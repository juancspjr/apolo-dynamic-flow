#!/usr/bin/env python3
"""
apolo_config.py — Configuracion centralizada de thresholds (v3.1.0).

Cierra el GAP #5.4 del INTEGRATION-VERDICT.md:
  "Thresholds hardcoded en gates — los thresholds de score_evidence
   (e.g., >= 0.6 para avanzar) estan hardcoded en TS, no son ajustables
   por flow ni por proyecto."

Este modulo carga `apolo-config.yaml` y expone thresholds configurables
que cualquier script Python puede consultar:

  from apolo_config import get_config, get_threshold
  cfg = get_config(repo_root)
  min_score = get_threshold(cfg, "gates.verdad.min_score", default=0.6)

CLI:
  init                          Crea apolo-config.yaml con defaults
  show                          Muestra configuracion actual
  get --key <path>              Obtiene un valor especifico
  set --key <path> --value <v>  Establece un valor (persiste)
  validate                      Valida contra schema interno
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


CONFIG_FILE = "apolo-config.yaml"


# ============================================================================
# Default configuration
# ============================================================================

DEFAULT_CONFIG = {
    "apoloconfig": "V1",
    "version": 1,
    "schema_version": "3.1.0",
    "generated_at": now_iso(),
    "description": "Configuracion centralizada de thresholds para apolo-dynamic-flow",

    # Gates por fase del state machine
    "gates": {
        "verdad": {
            "min_score": 0.6,           # score_evidence.py debe dar >= 0.6
            "min_items": 1,             # collect_evidence debe tener >= 1 item
            "min_hash_chain_length": 64, # SHA-256 = 64 chars hex
        },
        "plan_indice": {
            "min_units": 1,             # generate_plan debe producir >= 1 unidad
            "require_topological_sort": True,
        },
        "reanclaje": {
            "require_scaffold_concrete": True,  # scaffold debe tener files_to_create
            "min_files_to_create": 1,
            "min_files_to_modify": 0,
        },
        "exec": {
            "require_tests_pass": True,
            "max_test_failures": 0,
            "auto_rollback_on_fail": True,
        },
        "validar": {
            "min_final_score": 0.7,
            "require_consistent_evidence": True,
        },
    },

    # Circuit breaker
    "circuit_breaker": {
        "policy": "fail-closed",       # fail-closed | fail-open
        "max_loops_per_phase": {
            "init": 1,
            "verdad": 2,
            "plan_indice": 2,
            "reanclaje": 2,
            "exec": 4,
            "validar": 2,
            "merge": 1,
        },
        "max_consecutive_failures": 3,  # antes de escalate
        "max_total_failures": 5,        # antes de block
    },

    # Scoring de evidencia (pesos de las 6 metricas)
    "scoring": {
        "weights": {
            "coverage": 0.25,
            "freshness": 0.15,
            "depth": 0.20,
            "conflict": 0.15,
            "redundancy": 0.10,
            "schema": 0.15,
        },
        "freshness_stale_after_seconds": 300,  # 5 min
        "depth_max_symbols": 100,
    },

    # BFS multi-nivel en predict_impact
    "bfs": {
        "max_depth": 3,
        "max_nodes": 200,
        "risk_thresholds": {
            "low": 5,
            "medium": 15,
            "high": 30,
        },
    },

    # Code smells thresholds
    "code_smells": {
        "long_method_lines": 50,
        "deep_nesting_level": 4,
        "god_class_methods": 10,
        "duplicate_threshold": 0.8,
    },

    # Auto-hooks (v2.9.0)
    "auto_hooks": {
        "enabled": True,
        "timeout_per_script_seconds": 60,
        "max_parallel_scripts": 1,  # por ahora secuencial
    },

    # Post-script gates (v2.9.0)
    "post_script_gates": {
        "enabled": True,
        "default_on_fail": "warn",  # warn | block | continue
    },

    # v3.1.0: Auto-seleccion de U-NN
    "scaffold_v3": {
        "auto_select_unit": True,       # si True, no requiere --unit-id
        "selection_strategy": "topological_first",  # topological_first | highest_impact | lowest_risk
        "prefer_lowest_risk": True,
        "min_files_to_create": 1,
    },

    # v3.1.0: Cross-flow learning
    "cross_flow_learning": {
        "enabled": True,
        "lookback_flows": 10,           # analizar ultimos N flows
        "min_similarity_score": 0.7,    # para recomendar aprendizajes
        "storage": ".opencode/apolo-dynamic/CROSS-FLOW-LEARNING.yaml",
    },

    # v3.1.0: Evidence visual diff
    "evidence_visual_diff": {
        "enabled": True,
        "capture_baseline_on_init": True,
        "capture_broken_on_test_fail": True,
        "capture_post_fix_on_success": True,
        "diff_format": "unified",       # unified | json | html
        "max_diff_lines": 200,
    },

    # v3.1.0: Evidence replay
    "evidence_replay": {
        "enabled": True,
        "max_steps_per_replay": 50,
        "include_telemetry": True,
        "include_trace": True,
    },

    # Telemetry
    "telemetry": {
        "enabled": True,
        "panel_port": 8765,
        "auto_refresh_seconds": 3,
    },

    # Evidence collection
    "evidence_collection": {
        "auto_recollect_on_stale": True,
        "stale_check_interval_seconds": 300,
        "max_items_per_pack": 100,
    },
}


# ============================================================================
# Config loading
# ============================================================================

def config_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / CONFIG_FILE


def get_config(repo_root: Path) -> Dict[str, Any]:
    """Carga la configuracion. Si no existe, crea con defaults."""
    p = config_path(repo_root)
    if not p.exists():
        log("apolo-config.yaml no existe — creando con defaults", "INFO")
        init_config(repo_root)
    cfg = read_yaml(p) or {}
    # Merge con defaults para keys que falten
    return _merge_defaults(cfg, DEFAULT_CONFIG)


def init_config(repo_root: Path) -> Dict[str, Any]:
    """Crea apolo-config.yaml con defaults."""
    p = config_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_CONFIG)
    config["generated_at"] = now_iso()
    write_yaml(p, config)
    log(f"Configuracion creada: {p}", "INFO")
    return config


def save_config(repo_root: Path, config: Dict) -> None:
    write_yaml(config_path(repo_root), config)


def _merge_defaults(user_cfg: Dict, defaults: Dict) -> Dict:
    """Merge recursivo: user values override defaults, but defaults fill gaps."""
    result = dict(defaults)
    for k, v in user_cfg.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _merge_defaults(v, result[k])
        else:
            result[k] = v
    return result


# ============================================================================
# Threshold accessors
# ============================================================================

def get_threshold(config: Dict, key_path: str, default: Any = None) -> Any:
    """Obtiene un valor por path con dots (e.g., 'gates.verdad.min_score')."""
    parts = key_path.split(".")
    current = config
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def set_threshold(repo_root: Path, key_path: str, value: Any) -> Dict[str, Any]:
    """Establece un valor por path con dots y persiste."""
    config = get_config(repo_root)
    parts = key_path.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    # Convertir valor string a tipo apropiado
    if isinstance(value, str):
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        else:
            try:
                value = int(value)
            except ValueError:
                try:
                    value = float(value)
                except ValueError:
                    pass  # keep as string
    current[parts[-1]] = value
    save_config(repo_root, config)
    return config


# ============================================================================
# Validation
# ============================================================================

def validate_config(config: Dict) -> Dict[str, Any]:
    """Valida la configuracion contra reglas internas."""
    errors = []
    warnings = []

    # Gates
    gates = config.get("gates", {})
    verdad = gates.get("verdad", {})
    min_score = verdad.get("min_score", 0.6)
    if not isinstance(min_score, (int, float)) or min_score < 0 or min_score > 1:
        errors.append(f"gates.verdad.min_score debe estar entre 0 y 1, got {min_score}")

    min_items = verdad.get("min_items", 1)
    if not isinstance(min_items, int) or min_items < 0:
        errors.append(f"gates.verdad.min_items debe ser int >= 0, got {min_items}")

    # Circuit breaker
    cb = config.get("circuit_breaker", {})
    max_loops = cb.get("max_loops_per_phase", {})
    for phase, max_v in max_loops.items():
        if not isinstance(max_v, int) or max_v < 1:
            errors.append(f"circuit_breaker.max_loops_per_phase.{phase} debe ser int >= 1, got {max_v}")

    # Scoring weights deben sumar 1.0
    scoring = config.get("scoring", {})
    weights = scoring.get("weights", {})
    if weights:
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            warnings.append(f"scoring.weights suma {total:.3f}, deberia ser ~1.0")

    # BFS
    bfs = config.get("bfs", {})
    max_depth = bfs.get("max_depth", 3)
    if not isinstance(max_depth, int) or max_depth < 1 or max_depth > 10:
        warnings.append(f"bfs.max_depth={max_depth} fuera de rango recomendado [1, 10]")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "show"
    known = {"init", "show", "get", "set", "validate"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "init":
        config = init_config(repo_root)
        print(json.dumps({
            "success": True,
            "config_path": str(config_path(repo_root)),
            "version": config.get("schema_version"),
            "sections": list(config.keys()),
        }, indent=2))
        return 0

    elif action == "show":
        config = get_config(repo_root)
        print(json.dumps(config, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "get":
        key = args.get("key", "")
        if not key:
            print(json.dumps({"success": False, "error": "Falta --key"}, indent=2))
            return 2
        config = get_config(repo_root)
        value = get_threshold(config, key)
        print(json.dumps({"success": True, "key": key, "value": value}, indent=2, default=str))
        return 0

    elif action == "set":
        key = args.get("key", "")
        value = args.get("value", "")
        if not key or value == "":
            print(json.dumps({"success": False, "error": "Falta --key y --value"}, indent=2))
            return 2
        config = set_threshold(repo_root, key, value)
        new_value = get_threshold(config, key)
        print(json.dumps({"success": True, "key": key, "value": new_value, "persisted": True}, indent=2, default=str))
        return 0

    elif action == "validate":
        config = get_config(repo_root)
        result = validate_config(config)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0 if result["valid"] else 1

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

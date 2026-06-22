#!/usr/bin/env python3
"""
post_script_gates.py — Gates que validan contenido YAML, no solo exit code (v2.9.0).

Cierra el GAP #5.3 "Silent failures en scripts Python" del INTEGRATION-VERDICT.md:
si un script retorna YAML vacío pero exit code 0, el loop engine puede avanzar
de fase sin evidencia real. Este gate valida contenido post-script.

Define reglas en `apolo-post-script-gates.yaml`:
  - script: collect_evidence.py
    require:
      - path: items          # debe existir esta key
        type: list
        min_length: 1        # al menos 1 item
      - path: hash_chain
        type: string
        min_length: 64       # SHA-256
    on_fail: block           # block | warn | continue

  - script: score_evidence.py
    require:
      - path: score
        type: number
        min: 0.4             # score mínimo
    on_fail: block

  - script: generate_plan.py
    require:
      - path: unidades
        type: list
        min_length: 1
    on_fail: block

  - script: scaffold_impl.py
    require:
      - path: files_to_create
        type: list
        min_length: 1
      - path: files_to_modify
        type: list
        min_length: 0  # opcional pero debe existir la key
    on_fail: warn       # scaffold abstracto es warning, no bloqueo

CLI:
  init                          Crea apolo-post-script-gates.yaml con defaults
  list                          Lista gates configurados
  check --script <name> --output <yaml>   Valida un YAML contra las reglas del script
  check-all --flowid X          Valida todos los artifacts producidos en el flow
  enable/disable --script <s>   Activa/desactiva un gate
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


GATES_CONFIG_FILE = "apolo-post-script-gates.yaml"


# ============================================================================
# Default gates
# ============================================================================

DEFAULT_GATES = {
    "postscriptgates": "V1",
    "version": 2,
    "schema_version": "3.1.0",
    "generated_at": now_iso(),
    "enabled": True,
    "gates": [
        {
            "script": "collect_evidence.py",
            "enabled": True,
            "require": [
                {"path": "items", "type": "list", "min_length": 1, "description": "Al menos 1 item de evidencia"},
                {"path": "hash_chain", "type": "string", "min_length": 64, "description": "SHA-256 hash chain"},
            ],
            "on_fail": "block",
            "description": "Evidence pack debe tener al menos 1 item con hash chain válido",
        },
        {
            "script": "score_evidence.py",
            "enabled": True,
            "require": [
                {"path": "score", "type": "number", "min": 0.0, "max": 1.0, "description": "Score entre 0 y 1"},
                {"path": "metrics", "type": "dict", "description": "Métricas calculadas"},
            ],
            "on_fail": "warn",
            "description": "Score debe estar entre 0 y 1 con métricas",
        },
        {
            "script": "generate_plan.py",
            "enabled": True,
            "require": [
                {"path": "unidades", "type": "list", "min_length": 1, "description": "Al menos 1 unidad de trabajo"},
                {"path": "topological_sort", "type": "list", "description": "Orden topológico de unidades"},
            ],
            "on_fail": "block",
            "description": "Plan debe tener al menos 1 unidad con orden topológico",
        },
        {
            "script": "predict_impact.py",
            "enabled": True,
            "require": [
                {"path": "predictions", "type": "list", "description": "Lista de predicciones de impacto"},
            ],
            "on_fail": "warn",
            "description": "Predict impact debe producir predicciones (puede ser vacío si no hay afectados)",
        },
        {
            "script": "scaffold_impl.py",
            "enabled": True,
            "require": [
                {"path": "files_to_create", "type": "list", "description": "Lista de archivos a crear"},
                {"path": "files_to_modify", "type": "list", "description": "Lista de archivos a modificar"},
            ],
            "on_fail": "warn",
            "description": "Scaffold debe especificar files_to_create y files_to_modify (warn si vacío = scaffold abstracto)",
        },
        {
            "script": "index_codebase.py",
            "enabled": True,
            "require": [
                {"path": "files", "type": "list", "min_length": 1, "description": "Al menos 1 archivo indexado"},
            ],
            "on_fail": "block",
            "description": "Code index debe tener al menos 1 archivo",
        },
        {
            "script": "code_quality.py",
            "enabled": True,
            "require": [
                {"path": "total_files", "type": "number", "min": 0, "description": "Total de archivos analizados"},
            ],
            "on_fail": "warn",
            "description": "Code quality debe reportar total_files",
        },
        {
            "script": "test_coverage.py",
            "enabled": True,
            "require": [
                {"path": "coverage_percentage", "type": "number", "min": 0, "max": 100, "description": "Coverage 0-100%"},
            ],
            "on_fail": "warn",
            "description": "Test coverage debe reportar coverage_percentage",
        },
        {
            "script": "vulnerability_scanner.py",
            "enabled": True,
            "require": [
                {"path": "total_findings", "type": "number", "min": 0, "description": "Total de vulnerabilidades"},
                {"path": "tools_used", "type": "list", "description": "Herramientas utilizadas"},
            ],
            "on_fail": "warn",
            "description": "Vulnerability scanner debe reportar total_findings y tools_used",
        },
        {
            "script": "code_smells.py",
            "enabled": True,
            "require": [
                {"path": "summary", "type": "dict", "description": "Resumen de smells"},
            ],
            "on_fail": "warn",
            "description": "Code smells debe producir summary dict",
        },
        {
            "script": "full_audit.py",
            "enabled": True,
            "require": [
                {"path": "summary", "type": "dict", "description": "Resumen del audit"},
                {"path": "summary.final_score", "type": "number", "min": 0, "max": 100, "description": "Score final 0-100"},
                {"path": "summary.grade", "type": "string", "min_length": 1, "description": "Grade A-F"},
            ],
            "on_fail": "warn",
            "description": "Full audit debe producir summary con final_score y grade",
        },
        # === NUEVOS GATES v3.1.0 ===
        {
            "script": "scaffold_v3.py",
            "version_added": "3.1.0",
            "enabled": True,
            "require": [
                {"path": "files_to_create", "type": "list", "min_length": 1, "description": "Al menos 1 archivo concreto a crear (v3.1.0)"},
                {"path": "commands", "type": "list", "min_length": 1, "description": "Al menos 1 command accionable (v3.1.0)"},
                {"path": "summary.is_concrete", "type": "any", "description": "Flag de scaffold concreto"},
                {"path": "selection", "type": "dict", "description": "Metadata de auto-seleccion de U-NN"},
            ],
            "on_fail": "block",
            "description": "Scaffold v3 debe ser concreto: files_to_create + commands + selection metadata (GAP #5.1 cerrado)",
        },
        {
            "script": "evidence_visual_diff.py",
            "version_added": "3.1.0",
            "enabled": True,
            "require": [
                {"path": "snapshot_id", "type": "string", "min_length": 1, "description": "ID unico del snapshot"},
                {"path": "phase", "type": "string", "min_length": 1, "description": "Phase del snapshot (baseline/broken/post-fix)"},
                {"path": "files", "type": "list", "min_length": 1, "description": "Al menos 1 archivo en el snapshot"},
            ],
            "on_fail": "warn",
            "description": "Evidence visual diff debe capturar snapshots con phase y files (GAP #4)",
        },
        {
            "script": "evidence_replay.py",
            "version_added": "3.1.0",
            "enabled": True,
            "require": [
                {"path": "total_events", "type": "number", "min": 0, "description": "Total de eventos en timeline"},
            ],
            "on_fail": "warn",
            "description": "Evidence replay debe construir timeline con eventos (GAP #5)",
        },
        {
            "script": "cross_flow_learning.py",
            "version_added": "3.1.0",
            "enabled": True,
            "require": [
                {"path": "flows_analyzed", "type": "number", "min": 0, "description": "Flows analizados"},
                {"path": "patterns", "type": "dict", "description": "Patrones extraidos"},
            ],
            "on_fail": "warn",
            "description": "Cross-flow learning debe analizar flows y extraer patrones (GAP #6)",
        },
    ],
}


# ============================================================================
# Config management
# ============================================================================

def gates_config_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / GATES_CONFIG_FILE


def load_config(repo_root: Path) -> Dict[str, Any]:
    p = gates_config_path(repo_root)
    if not p.exists():
        log("apolo-post-script-gates.yaml no existe — creando con defaults", "INFO")
        init_config(repo_root)
    return read_yaml(p) or {}


def init_config(repo_root: Path) -> Dict[str, Any]:
    p = gates_config_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_GATES)
    config["generated_at"] = now_iso()
    write_yaml(p, config)
    log(f"Configuración de gates creada: {p}", "INFO")
    return config


def save_config(repo_root: Path, config: Dict) -> None:
    write_yaml(gates_config_path(repo_root), config)


# ============================================================================
# Path navigation in nested dicts
# ============================================================================

def get_path(data: Any, path: str) -> Any:
    """Obtiene un valor anidado por path con dots (e.g., 'summary.final_score')."""
    if not data:
        return None
    parts = path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
            except ValueError:
                return None
        else:
            return None
    return current


# ============================================================================
# Validation
# ============================================================================

def validate_value(value: Any, expected_type: str, spec: Dict) -> List[str]:
    """Valida un valor contra un tipo y especificación. Retorna lista de errores."""
    errors = []

    if expected_type == "list":
        if not isinstance(value, list):
            errors.append(f"expected list, got {type(value).__name__}")
            return errors
        min_len = spec.get("min_length")
        if min_len is not None and len(value) < min_len:
            errors.append(f"list length {len(value)} < min_length {min_len}")

    elif expected_type == "dict":
        if not isinstance(value, dict):
            errors.append(f"expected dict, got {type(value).__name__}")

    elif expected_type == "string":
        if not isinstance(value, str):
            errors.append(f"expected string, got {type(value).__name__}")
            return errors
        min_len = spec.get("min_length")
        if min_len is not None and len(value) < min_len:
            errors.append(f"string length {len(value)} < min_length {min_len}")

    elif expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"expected number, got {type(value).__name__}")
            return errors
        min_v = spec.get("min")
        max_v = spec.get("max")
        if min_v is not None and value < min_v:
            errors.append(f"value {value} < min {min_v}")
        if max_v is not None and value > max_v:
            errors.append(f"value {value} > max {max_v}")

    return errors


def check_gate(gate: Dict, yaml_data: Dict) -> Dict[str, Any]:
    """Ejecuta un gate contra un YAML. Retorna resultado de validación."""
    script_name = gate["script"]
    requirements = gate.get("require", [])
    on_fail = gate.get("on_fail", "warn")

    checks = []
    all_pass = True

    for req in requirements:
        path = req["path"]
        expected_type = req.get("type", "any")
        value = get_path(yaml_data, path)

        if value is None and expected_type != "any":
            checks.append({
                "path": path,
                "status": "FAIL",
                "error": f"path '{path}' not found in YAML",
                "description": req.get("description", ""),
            })
            all_pass = False
            continue

        errors = validate_value(value, expected_type, req)
        if errors:
            checks.append({
                "path": path,
                "status": "FAIL",
                "error": "; ".join(errors),
                "value_preview": str(value)[:100] if value is not None else None,
                "description": req.get("description", ""),
            })
            all_pass = False
        else:
            checks.append({
                "path": path,
                "status": "PASS",
                "value_preview": str(value)[:100] if value is not None else None,
                "description": req.get("description", ""),
            })

    return {
        "script": script_name,
        "enabled": gate.get("enabled", True),
        "on_fail": on_fail,
        "all_checks_pass": all_pass,
        "checks": checks,
        "action": "pass" if all_pass else on_fail,
    }


def check_script_output(repo_root: Path, script_name: str, yaml_path: Path) -> Dict[str, Any]:
    """Valida un YAML producido por un script contra las reglas configuradas."""
    config = load_config(repo_root)
    if not config.get("enabled", True):
        return {"script": script_name, "status": "skipped", "reason": "gates disabled globally"}

    # Buscar gate para este script
    gate = None
    for g in config.get("gates", []):
        if g["script"] == script_name:
            gate = g
            break

    if not gate:
        return {"script": script_name, "status": "no_gate", "message": "no gate configured for this script"}

    if not gate.get("enabled", True):
        return {"script": script_name, "status": "disabled"}

    if not yaml_path.exists():
        return {
            "script": script_name,
            "status": "fail",
            "action": gate.get("on_fail", "warn"),
            "error": f"YAML file not found: {yaml_path}",
        }

    try:
        yaml_data = read_yaml(yaml_path) or {}
    except Exception as e:
        return {
            "script": script_name,
            "status": "fail",
            "action": gate.get("on_fail", "warn"),
            "error": f"YAML parse error: {e}",
        }

    result = check_gate(gate, yaml_data)
    result["yaml_path"] = str(yaml_path)
    result["status"] = "pass" if result["all_checks_pass"] else "fail"
    return result


def check_all_flow_artifacts(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Valida todos los artifacts producidos en un flow."""
    flow_d = flow_dir(repo_root, flowid)
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"

    artifacts = [
        ("index_codebase.py", ci_path),
        ("collect_evidence.py", flow_d / "evidence" / "EVIDENCE-PACK.yaml"),
        ("score_evidence.py", flow_d / "evidence" / "EVIDENCE-SCORE.yaml"),
        ("generate_plan.py", flow_d / "plans" / "PLAN.yaml"),
        ("predict_impact.py", flow_d / "plans" / "IMPACT-PREDICTION.yaml"),
        ("scaffold_impl.py", flow_d / "scaffolds" / "SCAFFOLD.yaml"),
    ]

    results = []
    for script_name, path in artifacts:
        r = check_script_output(repo_root, script_name, path)
        results.append(r)

    # Determinar acción global
    block_count = sum(1 for r in results if r.get("action") == "block")
    warn_count = sum(1 for r in results if r.get("action") == "warn")
    pass_count = sum(1 for r in results if r.get("status") == "pass")

    if block_count > 0:
        overall_action = "block"
    elif warn_count > 0:
        overall_action = "warn"
    else:
        overall_action = "pass"

    return {
        "flowid": flowid,
        "total_artifacts": len(artifacts),
        "pass": pass_count,
        "warn": warn_count,
        "block": block_count,
        "overall_action": overall_action,
        "results": results,
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "list"
    known = {"init", "list", "check", "check-all", "enable", "disable"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "init":
        config = init_config(repo_root)
        print(json.dumps({"success": True, "config_path": str(gates_config_path(repo_root)), "gates": len(config["gates"])}, indent=2))
        return 0

    elif action == "list":
        config = load_config(repo_root)
        gates = []
        for g in config.get("gates", []):
            gates.append({
                "script": g["script"],
                "enabled": g.get("enabled", True),
                "on_fail": g.get("on_fail", "warn"),
                "requirements": len(g.get("require", [])),
            })
        print(json.dumps({"success": True, "total": len(gates), "gates": gates}, indent=2))
        return 0

    elif action == "check":
        script_name = args.get("script", "")
        yaml_path_str = args.get("output", "") or args.get("yaml", "")
        if not script_name or not yaml_path_str:
            print(json.dumps({"success": False, "error": "Falta --script y --output"}, indent=2))
            return 2
        result = check_script_output(repo_root, script_name, Path(yaml_path_str))
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        # Exit code: 0 if pass, 1 if block, 0 if warn (warn is informational)
        return 0 if result.get("action") in ("pass", "warn") else 1

    elif action == "check-all":
        flowid = args.get("flowid", "")
        if not flowid:
            print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
            return 2
        result = check_all_flow_artifacts(repo_root, flowid)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0 if result["overall_action"] != "block" else 1

    elif action == "enable":
        script_name = args.get("script", "")
        if not script_name:
            print(json.dumps({"success": False, "error": "Falta --script"}, indent=2))
            return 2
        config = load_config(repo_root)
        for g in config.get("gates", []):
            if g["script"] == script_name:
                g["enabled"] = True
                save_config(repo_root, config)
                print(json.dumps({"success": True, "enabled": script_name}, indent=2))
                return 0
        print(json.dumps({"success": False, "error": f"gate for {script_name} not found"}, indent=2))
        return 1

    elif action == "disable":
        script_name = args.get("script", "")
        if not script_name:
            print(json.dumps({"success": False, "error": "Falta --script"}, indent=2))
            return 2
        config = load_config(repo_root)
        for g in config.get("gates", []):
            if g["script"] == script_name:
                g["enabled"] = False
                save_config(repo_root, config)
                print(json.dumps({"success": True, "disabled": script_name}, indent=2))
                return 0
        print(json.dumps({"success": False, "error": f"gate for {script_name} not found"}, indent=2))
        return 1

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

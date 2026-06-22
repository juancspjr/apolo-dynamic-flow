#!/usr/bin/env python3
"""
auto_hooks.py — Ejecuta scripts Python automáticamente según el contexto (v3.1.0).

EXTENDIDO en v3.1.0: 4 nuevos triggers para integrar los nuevos scripts:
  - evidence:baseline-captured → capturar diff baseline (v3.1.0)
  - evidence:broken-captured → construir bug replay (v3.1.0)
  - evidence:post-fix-captured → comparar 3 estados (v3.1.0)
  - flow:completed → cross-flow learning analyze (v3.1.0)
  - scaffold:v3-produced → validar scaffold concreto (v3.1.0)

Total triggers v3.1.0: 14 (9 de v2.9.0 + 5 nuevos)

Mantiene compatibilidad total con v2.9.0 — los triggers existentes no cambian.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, flow_dir, state_path


HOOKS_CONFIG_FILE = "apolo-auto-hooks.yaml"
HOOKS_LOG_FILE = "AUTO-HOOKS-LOG.jsonl"


# ============================================================================
# Default hooks configuration (v3.1.0 — 14 triggers)
# ============================================================================

DEFAULT_HOOKS = {
    "autohooks": "V1",
    "version": 2,
    "schema_version": "3.1.0",
    "generated_at": now_iso(),
    "enabled": True,
    "triggers": [
        # === TRIGGERS v2.9.0 (sin cambios) ===
        {
            "name": "phase-complete:init",
            "enabled": True,
            "run": [
                {"script": "health_check.py", "args": ["--repo-root", "."], "timeout": 30},
            ],
            "condition": None,
            "description": "Después de init, ejecutar health check del entorno",
        },
        {
            "name": "phase-complete:plan-indice",
            "enabled": True,
            "run": [
                {"script": "cross_language_analyzer.py", "args": ["--repo-root", ".", "--code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"], "timeout": 60},
                {"script": "summarize_functions.py", "args": ["--repo-root", ".", "--code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"], "timeout": 60},
            ],
            "condition": "code_index_exists",
            "description": "Después de indexar codebase, análisis cross-language + resúmenes",
        },
        {
            "name": "evidence:collected",
            "enabled": True,
            "run": [
                {"script": "secret_scanner.py", "args": ["--scan-stdin"], "timeout": 30, "stdin_from": "evidence_files"},
            ],
            "condition": "items >= 1",
            "description": "Después de recolectar evidencia, escanear secretos en archivos",
        },
        {
            "name": "phase-complete:verdad",
            "enabled": True,
            "run": [
                {"script": "code_quality.py", "args": ["--repo-root", "."], "timeout": 120},
                {"script": "vulnerability_scanner.py", "args": ["--repo-root", "."], "timeout": 120},
            ],
            "condition": None,
            "description": "Después de fase verdad, análisis de calidad + vulnerabilidades",
        },
        {
            "name": "plan:generated",
            "enabled": True,
            "run": [],
            "condition": None,
            "description": "Placeholder — generate_plan no requiere hooks automáticos",
        },
        {
            "name": "scaffold:produced",
            "enabled": True,
            "run": [
                {"script": "code_smells.py", "args": ["--repo-root", ".", "--code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"], "timeout": 60},
            ],
            "condition": "scaffold_concrete",
            "description": "Después de producir scaffold, verificar code smells",
        },
        {
            "name": "phase-complete:reanclaje",
            "enabled": True,
            "run": [
                {"script": "test_coverage.py", "args": ["--repo-root", ".", "--code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"], "timeout": 120},
            ],
            "condition": None,
            "description": "Después de reanclaje, medir coverage",
        },
        {
            "name": "test:failed",
            "enabled": True,
            "run": [
                {"script": "self_healing.py", "args": ["--repo-root", "."], "timeout": 60},
            ],
            "condition": "consecutive_failures >= 3",
            "description": "Después de 3 fallos consecutivos, ejecutar self-healing",
        },
        {
            "name": "block:detected",
            "enabled": False,
            "run": [],
            "condition": None,
            "description": "Bloqueo detectado — escalado a operador (no automático)",
        },

        # === NUEVOS TRIGGERS v3.1.0 ===
        {
            "name": "evidence:baseline-captured",
            "enabled": True,
            "version_added": "3.1.0",
            "run": [],
            "condition": None,
            "description": "Baseline capturado por evidence_visual_diff — no requiere scripts adicionales (la captura es el trigger)",
        },
        {
            "name": "evidence:broken-captured",
            "enabled": True,
            "version_added": "3.1.0",
            "run": [
                {"script": "evidence_replay.py", "args": ["bug", "--repo-root", "."], "timeout": 30},
            ],
            "condition": None,
            "description": "Después de capturar estado broken, construir bug replay para análisis",
        },
        {
            "name": "evidence:post-fix-captured",
            "enabled": True,
            "version_added": "3.1.0",
            "run": [
                {"script": "evidence_visual_diff.py", "args": ["compare", "--repo-root", "."], "timeout": 30},
            ],
            "condition": None,
            "description": "Después de capturar post-fix, generar comparación visual completa (baseline vs broken vs post-fix)",
        },
        {
            "name": "flow:completed",
            "enabled": True,
            "version_added": "3.1.0",
            "run": [
                {"script": "cross_flow_learning.py", "args": ["analyze", "--repo-root", "."], "timeout": 60},
            ],
            "condition": None,
            "description": "Después de completar un flow, analizar todos los flows para cross-flow learning",
        },
        {
            "name": "scaffold:v3-produced",
            "enabled": True,
            "version_added": "3.1.0",
            "run": [
                {"script": "post_script_gates.py", "args": ["check", "--repo-root", ".", "--script", "scaffold_v3.py"], "timeout": 15},
            ],
            "condition": "scaffold_v3_concrete",
            "description": "Después de producir scaffold v3, validar con post-script gates que es concreto",
        },
    ],
}


# ============================================================================
# Config management (igual que v2.9.0 pero con version 2)
# ============================================================================

def hooks_config_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / HOOKS_CONFIG_FILE


def hooks_log_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / HOOKS_LOG_FILE


def load_config(repo_root: Path) -> Dict[str, Any]:
    p = hooks_config_path(repo_root)
    if not p.exists():
        log("apolo-auto-hooks.yaml no existe — creando con defaults v3.1.0", "INFO")
        init_config(repo_root)
    return read_yaml(p) or {}


def init_config(repo_root: Path) -> Dict[str, Any]:
    p = hooks_config_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_HOOKS)
    config["generated_at"] = now_iso()
    write_yaml(p, config)
    log(f"Configuración de hooks creada (v3.1.0 — 14 triggers): {p}", "INFO")
    return config


def save_config(repo_root: Path, config: Dict) -> None:
    write_yaml(hooks_config_path(repo_root), config)


# ============================================================================
# Logging
# ============================================================================

def log_hook_execution(repo_root: Path, event: Dict[str, Any]) -> None:
    p = hooks_log_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    event["at"] = now_iso()
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ============================================================================
# Condition evaluation (extended for v3.1.0)
# ============================================================================

def evaluate_condition(condition: Optional[str], repo_root: Path, flowid: str = "") -> bool:
    if not condition:
        return True

    if condition == "code_index_exists":
        return (repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml").exists()
    if condition == "scaffold_concrete":
        if not flowid:
            return False
        sf = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD.yaml"
        if not sf.exists():
            return False
        data = read_yaml(sf) or {}
        return bool(data.get("files_to_create") or data.get("files_to_modify") or data.get("commands"))
    # v3.1.0: condition for scaffold_v3
    if condition == "scaffold_v3_concrete":
        if not flowid:
            return False
        sf = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD-V3.yaml"
        if not sf.exists():
            # Try default name
            sf = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD.yaml"
            if not sf.exists():
                return False
        data = read_yaml(sf) or {}
        return bool(data.get("files_to_create"))

    if condition.startswith("items >= "):
        threshold = int(condition.split(">=")[1].strip())
        if not flowid:
            return False
        ev = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
        if not ev.exists():
            return False
        data = read_yaml(ev) or {}
        return len(data.get("items", [])) >= threshold

    if condition.startswith("consecutive_failures >= "):
        threshold = int(condition.split(">=")[1].strip())
        return threshold > 0  # placeholder

    log(f"Condición no reconocida: {condition} — asumiendo True", "WARN")
    return True


# ============================================================================
# Script execution
# ============================================================================

def execute_script(script_name: str, args: List[str], repo_root: Path, timeout: int = 60, stdin_data: str = "") -> Dict[str, Any]:
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        return {
            "script": script_name,
            "status": "skipped",
            "reason": f"not found at {script_path}",
        }

    cmd = ["python3", str(script_path)] + args
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            input=stdin_data if stdin_data else None,
        )
        duration_ms = int((time.time() - start) * 1000)
        return {
            "script": script_name,
            "status": "success" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "duration_ms": duration_ms,
            "stdout": result.stdout[:1000] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "script": script_name,
            "status": "timeout",
            "duration_ms": timeout * 1000,
        }
    except Exception as e:
        return {
            "script": script_name,
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# Trigger execution
# ============================================================================

def fire_trigger(repo_root: Path, trigger_name: str, flowid: str = "", context: Dict = None) -> Dict[str, Any]:
    config = load_config(repo_root)
    if not config.get("enabled", True):
        return {"trigger": trigger_name, "status": "skipped", "reason": "auto-hooks disabled globally"}

    trigger = None
    for t in config.get("triggers", []):
        if t.get("name") == trigger_name:
            trigger = t
            break

    if not trigger:
        return {"trigger": trigger_name, "status": "not_found"}

    if not trigger.get("enabled", True):
        return {"trigger": trigger_name, "status": "disabled"}

    condition = trigger.get("condition")
    if not evaluate_condition(condition, repo_root, flowid):
        log(f"Trigger {trigger_name} omitido — condición no cumplida: {condition}", "INFO")
        return {
            "trigger": trigger_name,
            "status": "condition_not_met",
            "condition": condition,
        }

    results = []
    for script_spec in trigger.get("run", []):
        script_name = script_spec["script"]
        args = script_spec.get("args", [])
        timeout = script_spec.get("timeout", 60)

        stdin_data = ""
        if script_spec.get("stdin_from") == "evidence_files" and flowid:
            ev = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
            if ev.exists():
                stdin_data = ev.read_text(encoding="utf-8", errors="replace")[:10000]

        log(f"  → Ejecutando {script_name} {args}", "INFO")
        result = execute_script(script_name, args, repo_root, timeout, stdin_data)
        results.append(result)

        log_hook_execution(repo_root, {
            "trigger": trigger_name,
            "flowid": flowid,
            "script": script_name,
            "status": result["status"],
            "duration_ms": result.get("duration_ms", 0),
        })

    success_count = sum(1 for r in results if r["status"] == "success")
    return {
        "trigger": trigger_name,
        "status": "executed",
        "flowid": flowid,
        "scripts_run": len(results),
        "scripts_success": success_count,
        "scripts_failed": len(results) - success_count,
        "results": results,
    }


# ============================================================================
# Status
# ============================================================================

def get_status(repo_root: Path, flowid: str = "") -> Dict[str, Any]:
    config = load_config(repo_root)
    log_p = hooks_log_path(repo_root)

    log_entries = []
    if log_p.exists():
        for line in log_p.read_text(encoding="utf-8").splitlines()[-50:]:
            line = line.strip()
            if not line:
                continue
            try:
                log_entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    trigger_stats: Dict[str, Dict] = {}
    for entry in log_entries:
        t = entry.get("trigger", "")
        if t not in trigger_stats:
            trigger_stats[t] = {"total": 0, "success": 0, "failed": 0, "last_at": ""}
        trigger_stats[t]["total"] += 1
        if entry.get("status") == "success":
            trigger_stats[t]["success"] += 1
        else:
            trigger_stats[t]["failed"] += 1
        trigger_stats[t]["last_at"] = entry.get("at", "")

    # v3.1.0: contar triggers por version
    v290_triggers = sum(1 for t in config.get("triggers", []) if not t.get("version_added"))
    v310_triggers = sum(1 for t in config.get("triggers", []) if t.get("version_added") == "3.1.0")

    return {
        "config_enabled": config.get("enabled", True),
        "config_version": config.get("schema_version", "3.1.0"),
        "total_triggers": len(config.get("triggers", [])),
        "enabled_triggers": sum(1 for t in config.get("triggers", []) if t.get("enabled", True)),
        "v290_triggers": v290_triggers,
        "v310_triggers": v310_triggers,
        "log_entries": len(log_entries),
        "trigger_stats": trigger_stats,
        "last_10_executions": log_entries[-10:],
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "list"
    known = {"list", "trigger", "run", "enable", "disable", "init", "status"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if action == "init":
        config = init_config(repo_root)
        print(json.dumps({
            "success": True,
            "config_path": str(hooks_config_path(repo_root)),
            "version": config.get("schema_version"),
            "triggers": len(config["triggers"]),
            "v290_triggers": sum(1 for t in config["triggers"] if not t.get("version_added")),
            "v310_triggers": sum(1 for t in config["triggers"] if t.get("version_added") == "3.1.0"),
        }, indent=2))
        return 0

    elif action == "list":
        config = load_config(repo_root)
        triggers = []
        for t in config.get("triggers", []):
            triggers.append({
                "name": t["name"],
                "enabled": t.get("enabled", True),
                "version": t.get("version_added", "2.9.0"),
                "scripts": [s["script"] for s in t.get("run", [])],
                "condition": t.get("condition"),
                "description": t.get("description", ""),
            })
        print(json.dumps({"success": True, "total": len(triggers), "triggers": triggers}, ensure_ascii=False, indent=2))
        return 0

    elif action == "trigger":
        name = args.get("name", "")
        if not name:
            print(json.dumps({"success": False, "error": "Falta --name"}, indent=2))
            return 2
        result = fire_trigger(repo_root, name, flowid)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in ("executed", "condition_not_met", "disabled") else 1

    elif action == "run":
        phase = args.get("phase", "")
        if not phase:
            sp = state_path(repo_root, flowid) if flowid else None
            if sp and sp.exists():
                state = read_yaml(sp) or {}
                phase = state.get("phase", "")
        if not phase:
            print(json.dumps({"success": False, "error": "Falta --phase (no se pudo leer del state)"}, indent=2))
            return 2

        trigger_name = f"phase-complete:{phase}"
        result = fire_trigger(repo_root, trigger_name, flowid)
        print(json.dumps({"success": True, "phase": phase, "trigger": trigger_name, **result}, ensure_ascii=False, indent=2))
        return 0

    elif action == "enable":
        name = args.get("name", "")
        if not name:
            print(json.dumps({"success": False, "error": "Falta --name"}, indent=2))
            return 2
        config = load_config(repo_root)
        for t in config.get("triggers", []):
            if t["name"] == name:
                t["enabled"] = True
                save_config(repo_root, config)
                print(json.dumps({"success": True, "enabled": name}, indent=2))
                return 0
        print(json.dumps({"success": False, "error": f"trigger {name} not found"}, indent=2))
        return 1

    elif action == "disable":
        name = args.get("name", "")
        if not name:
            print(json.dumps({"success": False, "error": "Falta --name"}, indent=2))
            return 2
        config = load_config(repo_root)
        for t in config.get("triggers", []):
            if t["name"] == name:
                t["enabled"] = False
                save_config(repo_root, config)
                print(json.dumps({"success": True, "disabled": name}, indent=2))
                return 0
        print(json.dumps({"success": False, "error": f"trigger {name} not found"}, indent=2))
        return 1

    elif action == "status":
        result = get_status(repo_root, flowid)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

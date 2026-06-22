#!/usr/bin/env python3
"""
self_healing_loop.py — Loop que detecta y auto-repara fallas del sistema (v3.5.1).

RESPONDE a tu indicacion: "el agente se de cuenta de los errores del sistema
el sistema ayuda"

Este script MONITOREA el sistema continuamente y cuando detecta una falla:
  1. La diagnostica (guided_recovery)
  2. Intenta repararla automaticamente si es segura
  3. Si no es segura, ofrece escape hatch al agente
  4. Registra todo en telemetry para aprendizaje

Tipos de auto-repair que hace:
  - Missing dependency → pip install (con confirmacion)
  - Missing directory → mkdir -p
  - Missing config file → init con defaults
  - YAML parse error → intentar reconstruir desde backup
  - Permission denied → chmod (con confirmacion)

CLI:
  python3 self_healing_loop.py monitor --flowid X --repo-root . [--interval 30]
  python3 self_healing_loop.py check --flowid X --repo-root .
  python3 self_healing_loop.py repair --flowid X --error "..." [--dry-run]
"""

from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir, telemetry_path, run_cmd


# ============================================================================
# Auto-repair strategies (SAFE repairs only)
# ============================================================================

SAFE_REPAIRS = {
    "missing_directory": {
        "check": lambda repo_root, details: not (repo_root / details).exists() if details else False,
        "repair": lambda repo_root, details: _mkdir(repo_root / details),
        "description": "Crear directorio faltante",
        "safe": True,
    },
    "missing_config": {
        "check": lambda repo_root, details: not (repo_root / ".opencode" / "apolo-dynamic" / details).exists(),
        "repair": lambda repo_root, details: _init_config(repo_root, details),
        "description": "Inicializar config con defaults",
        "safe": True,
    },
    "stale_lock": {
        "check": lambda repo_root, details: _check_stale_lock(repo_root, details),
        "repair": lambda repo_root, details: _remove_stale_lock(repo_root, details),
        "description": "Remover lock stale (modificado hace >30min)",
        "safe": True,
    },
    "empty_telemetry": {
        "check": lambda repo_root, details: _check_empty_telemetry(repo_root, details),
        "repair": lambda repo_root, details: _init_telemetry(repo_root, details),
        "description": "Inicializar telemetry.jsonl vacio",
        "safe": True,
    },
}

UNSAFE_REPAIRS = {
    "missing_dependency": {
        "description": "Instalar paquete Python faltante",
        "repair": lambda module: f"pip3 install --user {module}",
        "requires_confirmation": True,
    },
    "permission_denied": {
        "description": "Cambiar permisos de archivo",
        "repair": lambda file: f"chmod +x {file}",
        "requires_confirmation": True,
    },
    "yaml_corrupt": {
        "description": "Reconstruir YAML desde backup",
        "repair": lambda file: f"Restaurar {file} desde .bak",
        "requires_confirmation": True,
    },
}


def _mkdir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _init_config(repo_root: Path, config_name: str) -> bool:
    try:
        config_map = {
            "apolo-config.yaml": "apolo_config.py",
            "apolo-auto-hooks.yaml": "auto_hooks.py",
            "apolo-post-script-gates.yaml": "post_script_gates.py",
        }
        script = config_map.get(config_name)
        if not script:
            return False
        script_path = repo_root / "scripts" / "python" / script
        if script_path.exists():
            code, out, err = run_cmd(["python3", str(script_path), "init", "--repo-root", str(repo_root)], timeout=15)
            return code == 0
        return False
    except Exception:
        return False


def _check_stale_lock(repo_root: Path, flowid: str) -> bool:
    lock_path = flow_dir(repo_root, flowid) / "FLOW-LOCK"
    if not lock_path.exists():
        return False
    # Check if lock is older than 30 minutes
    import os.path
    age = time.time() - os.path.getmtime(lock_path)
    return age > 1800  # 30 min


def _remove_stale_lock(repo_root: Path, flowid: str) -> bool:
    lock_path = flow_dir(repo_root, flowid) / "FLOW-LOCK"
    try:
        lock_path.unlink()
        return True
    except Exception:
        return False


def _check_empty_telemetry(repo_root: Path, flowid: str) -> bool:
    tel_path = telemetry_path(repo_root, flowid)
    return not tel_path.exists() or tel_path.stat().st_size == 0


def _init_telemetry(repo_root: Path, flowid: str) -> bool:
    tel_path = telemetry_path(repo_root, flowid)
    tel_path.parent.mkdir(parents=True, exist_ok=True)
    tel_path.write_text("", encoding="utf-8")
    return True


def check_system_health(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica salud del sistema y detecta problemas."""
    issues = []

    # 1. Verificar directorios criticos
    for d in [".opencode/apolo-dynamic", "plan/active", "scripts/python", "scripts/bash"]:
        if not (repo_root / d).exists():
            issues.append({"type": "missing_directory", "details": d, "severity": "high"})

    # 2. Verificar configs
    for cfg in ["apolo-config.yaml", "apolo-auto-hooks.yaml", "apolo-post-script-gates.yaml"]:
        if not (repo_root / ".opencode" / "apolo-dynamic" / cfg).exists():
            issues.append({"type": "missing_config", "details": cfg, "severity": "medium"})

    # 3. Verificar telemetry
    if _check_empty_telemetry(repo_root, flowid):
        issues.append({"type": "empty_telemetry", "details": flowid, "severity": "low"})

    # 4. Verificar stale locks
    if _check_stale_lock(repo_root, flowid):
        issues.append({"type": "stale_lock", "details": flowid, "severity": "medium"})

    # 5. Verificar errores en telemetry reciente
    tel_path = telemetry_path(repo_root, flowid)
    if tel_path.exists():
        for line in tel_path.read_text(encoding="utf-8").splitlines()[-20:]:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if event.get("severity") == "error":
                    issues.append({
                        "type": "error_in_telemetry",
                        "details": event.get("message", "")[:200],
                        "severity": "high",
                        "event": event,
                    })
            except json.JSONDecodeError:
                continue

    return {
        "flowid": flowid,
        "checked_at": now_iso(),
        "issues_found": len(issues),
        "issues": issues,
        "healthy": len([i for i in issues if i["severity"] == "high"]) == 0,
    }


def auto_repair(repo_root: Path, flowid: str, dry_run: bool = False) -> Dict[str, Any]:
    """Ejecuta auto-repair de problemas seguros."""
    health = check_system_health(repo_root, flowid)
    repairs_attempted = []
    repairs_succeeded = []
    repairs_failed = []
    unsafe_issues = []

    for issue in health["issues"]:
        issue_type = issue["type"]
        issue_details = issue["details"]

        if issue_type in SAFE_REPAIRS:
            repair_config = SAFE_REPAIRS[issue_type]
            repairs_attempted.append(issue_type)

            if dry_run:
                repairs_succeeded.append({
                    "type": issue_type,
                    "details": issue_details,
                    "action": repair_config["description"],
                    "dry_run": True,
                })
                continue

            # Ejecutar repair
            try:
                success = repair_config["repair"](repo_root, issue_details)
                if success:
                    repairs_succeeded.append({
                        "type": issue_type,
                        "details": issue_details,
                        "action": repair_config["description"],
                    })
                    log(f"  ✓ Auto-repair: {repair_config['description']} ({issue_details})", "INFO")
                else:
                    repairs_failed.append({
                        "type": issue_type,
                        "details": issue_details,
                        "error": "Repair function returned False",
                    })
            except Exception as e:
                repairs_failed.append({
                    "type": issue_type,
                    "details": issue_details,
                    "error": str(e),
                })

        elif issue_type in UNSAFE_REPAIRS:
            unsafe_issues.append({
                "type": issue_type,
                "details": issue_details,
                "description": UNSAFE_REPAIRS[issue_type]["description"],
                "requires_confirmation": True,
            })

        elif issue_type == "error_in_telemetry":
            # Usar guided_recovery para diagnosticar
            error_msg = issue.get("details", "")
            try:
                from guided_recovery import diagnose_error
                diagnosis = diagnose_error(repo_root, flowid, error_msg)
                unsafe_issues.append({
                    "type": issue_type,
                    "details": error_msg,
                    "diagnosis": diagnosis.get("recommended_fix", {}),
                    "requires_confirmation": True,
                })
            except Exception:
                unsafe_issues.append({
                    "type": issue_type,
                    "details": error_msg,
                    "requires_confirmation": True,
                })

    # Log repairs
    repair_log = {
        "at": now_iso(),
        "flowid": flowid,
        "dry_run": dry_run,
        "attempted": len(repairs_attempted),
        "succeeded": len(repairs_succeeded),
        "failed": len(repairs_failed),
        "unsafe": len(unsafe_issues),
    }
    tel_path = telemetry_path(repo_root, flowid)
    tel_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tel_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": now_iso(), "flowid": flowid,
            "kind": "self-healing-repair",
            "severity": "info" if len(repairs_failed) == 0 else "warn",
            "message": f"Auto-repair: {len(repairs_succeeded)} OK, {len(repairs_failed)} fail, {len(unsafe_issues)} unsafe",
        }) + "\n")

    return {
        "success": True,
        "flowid": flowid,
        "dry_run": dry_run,
        "repairs_attempted": len(repairs_attempted),
        "repairs_succeeded": repairs_succeeded,
        "repairs_failed": repairs_failed,
        "unsafe_issues": unsafe_issues,
        "message": f"Auto-repair: {len(repairs_succeeded)} OK, {len(repairs_failed)} fail, {len(unsafe_issues)} requieren confirmacion",
    }


def monitor(repo_root: Path, flowid: str, interval: int = 30, max_iterations: int = 0) -> Dict[str, Any]:
    """Monitorea el sistema continuamente."""
    log(f"SELF-HEALING MONITOR: revisando cada {interval}s (flowid={flowid})", "INFO")
    iterations = 0
    total_repairs = 0

    while max_iterations == 0 or iterations < max_iterations:
        iterations += 1
        log(f"\n--- Iteracion {iterations} ---", "INFO")

        health = check_system_health(repo_root, flowid)
        log(f"  Health: {health['issues_found']} issues, healthy={health['healthy']}", "INFO")

        if health["issues_found"] > 0:
            repair_result = auto_repair(repo_root, flowid, dry_run=False)
            total_repairs += repair_result["repairs_attempted"]
            log(f"  Repairs: {repair_result['message']}", "INFO")

            if repair_result["unsafe_issues"]:
                log(f"  ⚠ {len(repair_result['unsafe_issues'])} issues requieren atencion manual", "WARN")

        time.sleep(interval)

    return {
        "success": True,
        "flowid": flowid,
        "iterations": iterations,
        "total_repairs_attempted": total_repairs,
        "message": f"Monitor completo: {iterations} iteraciones, {total_repairs} repairs",
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "check"
    known = {"monitor", "check", "repair"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid and action != "check":
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "monitor":
        interval = int(args.get("interval", "30"))
        max_iter = int(args.get("max-iterations", "0"))
        r = monitor(repo_root, flowid, interval, max_iter)
        print(json.dumps(r, indent=2)); return 0
    elif action == "check":
        r = check_system_health(repo_root, flowid or "DEFAULT")
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0 if r["healthy"] else 1
    elif action == "repair":
        dry = args.get("dry-run", "false") == "true"
        r = auto_repair(repo_root, flowid, dry)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

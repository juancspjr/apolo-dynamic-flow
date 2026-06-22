#!/usr/bin/env python3
"""
smart_rollback.py — Detectar qué parte del MP falló y revertir solo esa (v3.4.0).

Cierra el GAP: "Rollback inteligente: detectar qué parte del MP falló y revertir solo esa"

En lugar de hacer git checkout de todo el repo, este script:
  1. Analiza que archivos fueron modificados por el MP actual
  2. Identifica cuales causaron el fallo (via test failures + evidence_replay)
  3. Revierte SOLO esos archivos, preservando el resto del trabajo

CLI:
  # Analizar que archivos causaron el fallo
  python3 smart_rollback.py analyze --flowid X --repo-root .

  # Ejecutar rollback inteligente (solo archivos que fallaron)
  python3 smart_rollback.py rollback --flowid X --repo-root . [--dry-run]

  # Ver que se revertiria sin ejecutar
  python3 smart_rollback.py preview --flowid X --repo-root .
"""

from __future__ import annotations
import json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir, run_cmd


def get_modified_files(repo_root: Path) -> List[str]:
    """Obtiene archivos modificados desde el ultimo commit."""
    code, out, err = run_cmd(["git", "diff", "--name-only", "HEAD"], cwd=repo_root, timeout=10)
    if code != 0:
        return []
    return [f.strip() for f in out.splitlines() if f.strip()]


def get_failing_files_from_telemetry(repo_root: Path, flowid: str) -> List[str]:
    """Identifica archivos que causaron fallos via telemetry."""
    tel_path = repo_root / "plan" / "active" / flowid / "telemetry.jsonl"
    if not tel_path.exists():
        return []

    failing_files = set()
    for line in tel_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Si es un evento de error o test failure
        if event.get("severity") == "error" or "fail" in event.get("kind", "").lower():
            # Buscar archivos en el payload
            payload = event.get("payload", {})
            files = payload.get("files", []) or payload.get("targets", [])
            if isinstance(files, list):
                failing_files.update(files)
            # Si el message menciona un archivo
            msg = event.get("message", "")
            for mod in get_modified_files(repo_root):
                if mod in msg:
                    failing_files.add(mod)
    return list(failing_files)


def get_failing_files_from_scaffold(repo_root: Path, flowid: str) -> List[str]:
    """Obtiene archivos del scaffold que se crearon/modificaron."""
    scaffold_path = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD-V3.yaml"
    if not scaffold_path.exists():
        return []
    scaffold = read_yaml(scaffold_path) or {}
    files = []
    for f in scaffold.get("files_to_create", []):
        files.append(f.get("path", ""))
    for f in scaffold.get("files_to_modify", []):
        files.append(f.get("path", ""))
    return [f for f in files if f]


def analyze_failure(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Analiza que archivos causaron el fallo."""
    modified = get_modified_files(repo_root)
    failing_from_tel = get_failing_files_from_telemetry(repo_root, flowid)
    scaffold_files = get_failing_files_from_scaffold(repo_root, flowid)

    # Interseccion: archivos modificados Y mencionados en fallos
    to_rollback = set(failing_from_tel) & set(modified)
    # Si no hay interseccion clara, revertir todos los del scaffold que fueron modificados
    if not to_rollback:
        to_rollback = set(scaffold_files) & set(modified)

    return {
        "flowid": flowid,
        "analyzed_at": now_iso(),
        "modified_files": modified,
        "failing_files_from_telemetry": failing_from_tel,
        "scaffold_files": scaffold_files,
        "files_to_rollback": sorted(to_rollback),
        "files_to_preserve": sorted(set(modified) - to_rollback),
        "total_modified": len(modified),
        "total_to_rollback": len(to_rollback),
    }


def execute_rollback(repo_root: Path, flowid: str, dry_run: bool = False) -> Dict[str, Any]:
    """Ejecuta rollback inteligente."""
    analysis = analyze_failure(repo_root, flowid)
    files_to_rollback = analysis["files_to_rollback"]

    if not files_to_rollback:
        return {"success": True, "message": "No hay archivos para revertir", "rolled_back": []}

    rolled_back = []
    for f in files_to_rollback:
        if dry_run:
            rolled_back.append({"file": f, "action": "would_revert"})
            log(f"  [DRY-RUN] Revertiria: {f}", "INFO")
        else:
            code, out, err = run_cmd(["git", "checkout", "HEAD", "--", f], cwd=repo_root, timeout=10)
            if code == 0:
                rolled_back.append({"file": f, "action": "reverted"})
                log(f"  ✓ Revertido: {f}", "INFO")
            else:
                rolled_back.append({"file": f, "action": "failed", "error": err})
                log(f"  ✗ Fallo revertir: {f} — {err}", "ERROR")

    # Guardar reporte
    report = {**analysis, "rollback_executed": not dry_run, "rolled_back": rolled_back, "executed_at": now_iso()}
    write_yaml(flow_dir(repo_root, flowid) / "ROLLBACK-REPORT.yaml", report)

    return {"success": True, "rolled_back": len(rolled_back), "preserved": len(analysis["files_to_preserve"]), "dry_run": dry_run, "report": report}


def main() -> int:
    argv = sys.argv[1:]
    action = "analyze"
    known = {"analyze", "rollback", "preview"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")
    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "analyze":
        r = analyze_failure(repo_root, flowid)
        print(json.dumps({"success": True, **r}, indent=2, default=str)); return 0
    elif action == "rollback":
        dry = args.get("dry-run", "false") == "true"
        r = execute_rollback(repo_root, flowid, dry)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    elif action == "preview":
        r = execute_rollback(repo_root, flowid, dry_run=True)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

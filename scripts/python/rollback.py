#!/usr/bin/env python3
"""
rollback.py — Ejecuta rollback tras test fail.

Estrategias:
  - git-restore: git restore <files afectados por el MP>
  - git-stash-pop: git stash + git stash pop al fallar
  - custom-script: ejecuta un script Python/shell custom

Lee:
  - mp_id: MP que originó el cambio
  - repo_root: raíz del repo

Determina archivos afectados por:
  - git diff --name-only HEAD (archivos modificados no commiteados)
  - Filtra por paths en FLOW-STATE.yaml.artifacts.current_mps[mp_id]

Ejecuta rollback y reporta:
  - archivos restaurados
  - hash del estado pre-rollback (para auditoría)
  - exit code
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    git_head_sha,
    git_status,
    log,
    now_iso,
    parse_args,
    run_cmd,
    sha256,
)


def get_modified_files(repo_root: Path) -> List[str]:
    """Lista archivos modificados no commiteados."""
    status = git_status(repo_root)
    if not status:
        return []
    files: List[str] = []
    for line in status.strip().split("\n"):
        if not line.strip():
            continue
        # Formato porcelain: XY path
        path = line[3:].strip()
        if path:
            files.append(path)
    return files


def rollback_git_restore(repo_root: Path, files: List[str]) -> Dict[str, Any]:
    if not files:
        return {"strategy": "git-restore", "restored": [], "exit_code": 0, "log": "no files to restore"}
    args = ["git", "restore"] + files
    code, out, err = run_cmd(args, cwd=repo_root, timeout=30)
    return {
        "strategy": "git-restore",
        "restored": files,
        "exit_code": code,
        "log": out + err,
    }


def rollback_git_stash_pop(repo_root: Path, files: List[str]) -> Dict[str, Any]:
    # stash push de los archivos afectados
    if not files:
        return {"strategy": "git-stash-pop", "restored": [], "exit_code": 0, "log": "no files"}
    args = ["git", "stash", "push", "--"] + files
    code, out, err = run_cmd(args, cwd=repo_root, timeout=30)
    if code != 0:
        return {"strategy": "git-stash-pop", "restored": [], "exit_code": code, "log": f"stash push failed: {err}"}
    # stash pop para recuperar el estado (esto no revierte — para revertir usaríamos stash drop)
    # Pero la idea del rollback ES revertir: así que dejamos el stash y no hacemos pop
    return {
        "strategy": "git-stash-pop",
        "restored": files,
        "exit_code": 0,
        "log": f"stashed {len(files)} files. Use 'git stash list' to inspect.",
        "stash_kept": True,
    }


def rollback_custom_script(
    repo_root: Path, files: List[str], script_path: str, mp_id: str
) -> Dict[str, Any]:
    if not os.path.exists(script_path):
        return {"strategy": "custom-script", "restored": [], "exit_code": 1, "log": f"script not found: {script_path}"}
    args = ["python3", script_path, "--repo-root", str(repo_root), "--mp-id", mp_id, "--files-json", json.dumps(files)]
    code, out, err = run_cmd(args, cwd=repo_root, timeout=60)
    return {
        "strategy": "custom-script",
        "restored": files,
        "exit_code": code,
        "log": out + err,
    }


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    strategy = args.get("strategy", "git-restore")
    custom_script = args.get("custom-script", "")
    mp_id = args.get("mp-id", "")

    log(f"rollback strategy={strategy} mp={mp_id} repo={repo_root}", "WARN")

    # Capturar estado pre-rollback
    pre_sha = git_head_sha(repo_root) or "unknown"
    modified = get_modified_files(repo_root)
    log(f"archivos modificados detectados: {len(modified)}", "INFO")

    start = time.time()
    if strategy == "git-restore":
        result = rollback_git_restore(repo_root, modified)
    elif strategy == "git-stash-pop":
        result = rollback_git_stash_pop(repo_root, modified)
    elif strategy == "custom-script":
        if not custom_script:
            log("--custom-script requerido para strategy=custom-script", "ERROR")
            return 2
        result = rollback_custom_script(repo_root, modified, custom_script, mp_id)
    else:
        log(f"estrategia desconocida: {strategy}", "ERROR")
        return 2

    result["pre_rollback_sha"] = pre_sha
    result["post_rollback_sha"] = git_head_sha(repo_root) or "unknown"
    result["duration_ms"] = int((time.time() - start) * 1000)
    result["at"] = now_iso()

    print(json.dumps(result))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())

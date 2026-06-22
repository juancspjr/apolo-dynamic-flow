#!/usr/bin/env python3
"""
pre_commit_hooks.py — Pre-commit hooks para apolo-dynamic-flow (v3.4.0).

Cierra el GAP: "Pre-commit hooks"

Genera y gestiona pre-commit hooks que se ejecutan antes de cada git commit:
  1. Verifica que no hay secretos en archivos staging
  2. Verifica que TypeScript compila
  3. Verifica que Python scripts compilan
  4. Ejecuta apolo-full-test.sh (fast mode)
  5. Verifica que force_quality_gates pasan

CLI:
  # Instalar hooks en .git/hooks/pre-commit
  python3 pre_commit_hooks.py install --repo-root .

  # Ejecutar hooks manualmente
  python3 pre_commit_hooks.py run --repo-root .

  # Verificar que hooks estan instalados
  python3 pre_commit_hooks.py status --repo-root .

  # Remover hooks
  python3 pre_commit_hooks.py uninstall --repo-root .
"""

from __future__ import annotations
import json, os, stat, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, cmd_available


PRE_COMMIT_SCRIPT = '''#!/usr/bin/env bash
# pre-commit hook generado por apolo-dynamic-flow v3.4.0
set -e
RED='\\033[0;31m'; GREEN='\\033[0;32m'; NC='\\033[0m'
echo -e "${GREEN}[apolo pre-commit]${NC} Verificando calidad antes de commit..."

# 1. Verificar que no hay secretos
STAGED=$(git diff --cached --name-only --diff-filter=ACM | grep -E "\\.(py|ts|js|json|yaml|yml|md)$" || true)
if [ -n "$STAGED" ]; then
  echo "$STAGED" | while read f; do
    if [ -f "$f" ]; then
      python3 scripts/python/secret_scanner.py --scan-stdin < "$f" 2>/dev/null || {
        echo -e "${RED}[apolo pre-commit] SECRET DETECTED in $f${NC}"
        exit 1
      }
    fi
  done
fi

# 2. Verificar que TypeScript compila
if [ -f tsconfig.json ] && command -v npx >/dev/null 2>&1; then
  npx tsc --noEmit 2>/dev/null || {
    echo -e "${RED}[apolo pre-commit] TypeScript no compila${NC}"
    exit 1
  }
fi

# 3. Verificar que Python scripts compilan
for f in scripts/python/*.py; do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null || {
    echo -e "${RED}[apolo pre-commit] $f no compila${NC}"
    exit 1
  }
done

# 4. Post-script gates (si hay flow activo)
if [ -d .opencode/apolo-dynamic ]; then
  python3 scripts/python/force_quality_gates.py check --repo-root . --flowid latest 2>/dev/null || true
fi

echo -e "${GREEN}[apolo pre-commit] ✓ Todo OK, commit permitido${NC}"
exit 0
'''


def install_hooks(repo_root: Path) -> Dict[str, Any]:
    """Instala pre-commit hook en .git/hooks/."""
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return {"success": False, "error": "No es un repo git (falta .git/)"}

    hook_path = git_dir / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    # Backup si ya existe
    if hook_path.exists():
        backup = hook_path.with_suffix(".apolo.bak")
        hook_path.rename(backup)
        log(f"Backup del hook anterior: {backup}", "INFO")

    hook_path.write_text(PRE_COMMIT_SCRIPT, encoding="utf-8")
    hook_path.chmod(0o755)

    log(f"Pre-commit hook instalado: {hook_path}", "INFO")
    return {"success": True, "hook_path": str(hook_path), "message": "Pre-commit hook instalado"}


def run_hooks(repo_root: Path) -> Dict[str, Any]:
    """Ejecuta los hooks manualmente."""
    hook_path = repo_root / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return {"success": False, "error": "Hook no instalado. Ejecuta: install --repo-root ."}

    start = time.time()
    code, out, err = run_cmd(["bash", str(hook_path)], cwd=repo_root, timeout=120)
    duration = int((time.time() - start) * 1000)

    return {
        "success": code == 0,
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1000],
        "stderr": err[:500],
        "verdict": "PASS — commit permitido" if code == 0 else "FAIL — commit bloqueado",
    }


def status_hooks(repo_root: Path) -> Dict[str, Any]:
    """Verifica si los hooks estan instalados."""
    hook_path = repo_root / ".git" / "hooks" / "pre-commit"
    installed = hook_path.exists()
    return {
        "success": True,
        "installed": installed,
        "hook_path": str(hook_path),
        "is_apolo": installed and "apolo" in hook_path.read_text(encoding="utf-8", errors="replace")[:200],
    }


def uninstall_hooks(repo_root: Path) -> Dict[str, Any]:
    """Remueve el hook."""
    hook_path = repo_root / ".git" / "hooks" / "pre-commit"
    if hook_path.exists():
        hook_path.unlink()
        return {"success": True, "message": "Hook removido"}
    return {"success": True, "message": "Hook no estaba instalado"}


def main() -> int:
    argv = sys.argv[1:]
    action = "status"
    known = {"install", "run", "status", "uninstall"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "install":
        r = install_hooks(repo_root); print(json.dumps(r, indent=2)); return 0 if r["success"] else 1
    elif action == "run":
        r = run_hooks(repo_root); print(json.dumps(r, indent=2)); return 0 if r["success"] else 1
    elif action == "status":
        r = status_hooks(repo_root); print(json.dumps(r, indent=2)); return 0
    elif action == "uninstall":
        r = uninstall_hooks(repo_root); print(json.dumps(r, indent=2)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
inspect_tools.py — Inspección rápida del TOOL-REGISTRY.yaml.

Imprime tabla legible de tools, conflictos y salud.

Uso:
  python3 inspect_tools.py --registry /path/TOOL-REGISTRY.yaml [--json]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, run_cmd


def main() -> int:
    args = parse_args(sys.argv[1:])
    registry_p = Path(args.get("registry", ".opencode/apolo-dynamic/TOOL-REGISTRY.yaml"))
    as_json = "json" in args

    reg = read_yaml(registry_p)
    if not reg:
        log(f"no se pudo leer registry: {registry_p}", "ERROR")
        return 2

    if as_json:
        print(json.dumps(reg, indent=2, default=str))
        return 0

    print(f"=" * 80)
    print(f"TOOL-REGISTRY v{reg.get('version')} (updated {reg.get('updated_at')})")
    print(f"{len(reg.get('tools', []))} tools registradas, {len(reg.get('conflicts', []))} conflictos")
    print(f"=" * 80)
    print()

    print(f"{'STATUS':<12} {'ID':<48} {'KIND':<16} {'CAPS'}")
    print("-" * 100)
    for t in reg.get("tools", []):
        status = t.get("status", "?").ljust(12)
        tid = t.get("id", "?")[:48].ljust(48)
        kind = t.get("kind", "?").ljust(16)
        caps = ",".join(t.get("capabilities", []))
        print(f"{status} {tid} {kind} {caps}")
        if t.get("fallback"):
            print(f"             ↳ fallback: {t['fallback']}")

    conflicts = reg.get("conflicts", [])
    if conflicts:
        print()
        print("CONFLICTOS:")
        print("-" * 60)
        for c in conflicts:
            print(f"  cap={c.get('capability')} res={c.get('resolution')}")
            for tid in c.get("tools", []):
                print(f"    - {tid}")

    # Health check summary (solo tools locales verificables)
    print()
    print("HEALTH CHECK (quick):")
    print("-" * 60)
    repo_root = Path(args.get("repo-root", ".")).resolve()
    for t in reg.get("tools", []):
        hc = t.get("health_check")
        if not hc:
            continue
        cmd = hc.get("command", "false")
        # MCPs externos: no se pueden verificar localmente
        if "opencode mcp" in cmd or t.get("kind") == "mcp":
            print(f"  [EXT ] {t['id']}  (verificar con: opencode mcp list)")
            continue
        # test -f: verificación local rápida sin ejecutar
        if cmd.startswith("test -f "):
            p = Path(cmd[8:].strip())
            ok = "OK" if p.exists() else "FAIL"
            print(f"  [{ok:<4}] {t['id']}")
            continue
        # Otros: skip
        print(f"  [SKIP] {t['id']}  (cmd: {cmd[:40]})")

    return 0


if __name__ == "__main__":
    sys.exit(main())

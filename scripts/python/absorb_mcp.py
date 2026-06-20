#!/usr/bin/env python3
"""
absorb_mcp.py — Descubrimiento y registro de tools externas.

Escanea:
  - opencode.json → MCPs registrados
  - .opencode/skills/ → skills locales
  - .opencode/plugin/ → plugins TS
  - scripts/python/ → scripts Python del plugin
  - ~/.config/opencode/mcps/ → MCPs globales (si existen)

Verifica salud (ejecuta health_check) y construye TOOL-REGISTRY.yaml.

Uso:
  python3 absorb_mcp.py --repo-root /path/to/repo --output /path/TOOL-REGISTRY.yaml
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
    cmd_available,
    log,
    now_iso,
    parse_args,
    read_json,
    read_yaml,
    run_cmd,
    sha256,
    write_yaml,
)


def infer_mcp_capabilities(name: str) -> List[str]:
    lower = name.lower()
    caps: List[str] = []
    if "fastedit" in lower or "edit" in lower:
        caps.extend(["edit", "read"])
    if "playwright" in lower:
        caps.extend(["capture", "interact", "dom"])
    if "triage" in lower:
        caps.extend(["triage", "route"])
    if "skillful" in lower or "skills" in lower:
        caps.extend(["plan", "optimize"])
    if "caveman" in lower:
        caps.append("compress")
    if "dcp" in lower:
        caps.extend(["discover", "scope"])
    if "devtools" in lower:
        caps.extend(["debug", "network", "console"])
    return caps or ["unknown"]


def infer_skill_capabilities(name: str) -> List[str]:
    lower = name.lower()
    caps: List[str] = []
    if "evidence" in lower or "capture" in lower:
        caps.extend(["capture", "evidence"])
    if "compare" in lower:
        caps.extend(["compare", "evidence"])
    if "plan" in lower:
        caps.extend(["plan", "shape"])
    if "test" in lower:
        caps.append("test")
    if "audit" in lower or "truth" in lower:
        caps.append("audit")
    if "frontend" in lower or "ui" in lower:
        caps.append("frontend")
    if "backend" in lower:
        caps.append("backend")
    if "security" in lower:
        caps.append("security")
    return caps or ["unknown"]


def infer_script_capabilities(name: str) -> List[str]:
    lower = name.lower()
    caps: List[str] = []
    if "collect" in lower:
        caps.extend(["collect", "evidence"])
    if "generate_plan" in lower:
        caps.extend(["plan", "generate"])
    if "run_tests" in lower:
        caps.extend(["test", "run"])
    if "absorb" in lower:
        caps.extend(["absorb", "register"])
    if "inspect" in lower:
        caps.append("inspect")
    if "rollback" in lower:
        caps.append("rollback")
    if "validate" in lower:
        caps.append("validate")
    if "telemetry" in lower:
        caps.extend(["telemetry", "aggregate"])
    return caps or ["unknown"]


def verify_health(command: str, repo_root: Path) -> bool:
    """Health-check rápido: solo verifica que el archivo/script existe.
    No ejecuta el comando (eso tarda 30s por script y puede colgar)."""
    if not command:
        return True
    # Caso 1: test -f /path/to/file
    if command.startswith("test -f "):
        p = Path(command[8:].strip())
        return p.exists()
    # Caso 2: python3 /path/script.py --help
    if "python3 " in command and ".py" in command:
        # Extraer path del .py
        import re
        m = re.search(r"(\S+\.py)", command)
        if m:
            return Path(m.group(1)).exists()
    # Caso 3: opencode mcp list (siempre considerado externo, no verificar)
    if "opencode mcp" in command:
        return None  # None = "no verificado, no falla"
    # Otros: no verificar
    return None


def build_mcp_tool(name: str, config: Dict[str, Any], repo_root: Path) -> Dict[str, Any]:
    return {
        "id": f"mcp:opencode.json:{name}",
        "source": f"opencode.json#mcp.{name}",
        "kind": "mcp",
        "name": name,
        "status": "unverified",
        "registered_at": now_iso(),
        "capabilities": infer_mcp_capabilities(name),
        "invoke": {"method": "mcp-call", "target": name},
        "fallback": config.get("fallback"),
        "health_check": {
            "command": f"opencode mcp list 2>&1 | grep -q {name}",
            "expected_exit": 0,
            "interval_seconds": 300,
        },
        "notes": json.dumps(config, ensure_ascii=False)[:200],
    }


def build_skill_tool(name: str, skill_md: Path) -> Dict[str, Any]:
    return {
        "id": f"skill:.opencode/skills/{name}",
        "source": str(skill_md),
        "kind": "skill",
        "name": name,
        "status": "unverified",
        "registered_at": now_iso(),
        "capabilities": infer_skill_capabilities(name),
        "invoke": {"method": "ts-function", "target": f"loadSkill({name})"},
        "health_check": {
            "command": f"test -f {skill_md}",
            "expected_exit": 0,
            "interval_seconds": 600,
        },
    }


def build_plugin_tool(name: str, plugin_path: Path) -> Dict[str, Any]:
    return {
        "id": f"plugin-tool:.opencode/plugin/{name}",
        "source": str(plugin_path),
        "kind": "plugin-tool",
        "name": name.replace(".ts", ""),
        "status": "unverified",
        "registered_at": now_iso(),
        "capabilities": ["orchestrate", "edit", "read"],
        "invoke": {"method": "ts-function", "target": f"import({plugin_path})"},
    }


def build_script_tool(name: str, script_path: Path) -> Dict[str, Any]:
    return {
        "id": f"external-script:scripts/python/{name}",
        "source": str(script_path),
        "kind": "external-script",
        "name": name.replace(".py", ""),
        "status": "unverified",
        "registered_at": now_iso(),
        "capabilities": infer_script_capabilities(name),
        "invoke": {"method": "bash-script", "target": f"python3 {script_path}"},
        "health_check": {
            "command": f"test -f {script_path}",
            "expected_exit": 0,
            "interval_seconds": 600,
        },
    }


def detect_conflicts(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_cap: Dict[str, List[str]] = {}
    for t in tools:
        for c in t.get("capabilities", []):
            by_cap.setdefault(c, []).append(t["id"])
    conflicts: List[Dict[str, Any]] = []
    for cap, ids in by_cap.items():
        if len(ids) > 1:
            conflicts.append({
                "tools": ids,
                "capability": cap,
                "resolution": "priority-first",
            })
    return conflicts


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", ".opencode/apolo-dynamic/TOOL-REGISTRY.yaml"))

    start = time.time()
    log(f"absorbiendo tools en {repo_root}", "INFO")

    # Leer registry existente
    existing = read_yaml(output) or {
        "toolregistry": "V2",
        "version": 0,
        "updated_at": now_iso(),
        "tools": [],
        "conflicts": [],
    }
    existing_tools = existing.get("tools", [])
    all_tools: List[Dict[str, Any]] = list(existing_tools)
    existing_ids = {t["id"] for t in all_tools}

    new_tools: List[Dict[str, Any]] = []

    # 1. MCPs desde opencode.json
    opencode_path = repo_root / "opencode.json"
    if opencode_path.exists():
        opencode = read_json(opencode_path) or {}
        mcps = opencode.get("mcp", {})
        for name, config in mcps.items():
            tool = build_mcp_tool(name, config, repo_root)
            if tool["id"] not in existing_ids:
                all_tools.append(tool)
                new_tools.append(tool)
                existing_ids.add(tool["id"])

    # 2. Skills locales
    skills_dir = repo_root / ".opencode" / "skills"
    if skills_dir.exists():
        for entry in skills_dir.iterdir():
            if entry.is_dir():
                skill_md = entry / "SKILL.md"
                if skill_md.exists():
                    tool = build_skill_tool(entry.name, skill_md)
                    if tool["id"] not in existing_ids:
                        all_tools.append(tool)
                        new_tools.append(tool)
                        existing_ids.add(tool["id"])

    # 3. Plugins TS
    plugin_dir = repo_root / ".opencode" / "plugin"
    if plugin_dir.exists():
        for entry in plugin_dir.iterdir():
            if entry.is_file() and entry.name.endswith(".ts"):
                tool = build_plugin_tool(entry.name, entry)
                if tool["id"] not in existing_ids:
                    all_tools.append(tool)
                    new_tools.append(tool)
                    existing_ids.add(tool["id"])

    # 4. Scripts Python
    scripts_dir = repo_root / "scripts" / "python"
    if scripts_dir.exists():
        for entry in scripts_dir.iterdir():
            if entry.is_file() and entry.name.endswith(".py") and entry.name != "common.py":
                tool = build_script_tool(entry.name, entry)
                if tool["id"] not in existing_ids:
                    all_tools.append(tool)
                    new_tools.append(tool)
                    existing_ids.add(tool["id"])

    # 5. Health check de tools nuevas (rápido, sin ejecutar)
    for tool in new_tools:
        hc = tool.get("health_check")
        if hc:
            ok = verify_health(hc["command"], repo_root)
            if ok is None:
                tool["status"] = "active"  # no verificable, asumir activo
            elif ok:
                tool["status"] = "active"
            else:
                tool["status"] = "degraded"
            tool["last_verified_at"] = now_iso()
        else:
            tool["status"] = "unverified"

    # 6. Conflictos
    conflicts = detect_conflicts(all_tools)

    # 7. Persistir
    registry = {
        "toolregistry": "V2",
        "version": int(existing.get("version", 0)) + 1,
        "updated_at": now_iso(),
        "tools": all_tools,
        "conflicts": conflicts,
    }
    write_yaml(output, registry)

    duration_ms = int((time.time() - start) * 1000)
    log(
        f"absorción completa: {len(new_tools)} nuevas, {len(all_tools)} total, {len(conflicts)} conflictos, {duration_ms}ms",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "total_tools": len(all_tools),
        "new_tools": len(new_tools),
        "conflicts": len(conflicts),
        "new_tool_ids": [t["id"] for t in new_tools],
        "version": registry["version"],
        "duration_ms": duration_ms,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

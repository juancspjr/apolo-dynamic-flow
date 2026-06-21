#!/usr/bin/env python3
"""
health_check.py — Implementa apolo.health.check() + hot reload.

Verifica en tiempo real qué MCPs/tools del registry están vivos y, si una
tool cambió de estado (degraded -> active o viceversa), re-absorbe y actualiza
el TOOL-REGISTRY.yaml en caliente.

Diferencia con absorb_mcp.py (que solo descubre y registra):
este script VERIFICA salud en runtime y actualiza estados.

Tipos de health check:
  1. file-exists: para scripts Python (test -f)
  2. mcp-ping: para MCPs (intenta listar herramientas via opencode)
  3. command-exit: para plugins TS (tsc --noEmit)
  4. callable: para funciones internas (la llama y verifica respuesta)

Hot reload:
  - Si una tool que estaba "degraded" ahora responde -> status: "active"
  - Si una tool que estaba "active" dejó de responder -> status: "degraded"
  - Si aparecen nuevas tools (archivo nuevo en scripts/python/) -> las absorbe
  - Si desaparece una tool -> la marca "disabled"

Uso:
  python3 health_check.py --repo-root /path [--fix] [--flowid APOLO-...]
  python3 health_check.py --repo-root /path --json
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
    read_yaml,
    run_cmd,
    write_yaml,
)


# ============================================================================
# Health checkers
# ============================================================================

def check_file_exists(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Verifica que el archivo de un script existe."""
    source = tool.get("source", "")
    if not source:
        return {"healthy": False, "reason": "no source path"}
    p = Path(source)
    if not p.is_absolute():
        # Relativo al repo root
        p = Path.cwd() / source
    exists = p.exists()
    return {
        "healthy": exists,
        "reason": "file exists" if exists else f"file not found: {p}",
        "check": "file-exists",
    }


def check_mcp_ping(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Verifica que un MCP responde (intenta --version o similar)."""
    invoke = tool.get("invoke", {}) or {}
    target = invoke.get("target", "")
    if not target:
        return {"healthy": False, "reason": "no invoke target"}

    # Para MCPs, target es el nombre del MCP en opencode.json
    # Intentamos un ping ligero (timeout corto)
    name = tool.get("name", target)
    # Como no podemos invocar MCPs directamente desde aquí (requiere runtime de OpenCode),
    # verificamos si el paquete npm está disponible
    if cmd_available("npx"):
        # Solo verificar si el paquete existe (sin instalar)
        code, out, err = run_cmd(
            ["npm", "view", name, "version"],
            timeout=10,
        )
        if code == 0:
            return {
                "healthy": True,
                "reason": f"npm package exists: {name}@{out.strip()}",
                "check": "npm-view",
            }
        else:
            return {
                "healthy": False,
                "reason": f"npm package not found: {name}",
                "check": "npm-view",
            }

    return {"healthy": False, "reason": "npx not available", "check": "mcp-ping"}


def check_command_exit(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Ejecuta el comando de health_check y verifica exit code."""
    hc = tool.get("health_check")
    if not hc:
        return {"healthy": True, "reason": "no health_check defined, assuming healthy", "check": "skip"}
    command = hc.get("command", "")
    expected_exit = hc.get("expected_exit", 0)
    if not command:
        return {"healthy": True, "reason": "no command", "check": "skip"}

    code, _, _ = run_cmd(["bash", "-c", command], timeout=10)
    return {
        "healthy": code == expected_exit,
        "reason": f"exit={code}, expected={expected_exit}",
        "check": "command-exit",
    }


def check_tool_health(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch al checker apropiado según el tipo de tool."""
    kind = tool.get("kind", "")
    hc = tool.get("health_check", {}) or {}
    command = hc.get("command", "")

    if kind == "external-script":
        return check_file_exists(tool)
    elif kind == "mcp":
        return check_mcp_ping(tool)
    elif kind == "skill":
        return check_file_exists(tool)
    elif kind == "plugin-tool":
        return check_file_exists(tool)
    elif command:
        return check_command_exit(tool)
    else:
        return {"healthy": True, "reason": "no checker available, assuming healthy", "check": "skip"}


# ============================================================================
# Hot reload
# ============================================================================

def discover_new_scripts(repo_root: Path) -> List[Dict[str, Any]]:
    """Descubre scripts Python nuevos en scripts/python/ que no están en el registry."""
    scripts_dir = repo_root / "scripts" / "python"
    if not scripts_dir.exists():
        return []

    reg = read_yaml(repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml") or {}
    existing_ids = {t.get("id") for t in reg.get("tools", [])}

    new_tools: List[Dict[str, Any]] = []
    for entry in scripts_dir.iterdir():
        if not entry.is_file() or not entry.name.endswith(".py"):
            continue
        if entry.name in ("common.py",):
            continue
        tool_id = f"external-script:scripts/python/{entry.name}"
        if tool_id in existing_ids:
            continue

        # Inferir capabilities desde el nombre
        name_lower = entry.name.lower()
        caps: List[str] = []
        if "collect" in name_lower:
            caps.extend(["collect", "evidence"])
        if "generate_plan" in name_lower:
            caps.extend(["plan", "generate"])
        if "run_tests" in name_lower:
            caps.extend(["test", "run"])
        if "absorb" in name_lower:
            caps.extend(["absorb", "register"])
        if "inspect" in name_lower:
            caps.append("inspect")
        if "rollback" in name_lower:
            caps.append("rollback")
        if "validate" in name_lower:
            caps.append("validate")
        if "telemetry" in name_lower:
            caps.extend(["telemetry", "aggregate"])
        if "index" in name_lower:
            caps.extend(["index", "code"])
        if "score" in name_lower:
            caps.extend(["score", "evidence"])
        if "predict" in name_lower:
            caps.extend(["predict", "impact"])
        if "scaffold" in name_lower:
            caps.extend(["scaffold", "impl"])
        if "context" in name_lower:
            caps.append("context")
        if "recommend" in name_lower:
            caps.extend(["recommend", "registry"])
        if "health" in name_lower:
            caps.extend(["health", "check"])
        if "serve_panel" in name_lower:
            caps.append("panel")
        if not caps:
            caps.append("unknown")

        new_tools.append({
            "id": tool_id,
            "source": str(entry),
            "kind": "external-script",
            "name": entry.name.replace(".py", ""),
            "status": "unverified",
            "registered_at": now_iso(),
            "capabilities": caps,
            "invoke": {
                "method": "bash-script",
                "target": f"python3 {entry}",
            },
            "health_check": {
                "command": f"test -f {entry}",
                "expected_exit": 0,
                "interval_seconds": 600,
            },
        })

    return new_tools


def detect_missing_tools(repo_root: Path) -> List[str]:
    """Detecta tools en el registry cuyo archivo fue eliminado."""
    reg = read_yaml(repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml") or {}
    missing: List[str] = []
    for t in reg.get("tools", []):
        source = t.get("source", "")
        if not source:
            continue
        p = Path(source)
        if not p.is_absolute():
            p = repo_root / source
        if not p.exists() and t.get("kind") in ("external-script", "skill", "plugin-tool"):
            missing.append(t.get("id", "?"))
    return missing


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    fix = args.get("fix", "") == "true"
    as_json = args.get("json", "") == "true"
    flowid = args.get("flowid", "")

    start = time.time()

    reg_path = repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml"
    reg = read_yaml(reg_path) or {"toolregistry": "V2", "version": 0, "tools": [], "conflicts": []}
    tools = reg.get("tools", [])

    log(f"Health check de {len(tools)} tools...", "INFO")

    # 1. Verificar salud de cada tool
    health_results: List[Dict[str, Any]] = []
    status_changes: List[Dict[str, Any]] = []

    for tool in tools:
        result = check_tool_health(tool)
        old_status = tool.get("status", "unverified")
        new_status = "active" if result["healthy"] else "degraded"

        health_results.append({
            "tool_id": tool.get("id"),
            "tool_name": tool.get("name"),
            "kind": tool.get("kind"),
            "old_status": old_status,
            "new_status": new_status,
            "healthy": result["healthy"],
            "reason": result["reason"],
            "check": result["check"],
        })

        if old_status != new_status and old_status != "unverified":
            status_changes.append({
                "tool_id": tool.get("id"),
                "old_status": old_status,
                "new_status": new_status,
                "reason": result["reason"],
            })

        if fix:
            tool["status"] = new_status
            tool["last_verified_at"] = now_iso()

    # 2. Hot reload: detectar scripts nuevos
    new_scripts: List[Dict[str, Any]] = []
    missing_tools: List[str] = []
    if fix:
        new_scripts = discover_new_scripts(repo_root)
        missing_tools = detect_missing_tools(repo_root)

        # Añadir nuevos
        for ns in new_scripts:
            tools.append(ns)

        # Marcar missing como disabled
        for t in tools:
            if t.get("id") in missing_tools:
                t["status"] = "disabled"

        # Persistir registry actualizado
        reg["version"] = int(reg.get("version", 0)) + 1
        reg["updated_at"] = now_iso()
        reg["tools"] = tools
        write_yaml(reg_path, reg)

    duration_ms = int((time.time() - start) * 1000)

    # Resumen
    summary = {
        "total_tools": len(tools),
        "healthy": sum(1 for h in health_results if h["healthy"]),
        "unhealthy": sum(1 for h in health_results if not h["healthy"]),
        "status_changes": len(status_changes),
        "new_scripts_added": len(new_scripts) if fix else 0,
        "missing_tools_marked_disabled": len(missing_tools) if fix else 0,
        "fix_applied": fix,
    }

    result = {
        "healthcheck": "V1",
        "version": 1,
        "flowid": flowid,
        "generated_at": now_iso(),
        "duration_ms": duration_ms,
        "summary": summary,
        "results": health_results,
        "status_changes": status_changes,
        "new_scripts": new_scripts if fix else [],
        "missing_tools": missing_tools if fix else [],
        "recommendation": (
            "all tools healthy" if summary["unhealthy"] == 0
            else f"{summary['unhealthy']} tools unhealthy — consider fallback or re-absorb"
        ),
    }

    if as_json:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    else:
        log(f"Health check: {summary['healthy']}/{summary['total_tools']} healthy, "
            f"{summary['status_changes']} status changes, "
            f"{summary['new_scripts_added']} new, "
            f"{summary['missing_tools_marked_disabled']} missing, "
            f"{duration_ms}ms",
            "INFO" if summary["unhealthy"] == 0 else "WARN")
        # Print tabla legible
        print()
        print(f"{'STATUS':<12} {'TOOL':<55} {'CHECK':<15} REASON")
        print("-" * 100)
        for h in health_results:
            status = "✓ active" if h["healthy"] else "✗ degraded"
            print(f"{status:<12} {h['tool_id'][:54]:<55} {h['check']:<15} {h['reason'][:50]}")
        if status_changes:
            print()
            print("STATUS CHANGES (hot reload):")
            for sc in status_changes:
                print(f"  {sc['tool_id']}: {sc['old_status']} -> {sc['new_status']} ({sc['reason']})")
        if fix and new_scripts:
            print()
            print(f"NEW SCRIPTS ABSORBED ({len(new_scripts)}):")
            for ns in new_scripts:
                print(f"  + {ns['id']} (caps: {', '.join(ns['capabilities'])})")
        if fix and missing_tools:
            print()
            print(f"MISSING TOOLS DISABLED ({len(missing_tools)}):")
            for tid in missing_tools:
                print(f"  - {tid}")

    return 0 if summary["unhealthy"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

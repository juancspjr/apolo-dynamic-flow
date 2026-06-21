#!/usr/bin/env python3
"""
registry_recommend.py — Implementa apolo.registry.recommend(task).

Dado una tarea, recomienda qué tool del registry usar con scoring.

Diferencia con mcp-loader.suggestMcpForTask (que solo mira MCPs):
este script considera TODAS las tools (MCPs + skills + plugins + scripts Python)
y las ordena por score con reasoning explícito.

Scoring:
  +10 si capability matchea palabra clave en la tarea
  +5 si es tool nativa (más confiable que MCP externo)
  +3 si tiene fallback definido
  -5 si está marcada como degraded
  -10 si está disabled

Uso:
  python3 registry_recommend.py \\
    --task "editar archivo TS y correr tests" \\
    --repo-root /path \\
    [--flowid APOLO-...] \\
    [--top 3]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    log,
    now_iso,
    parse_args,
    read_yaml,
)


# ============================================================================
# Capability -> keyword mapping
# ============================================================================

CAPABILITY_KEYWORDS: Dict[str, List[str]] = {
    "edit": ["editar", "edit", "modificar", "cambiar", "write", "escribir", "actualizar"],
    "read": ["leer", "read", "ver", "consultar", "inspeccion", "inspect"],
    "capture": ["capturar", "capture", "screenshot", "pantalla", "browser", "navegador"],
    "interact": ["interactuar", "interact", "click", "clic", "type", "teclear"],
    "dom": ["dom", "html", "css", "selector", "query"],
    "plan": ["plan", "planning", "estrategia", "strategy", "shaping"],
    "generate": ["generar", "generate", "crear", "create", "producir"],
    "test": ["test", "tests", "prueba", "pruebas", "validar", "validate", "tdd"],
    "run": ["correr", "run", "ejecutar", "execute", " lanzar"],
    "validate": ["validar", "validate", "verificar", "verify", "check", "revisar"],
    "rollback": ["rollback", "revertir", "deshacer", "undo"],
    "absorb": ["absorber", "absorb", "registrar", "register", "discover", "descubrir"],
    "inspect": ["inspeccion", "inspect", "ver", "mostrar", "show", "listar"],
    "telemetry": ["telemetría", "telemetria", "telemetry", "stats", "métricas", "metricas"],
    "aggregate": ["agregar", "aggregate", "consolidar", "sumarizar"],
    "debug": ["debug", "console", "network", "performance", "profil"],
    "discover": ["descubrir", "discover", "explorar", "explore", "mapear", "map"],
    "scope": ["scope", "alcance", "reducir", "reducción"],
    "optimize": ["optimizar", "optimize", "mejorar", "improve"],
    "compress": ["comprimir", "compress", "reducir tokens"],
    "triage": ["triage", "clasificar", "priorizar"],
    "route": ["rutar", "route", "dirigir", "dirigirse"],
    "evidence": ["evidencia", "evidence", "capturar evidencia"],
    "collect": ["recolectar", "collect", "capturar data"],
    "frontend": ["frontend", "ui", "interfaz", "componente", "react", "vue"],
    "backend": ["backend", "api", "endpoint", "server", "servidor"],
    "security": ["security", "seguridad", "audit", "auditar", "vulnerabilidad"],
    "unknown": [],
}


def score_tool(tool: Dict[str, Any], task_lower: str) -> Dict[str, Any]:
    """Calcula score de una tool para una tarea."""
    score = 0
    reasons: List[str] = []

    # Capability matching
    caps = tool.get("capabilities", []) or []
    matched_caps: List[str] = []
    for cap in caps:
        keywords = CAPABILITY_KEYWORDS.get(cap, [])
        for kw in keywords:
            if kw in task_lower:
                score += 10
                matched_caps.append(cap)
                reasons.append(f"capability '{cap}' matches keyword '{kw}'")
                break

    # Name-based matching (algunas tools no tienen capabilities bien inferidas)
    tool_name = (tool.get("name") or "").lower()
    tool_id = (tool.get("id") or "").lower()
    name_keywords = {
        "edit": ["editar", "edit", "modificar", "cambiar", "write", "escribir"],
        "test": ["test", "tests", "prueba", "pruebas", "validar", "validate"],
        "plan": ["plan", "planning", "estrategia"],
        "evidence": ["evidencia", "evidence", "capturar"],
        "index": ["index", "índice", "indice", "code"],
        "score": ["score", "calidad"],
        "predict": ["predict", "predicción", "prediccion", "impact"],
        "scaffold": ["scaffold", "andamio"],
        "context": ["context", "contexto", "consulta"],
        "recommend": ["recommend", "recomend", "sugerir"],
        "health": ["health", "salud"],
        "collect": ["collect", "recolectar"],
        "validate": ["validate", "validar", "verificar"],
        "rollback": ["rollback", "revertir", "deshacer"],
        "absorb": ["absorb", "absorber", "registrar"],
        "inspect": ["inspect", "inspeccion", "ver", "mostrar"],
        "telemetry": ["telemetry", "telemetría", "telemetria", "stats"],
    }
    for cap_name, kws in name_keywords.items():
        # Si el nombre o id de la tool contiene el cap_name
        if cap_name in tool_name or cap_name in tool_id:
            for kw in kws:
                if kw in task_lower:
                    if cap_name not in matched_caps:
                        score += 8
                        matched_caps.append(cap_name)
                        reasons.append(f"tool name matches '{cap_name}' (keyword '{kw}')")
                    break

    # Bonus por ser tool nativa (script Python del propio plugin)
    if tool.get("kind") == "external-script":
        score += 5
        reasons.append("native script (more reliable than external MCP)")

    # Bonus por tener fallback
    if tool.get("fallback"):
        score += 3
        reasons.append(f"has fallback: {tool['fallback']}")

    # Penalty por estar degraded
    if tool.get("status") == "degraded":
        score -= 5
        reasons.append("status 'degraded' (-5)")

    # Penalty por estar disabled
    if tool.get("status") == "disabled":
        score -= 10
        reasons.append("status 'disabled' (-10)")

    return {
        "tool_id": tool.get("id"),
        "tool_name": tool.get("name"),
        "tool_kind": tool.get("kind"),
        "score": max(score, 0),
        "matched_capabilities": matched_caps,
        "reasons": reasons,
        "status": tool.get("status"),
        "fallback": tool.get("fallback"),
        "invoke": tool.get("invoke"),
    }


def recommend(
    task: str,
    repo_root: Path,
    top: int = 3,
) -> Dict[str, Any]:
    """Recomienda top N tools para una tarea."""
    # Buscar registry en múltiples ubicaciones
    candidates = [
        repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml",
        repo_root / "TOOL-REGISTRY.yaml",
        Path.cwd() / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml",
    ]
    reg_path = next((p for p in candidates if p.exists()), candidates[0])
    reg = read_yaml(reg_path) or {}
    tools = reg.get("tools", [])

    task_lower = task.lower()
    scored: List[Dict[str, Any]] = []
    for t in tools:
        s = score_tool(t, task_lower)
        # Aceptar tools activas o no verificadas (unverified = asumir activas)
        if s["score"] > 0 and s["status"] in ("active", "unverified"):
            scored.append(s)

    # Ordenar por score descendente
    scored.sort(key=lambda x: -x["score"])
    top_tools = scored[:top]

    # Identificar conflicts (tools con misma capability principal)
    conflicts: List[Dict[str, Any]] = []
    cap_to_tools: Dict[str, List[str]] = {}
    for s in top_tools:
        for cap in s["matched_capabilities"]:
            cap_to_tools.setdefault(cap, []).append(s["tool_id"])
    for cap, tids in cap_to_tools.items():
        if len(tids) > 1:
            conflicts.append({
                "capability": cap,
                "tools": tids,
                "resolution": "priority-first (first registered wins) — consider explicit choice",
            })

    return {
        "task": task,
        "total_tools_evaluated": len(tools),
        "tools_with_score": len(scored),
        "top_recommendations": top_tools,
        "conflicts": conflicts,
        "recommended_action": (
            f"use {top_tools[0]['tool_id']} (score={top_tools[0]['score']})"
            if top_tools
            else "no tool matches the task — consider adding a new MCP"
        ),
    }


def main() -> int:
    args = parse_args(sys.argv[1:])
    task = args.get("task", "")
    repo_root = Path(args.get("repo-root", ".")).resolve()
    top = int(args.get("top", "3"))
    flowid = args.get("flowid", "")

    if not task:
        log("--task requerido", "ERROR")
        return 2

    start = time.time()
    result = recommend(task, repo_root, top)
    result["_meta"] = {
        "duration_ms": int((time.time() - start) * 1000),
        "flowid": flowid,
        "answered_at": now_iso(),
    }

    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
context_query.py — Implementa apolo.context.query(phase, question).

Convierte al sistema de pasivo (el agente lee YAMLs) a activo (el sistema
responde consultas del agente usando telemetría + flow state).

Responde preguntas del agente como:
  - "¿qué fase sigue?" -> lee FLOW-STATE.yaml y devuelve siguiente fase
  - "¿qué bloqueos activos hay?" -> lee BLOCK-LOG.yaml
  - "¿qué eventos recientes?" -> lee telemetry.jsonl
  - "¿qué tools disponibles?" -> lee TOOL-REGISTRY.yaml
  - "¿qué evidence tengo?" -> lee EVIDENCE-PACK.yaml + EVIDENCE-SCORE.yaml
  - "¿qué código toca este MP?" -> lee CODE-INDEX.yaml + DYNAMIC-PLAN.yaml
  - "¿qué predicciones de impacto hay?" -> lee IMPACT-PREDICTION.yaml
  - "¿qué andamio sigo?" -> lee IMPL-SCAFFOLD-*.yaml

Uso:
  python3 context_query.py \\
    --flowid APOLO-20260620-MI \\
    --repo-root /path \\
    --phase implementation \\
    --question "qué archivos debo tocar para U-01?"
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    log,
    now_iso,
    parse_args,
    read_yaml,
    write_yaml,
)


# ============================================================================
# Question patterns
# ============================================================================

# Cada pattern es (regex, handler_name)
QUESTION_PATTERNS = [
    (r"(qué|que).*(fase|phase).*(sigue|siguiente|next|viene|proxima|próxima)", "next_phase"),
    (r"(qué|que).*(bloqueo|block)", "active_blocks"),
    (r"(qué|que).*(eventos|events).*(reciente|recent)", "recent_events"),
    (r"(qué|que).*(tools|herramientas).*(disponible|available)", "available_tools"),
    (r"(qué|que).*(evidence|evidencia)", "evidence_summary"),
    (r"(qué|que).*(score|calidad).*(evidence|evidencia)", "evidence_score"),
    (r"(qué|que).*(código|code|archivos).*(tocar|touch|modificar|modify).*(U-\d+)", "files_for_unit"),
    (r"(qué|que).*(predic|impact|impacto)", "impact_prediction"),
    (r"(qué|que).*(andamio|scaffold|checkpoint)", "scaffold_summary"),
    (r"(qué|que).*(code.?index|índice|indice).*(código|code)", "code_index_summary"),
    (r"(qué|que).*(plan|plan dinámico|plan dinamico)", "plan_summary"),
    (r"(cuál|cual).*(estado|state)", "flow_state"),
    (r"(qué|que).*(falta|missing|pendiente)", "missing_artifacts"),
    (r"(qué|que).*(MCP)", "available_mcps"),
    (r"(cuál|cual).*(MCP).*(recomend|sugier)", "recommended_mcp"),
    (r"(qué|que).*(health|salud).*(MCP|tool)", "health_check"),
    (r"resumen|summary|status", "full_summary"),
]


def match_question(question: str) -> str:
    """Identifica qué handler usar para la pregunta."""
    q_lower = question.lower()
    for pattern, handler in QUESTION_PATTERNS:
        if re.search(pattern, q_lower):
            return handler
    return "unknown"


# ============================================================================
# Handlers
# ============================================================================

def flow_dir(repo_root: Path, flowid: str) -> Path:
    return repo_root / "plan" / "active" / flowid


def handler_next_phase(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee FLOW-STATE.yaml y devuelve la siguiente fase esperada."""
    state = read_yaml(flow_dir(repo_root, flowid) / "FLOW-STATE.yaml") or {}
    current = state.get("phase", phase or "?")
    transitions = {
        "reanclaje": "planning-bootstrap",
        "planning-bootstrap": "asr",
        "asr": "verdad",
        "verdad": "shaping",
        "shaping": "plan-indice",
        "plan-indice": "mp-validation",
        "mp-validation": "implementation",
        "implementation": "critical-validation",
        "critical-validation": "cierre-flow",
        "cierre-flow": None,
    }
    next_phase = transitions.get(current)
    loops = state.get("loops", {}).get(current, {}) or {}
    return {
        "current_phase": current,
        "next_phase": next_phase,
        "loop_counter": f"{loops.get('current', 0)}/{loops.get('max', '?')}",
        "version": state.get("version"),
    }


def handler_active_blocks(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee BLOCK-LOG.yaml y devuelve bloqueos activos."""
    blocks_data = read_yaml(flow_dir(repo_root, flowid) / "BLOCK-LOG.yaml") or {}
    blocks = blocks_data.get("blocks", [])
    active = [b for b in blocks if b.get("status") == "active"]
    return {
        "active_blocks_count": len(active),
        "blocks": [
            {
                "id": b.get("id"),
                "kind": b.get("kind"),
                "severity": b.get("severity"),
                "description": b.get("description"),
                "suggested_resolution": b.get("suggested_resolution"),
            }
            for b in active
        ],
    }


def handler_recent_events(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee telemetry.jsonl y devuelve últimos 10 eventos."""
    tel_path = flow_dir(repo_root, flowid) / "telemetry.jsonl"
    if not tel_path.exists():
        return {"events": [], "note": "no telemetry file"}
    events: List[Dict[str, Any]] = []
    for line in tel_path.read_text(encoding="utf-8").splitlines()[-10:]:
        if line.strip():
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return {
        "recent_events_count": len(events),
        "events": [
            {
                "at": e.get("at"),
                "kind": e.get("kind"),
                "phase": e.get("phase"),
                "severity": e.get("severity"),
                "message": e.get("message"),
            }
            for e in events
        ],
    }


def handler_available_tools(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee TOOL-REGISTRY.yaml y devuelve tools activas."""
    reg = read_yaml(repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml") or {}
    tools = reg.get("tools", [])
    active = [t for t in tools if t.get("status") == "active"]
    return {
        "total_tools": len(tools),
        "active_tools": len(active),
        "tools": [
            {
                "id": t.get("id"),
                "kind": t.get("kind"),
                "capabilities": t.get("capabilities"),
                "fallback": t.get("fallback"),
            }
            for t in active
        ],
    }


def handler_evidence_summary(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee EVIDENCE-PACK.yaml y devuelve resumen."""
    pack = read_yaml(flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml") or {}
    return {
        "items_count": len(pack.get("items", [])),
        "hash_chain": pack.get("hash_chain"),
        "capabilities": pack.get("capabilities"),
        "degradation_count": len(pack.get("degradation_log", [])),
        "captured_at": pack.get("created_at"),
        "items_by_kind": _group_by_kind(pack.get("items", [])),
    }


def _group_by_kind(items: List[Dict[str, Any]]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for item in items:
        kind = item.get("kind", "unknown")
        result[kind] = result.get(kind, 0) + 1
    return result


def handler_evidence_score(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee EVIDENCE-SCORE.yaml y devuelve scores."""
    score = read_yaml(flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-SCORE.yaml") or {}
    return {
        "overall_score": score.get("overall_score"),
        "scores": score.get("scores"),
        "recommendation": score.get("recommendation"),
        "missing_critical": score.get("details", {}).get("missing_critical", []),
    }


def handler_files_for_unit(repo_root: Path, flowid: str, phase: str, question: str = "") -> Dict[str, Any]:
    """Lee DYNAMIC-PLAN.yaml + CODE-INDEX.yaml y devuelve archivos para una unidad."""
    plan = read_yaml(flow_dir(repo_root, flowid) / "03-PLAN-INDICE-DYNAMIC.yaml") or {}
    code_index = read_yaml(
        repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
    ) or {}

    # Extraer unit_id de la pregunta
    m = re.search(r"U-(\d+)", question)
    unit_id = f"U-{m.group(1)}" if m else ""

    unidades = plan.get("unidades", [])
    unidad = next((u for u in unidades if u.get("id") == unit_id), None)
    if not unidad:
        return {"error": f"unidad {unit_id} no encontrada en plan"}

    acopl = unidad.get("acoplamientosreales", {}) or {}
    files = acopl.get("archivos", []) or []
    symbols = acopl.get("simbolos", []) or []

    # Enriquecer con info del CODE-INDEX
    files_index = {f["path"]: f for f in code_index.get("files", [])}
    enriched_files = []
    for f in files:
        fi = files_index.get(f, {})
        enriched_files.append({
            "path": f,
            "in_index": bool(fi),
            "summary": fi.get("summary"),
            "exported_functions": [
                fn["name"] for fn in fi.get("symbols", {}).get("functions", [])
                if fn.get("is_exported")
            ][:5],
        })

    return {
        "unit_id": unit_id,
        "files": enriched_files,
        "symbols": symbols,
        "riesgo_operativo": unidad.get("riesgooperativo"),
        "criterio_homogeneidad": unidad.get("criteriohomogeneidad"),
    }


def handler_impact_prediction(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee IMPACT-PREDICTION.yaml y devuelve resumen."""
    pred = read_yaml(flow_dir(repo_root, flowid) / "IMPACT-PREDICTION.yaml") or {}
    return {
        "global_risk": pred.get("global_risk"),
        "risk_distribution": pred.get("risk_distribution"),
        "total_predictions": pred.get("total_predictions"),
        "high_risk_mps": [
            {
                "mp_id": p.get("mp_id"),
                "overall_risk": p.get("overall_risk"),
                "recommendation": p.get("recommendation"),
            }
            for p in pred.get("predictions", [])
            if p.get("overall_risk") in ("high", "critical")
        ],
    }


def handler_scaffold_summary(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee IMPL-SCAFFOLD-*.yaml y devuelve resumen."""
    flow_d = flow_dir(repo_root, flowid)
    scaffolds = list(flow_d.glob("IMPL-SCAFFOLD-*.yaml"))
    if not scaffolds:
        return {"scaffolds": [], "note": "no scaffolds generated yet"}
    result = []
    for sf in scaffolds:
        data = read_yaml(sf) or {}
        result.append({
            "unit_id": data.get("unit_id"),
            "verdict": data.get("verdict"),
            "total_files": data.get("summary", {}).get("total_files"),
            "total_checkpoints": data.get("summary", {}).get("total_checkpoints"),
            "has_circular_deps": data.get("summary", {}).get("has_circular_deps"),
        })
    return {"scaffolds": result}


def handler_code_index_summary(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee CODE-INDEX.yaml y devuelve resumen."""
    ci = read_yaml(repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml") or {}
    return {
        "total_files": ci.get("stats", {}).get("total_files"),
        "by_language": ci.get("stats", {}).get("by_language"),
        "total_functions": ci.get("stats", {}).get("total_functions"),
        "total_classes": ci.get("stats", {}).get("total_classes"),
        "index_hash": ci.get("index_hash"),
        "generated_at": ci.get("generated_at"),
    }


def handler_plan_summary(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee DYNAMIC-PLAN.yaml y devuelve resumen."""
    plan = read_yaml(flow_dir(repo_root, flowid) / "03-PLAN-INDICE-DYNAMIC.yaml") or {}
    unidades = plan.get("unidades", [])
    return {
        "version": plan.get("version"),
        "estado": plan.get("estado"),
        "total_unidades": len(unidades),
        "unidades_admisibles": sum(1 for u in unidades if u.get("admisibleaindice")),
        "topological_order": [
            t.get("unit_id") for t in plan.get("topological_sort", [])
        ],
        "unidades": [
            {
                "id": u.get("id"),
                "resumen": u.get("resumen"),
                "tipocambio": u.get("tipocambio"),
                "riesgooperativo": u.get("riesgooperativo"),
                "mpestimados": u.get("mpestimados"),
                "admisible": u.get("admisibleaindice"),
            }
            for u in unidades
        ],
    }


def handler_flow_state(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lee FLOW-STATE.yaml y devuelve estado completo."""
    state = read_yaml(flow_dir(repo_root, flowid) / "FLOW-STATE.yaml") or {}
    return {
        "flowid": state.get("flowid"),
        "phase": state.get("phase"),
        "version": state.get("version"),
        "tokens_consumed_total": state.get("tokens_consumed_total"),
        "tools_absorbed_count": len(state.get("tools_absorbed", [])),
        "loops": state.get("loops"),
        "circuit_breaker": state.get("circuit_breaker"),
        "artifacts": state.get("artifacts"),
    }


def handler_missing_artifacts(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Verifica qué artefactos faltan para avanzar."""
    state = read_yaml(flow_dir(repo_root, flowid) / "FLOW-STATE.yaml") or {}
    current_phase = state.get("phase", phase or "?")
    required_per_phase = {
        "reanclaje": [],
        "planning-bootstrap": ["objetivo"],
        "asr": ["asr"],
        "verdad": ["verdad", "evidence_pack"],
        "shaping": ["shaping"],
        "plan-indice": ["plan_indice"],
        "mp-validation": ["plan_indice"],
        "implementation": ["current_mps"],
        "critical-validation": ["test_runs"],
        "cierre-flow": [],
    }
    required = required_per_phase.get(current_phase, [])
    artifacts = state.get("artifacts", {}) or {}
    missing = []
    for req in required:
        val = artifacts.get(req)
        if not val or (isinstance(val, list) and len(val) == 0):
            missing.append(req)
    return {
        "current_phase": current_phase,
        "required_artifacts": required,
        "missing": missing,
        "ready_to_advance": len(missing) == 0,
    }


def handler_available_mcps(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Lista MCPs disponibles del TOOL-REGISTRY."""
    reg = read_yaml(repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml") or {}
    mcps = [t for t in reg.get("tools", []) if t.get("kind") == "mcp"]
    return {
        "total_mcps": len(mcps),
        "active_mcps": sum(1 for m in mcps if m.get("status") == "active"),
        "mcps": [
            {
                "id": m.get("id"),
                "name": m.get("name"),
                "status": m.get("status"),
                "capabilities": m.get("capabilities"),
                "fallback": m.get("fallback"),
            }
            for m in mcps
        ],
    }


def handler_recommended_mcp(repo_root: Path, flowid: str, phase: str, question: str = "") -> Dict[str, Any]:
    """Recomienda qué MCP usar para una tarea."""
    reg = read_yaml(repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml") or {}
    tools = [t for t in reg.get("tools", []) if t.get("kind") == "mcp" and t.get("status") == "active"]

    q_lower = question.lower()
    recommendations: List[Dict[str, Any]] = []

    for t in tools:
        caps = t.get("capabilities", []) or []
        score = 0
        reasons: List[str] = []
        if "edit" in caps and any(k in q_lower for k in ("editar", "edit", "modificar", "cambiar")):
            score += 10
            reasons.append("capability 'edit' matches editing task")
        if "capture" in caps and any(k in q_lower for k in ("captur", "screenshot", "browser", "ui")):
            score += 10
            reasons.append("capability 'capture' matches visual task")
        if "dom" in caps and any(k in q_lower for k in ("dom", "html", "click", "interact")):
            score += 8
            reasons.append("capability 'dom' matches interaction task")
        if "plan" in caps and any(k in q_lower for k in ("plan", "optimize", "estrategia")):
            score += 8
            reasons.append("capability 'plan' matches planning task")
        if "discover" in caps and any(k in q_lower for k in ("descubrir", "discover", "explorar", "explore")):
            score += 8
            reasons.append("capability 'discover' matches exploration task")
        if "test" in caps and any(k in q_lower for k in ("test", "prueba", "validar")):
            score += 7
            reasons.append("capability 'test' matches testing task")
        if "debug" in caps and any(k in q_lower for k in ("debug", "console", "network")):
            score += 7
            reasons.append("capability 'debug' matches debugging task")
        if score > 0:
            recommendations.append({
                "mcp": t.get("name"),
                "id": t.get("id"),
                "score": score,
                "reasons": reasons,
                "fallback": t.get("fallback"),
            })

    recommendations.sort(key=lambda r: -r["score"])
    return {
        "question": question,
        "top_recommendation": recommendations[0] if recommendations else None,
        "all_recommendations": recommendations[:3],
    }


def handler_health_check(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Health check rápido de tools del registry."""
    from inspect_tools import inspect_tools_cli
    # Reusar inspect_tools.py
    result = inspect_tools_cli(repo_root)
    return result


def handler_full_summary(repo_root: Path, flowid: str, phase: str) -> Dict[str, Any]:
    """Resumen completo del estado del flow."""
    return {
        "flow_state": handler_flow_state(repo_root, flowid, phase),
        "missing_artifacts": handler_missing_artifacts(repo_root, flowid, phase),
        "active_blocks": handler_active_blocks(repo_root, flowid, phase),
        "recent_events": handler_recent_events(repo_root, flowid, phase),
        "available_tools": handler_available_tools(repo_root, flowid, phase),
        "evidence_summary": handler_evidence_summary(repo_root, flowid, phase),
        "evidence_score": handler_evidence_score(repo_root, flowid, phase),
        "plan_summary": handler_plan_summary(repo_root, flowid, phase),
        "code_index_summary": handler_code_index_summary(repo_root, flowid, phase),
        "impact_prediction": handler_impact_prediction(repo_root, flowid, phase),
    }


def handler_unknown(repo_root: Path, flowid: str, phase: str, question: str = "") -> Dict[str, Any]:
    """Handler para preguntas no reconocidas."""
    return {
        "error": "question_not_recognized",
        "question": question,
        "suggested_questions": [
            "qué fase sigue",
            "qué bloqueos activos hay",
            "qué eventos recientes",
            "qué tools disponibles",
            "qué evidence tengo",
            "qué score tiene la evidencia",
            "qué código debo tocar para U-XX",
            "qué predicciones de impacto hay",
            "qué andamio sigo",
            "qué falta para avanzar",
            "cuál MCP recomendado para [tarea]",
            "resumen completo",
        ],
    }


# ============================================================================
# Dispatcher
# ============================================================================

HANDLERS = {
    "next_phase": handler_next_phase,
    "active_blocks": handler_active_blocks,
    "recent_events": handler_recent_events,
    "available_tools": handler_available_tools,
    "evidence_summary": handler_evidence_summary,
    "evidence_score": handler_evidence_score,
    "files_for_unit": handler_files_for_unit,
    "impact_prediction": handler_impact_prediction,
    "scaffold_summary": handler_scaffold_summary,
    "code_index_summary": handler_code_index_summary,
    "plan_summary": handler_plan_summary,
    "flow_state": handler_flow_state,
    "missing_artifacts": handler_missing_artifacts,
    "available_mcps": handler_available_mcps,
    "recommended_mcp": handler_recommended_mcp,
    "health_check": handler_health_check,
    "full_summary": handler_full_summary,
    "unknown": handler_unknown,
}


def answer(repo_root: Path, flowid: str, phase: str, question: str) -> Dict[str, Any]:
    """Punto de entrada principal: dada una pregunta, devuelve respuesta."""
    handler_name = match_question(question)
    handler = HANDLERS.get(handler_name, handler_unknown)
    start = time.time()

    try:
        # Algunos handlers reciben question extra
        if handler_name in ("files_for_unit", "recommended_mcp", "unknown"):
            result = handler(repo_root, flowid, phase, question)
        else:
            result = handler(repo_root, flowid, phase)
        result["_meta"] = {
            "handler": handler_name,
            "duration_ms": int((time.time() - start) * 1000),
            "flowid": flowid,
            "phase": phase,
            "question": question,
            "answered_at": now_iso(),
        }
        return result
    except Exception as e:
        return {
            "error": str(e),
            "_meta": {
                "handler": handler_name,
                "duration_ms": int((time.time() - start) * 1000),
                "flowid": flowid,
                "phase": phase,
                "question": question,
            },
        }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    flowid = args.get("flowid", "")
    repo_root = Path(args.get("repo-root", ".")).resolve()
    phase = args.get("phase", "")
    question = args.get("question", "")

    if not flowid or not question:
        log("--flowid y --question requeridos", "ERROR")
        return 2

    result = answer(repo_root, flowid, phase, question)

    # Output: JSON a stdout para que el agente lo consuma
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
agent_escape_hatch.py — Salidas guiadas cuando el sistema puede dañar (v3.5.1).

RESPONDE a tu indicacion: "seria bueno indicaciones no digo que el agente se
libere o que haga trampas para liberarse solo que hay que buscar una salida
cuando el sistema puede dañar las soluciones"

Cuando el agente esta atasco en un loop de fallos, el sistema debe ofrecer
SALIDAS GUIADAS (no escapar sin control, sino caminos alternativos seguros):

  1. SKIP_WITH_JUSTIFICATION: saltar una fase con justificacion documentada
  2. ALTERNATIVE_PATH: proponer un camino alternativo (ej: manual en vez de auto)
  3. DEGRADE_GRACEFUL: degradar funcionalidad en vez de fallar
  4. REQUEST_HUMAN_HELP: escalar a humano con contexto completo
  5. ROLLBACK_AND_RETRY: revertir y reintentar con estrategia diferente

Cada escape hatch:
  - Requiere justificacion (no se puede escapar sin razon)
  - Queda registrado en telemetry (auditable)
  - El agente debe aprender de por que necesito escapar
  - Si se usa el mismo escape hatch 3+ veces, se bloquea (no es trampa)

CLI:
  python3 agent_escape_hatch.py offer --flowid X --phase plan --reason "score < threshold 3 veces"
  python3 agent_escape_hatch.py use --flowid X --hatch-id H-001 --justification "..."
  python3 agent_escape_hatch.py history --flowid X
"""

from __future__ import annotations
import json, os, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir, telemetry_path


ESCAPE_HATCH_TYPES = {
    "skip_with_justification": {
        "description": "Saltar una fase con justificacion documentada",
        "risk_level": "medium",
        "requires_justification": True,
        "max_uses_per_flow": 2,
    },
    "alternative_path": {
        "description": "Proponer un camino alternativo (manual vs auto)",
        "risk_level": "low",
        "requires_justification": True,
        "max_uses_per_flow": 3,
    },
    "degrade_graceful": {
        "description": "Degradar funcionalidad en vez de fallar",
        "risk_level": "low",
        "requires_justification": True,
        "max_uses_per_flow": 5,
    },
    "request_human_help": {
        "description": "Escalar a humano con contexto completo",
        "risk_level": "none",
        "requires_justification": False,
        "max_uses_per_flow": 10,
    },
    "rollback_and_retry": {
        "description": "Revertir y reintentar con estrategia diferente",
        "risk_level": "medium",
        "requires_justification": True,
        "max_uses_per_flow": 2,
    },
}


def escape_hatch_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "ESCAPE-HATCHES.jsonl"


def offer_escape_hatches(repo_root: Path, flowid: str, phase: str, reason: str) -> Dict[str, Any]:
    """Ofrece escape hatches disponibles para una situacion de atasco."""
    hatches = []
    for hatch_type, config in ESCAPE_HATCH_TYPES.items():
        hatches.append({
            "hatch_id": f"H-{uuid.uuid4().hex[:8]}",
            "type": hatch_type,
            "description": config["description"],
            "risk_level": config["risk_level"],
            "requires_justification": config["requires_justification"],
            "max_uses": config["max_uses_per_flow"],
        })

    # Log offer
    log_entry = {
        "at": now_iso(),
        "flowid": flowid,
        "phase": phase,
        "reason": reason,
        "action": "escape_hatch_offered",
        "hatches_offered": len(hatches),
    }
    _append_log(repo_root, flowid, log_entry)

    return {
        "success": True,
        "flowid": flowid,
        "phase": phase,
        "reason": reason,
        "hatches_available": hatches,
        "message": "Escape hatches disponibles — el agente puede usar uno con justificacion",
        "warning": "Cada escape hatch requiere justificacion y queda registrado en telemetry",
    }


def use_escape_hatch(repo_root: Path, flowid: str, hatch_id: str, hatch_type: str, justification: str, context: str = "") -> Dict[str, Any]:
    """El agente usa un escape hatch."""
    if hatch_type not in ESCAPE_HATCH_TYPES:
        return {"success": False, "error": f"Tipo de escape hatch invalido: {hatch_type}"}

    config = ESCAPE_HATCH_TYPES[hatch_type]

    if config["requires_justification"] and not justification.strip():
        return {"success": False, "error": "Este escape hatch requiere justificacion (no se puede usar sin razon)"}

    # Verificar limite de uses
    history = _get_history(repo_root, flowid)
    uses_of_type = sum(1 for h in history if h.get("type") == hatch_type)
    if uses_of_type >= config["max_uses_per_flow"]:
        return {
            "success": False,
            "error": f"Limite de uses alcanzado para {hatch_type} ({uses_of_type}/{config['max_uses_per_flow']})",
            "hint": "Si necesitas escapar mas veces, considera request_human_help",
        }

    # Registrar uso
    log_entry = {
        "at": now_iso(),
        "flowid": flowid,
        "hatch_id": hatch_id,
        "type": hatch_type,
        "justification": justification,
        "context": context,
        "action": "escape_hatch_used",
        "risk_level": config["risk_level"],
        "use_number": uses_of_type + 1,
    }
    _append_log(repo_root, flowid, log_entry)

    # Also log to telemetry
    tel_path = telemetry_path(repo_root, flowid)
    tel_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tel_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": now_iso(),
            "flowid": flowid,
            "kind": "escape-hatch-used",
            "phase": "unknown",
            "severity": "warn",
            "message": f"Escape hatch used: {hatch_type} — {justification[:100]}",
            "payload": log_entry,
        }) + "\n")

    # Determinar accion recomendada
    actions = {
        "skip_with_justification": f"Saltar fase actual. Justificacion: {justification}. Continuar con siguiente fase.",
        "alternative_path": f"Probar camino alternativo: {context or 'usar method=manual'}. Justificacion: {justification}",
        "degrade_graceful": f"Degradar: {context or 'omitir analisis opcional'}. Justificacion: {justification}",
        "request_human_help": f"ESCALAR A HUMANO. Contexto: {context}. Razón: {justification}",
        "rollback_and_retry": f"Revertir cambios y reintentar con estrategia diferente. Justificacion: {justification}",
    }

    return {
        "success": True,
        "hatch_id": hatch_id,
        "type": hatch_type,
        "justification": justification,
        "action_recommended": actions.get(hatch_type, "Continuar"),
        "use_number": uses_of_type + 1,
        "uses_remaining": config["max_uses_per_flow"] - uses_of_type - 1,
        "logged_to_telemetry": True,
        "message": f"Escape hatch '{hatch_type}' usado. Accion: {actions.get(hatch_type, '')}",
    }


def _append_log(repo_root: Path, flowid: str, entry: Dict) -> None:
    p = escape_hatch_path(repo_root, flowid)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _get_history(repo_root: Path, flowid: str) -> List[Dict]:
    p = escape_hatch_path(repo_root, flowid)
    if not p.exists():
        return []
    history = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            history.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return history


def get_history(repo_root: Path, flowid: str) -> Dict[str, Any]:
    history = _get_history(repo_root, flowid)
    used = [h for h in history if h.get("action") == "escape_hatch_used"]

    # Stats por tipo
    by_type: Dict[str, int] = {}
    for h in used:
        t = h.get("type", "")
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "success": True,
        "flowid": flowid,
        "total_offered": sum(1 for h in history if h.get("action") == "escape_hatch_offered"),
        "total_used": len(used),
        "by_type": by_type,
        "history": used[-10:],  # ultimos 10
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "offer"
    known = {"offer", "use", "history"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "offer":
        phase = args.get("phase", "")
        reason = args.get("reason", "")
        if not phase or not reason:
            print(json.dumps({"success": False, "error": "Falta --phase y --reason"}, indent=2)); return 2
        r = offer_escape_hatches(repo_root, flowid, phase, reason)
        print(json.dumps(r, ensure_ascii=False, indent=2)); return 0
    elif action == "use":
        hatch_id = args.get("hatch-id", "")
        hatch_type = args.get("type", args.get("hatch-type", ""))
        justification = args.get("justification", "")
        context = args.get("context", "")
        if not hatch_type:
            print(json.dumps({"success": False, "error": "Falta --type (skip_with_justification|alternative_path|degrade_graceful|request_human_help|rollback_and_retry)"}, indent=2)); return 2
        r = use_escape_hatch(repo_root, flowid, hatch_id, hatch_type, justification, context)
        print(json.dumps(r, ensure_ascii=False, indent=2)); return 0 if r["success"] else 1
    elif action == "history":
        r = get_history(repo_root, flowid)
        print(json.dumps(r, ensure_ascii=False, indent=2)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

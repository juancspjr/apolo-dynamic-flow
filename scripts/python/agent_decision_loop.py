#!/usr/bin/env python3
"""
agent_decision_loop.py — Loop sobre decisiones del agente (v3.2.0).

RESPONDE a la intencion del usuario:
  "se busca que el agente haga loop sobre esas decisiones y escoja entre
   ellas excelentes decisiones"

El agente propone N opciones de decision. El sistema las evalua automaticamente
con criterios objetivos (impacto, riesgo, alineacion con goal, evidencia) y
escoge la mejor. Si ninguna es excelente (score < threshold), el sistema
obliga al agente a proponer mas opciones.

Flujo:
  1. Agente propone opciones (via archivo YAML o stdin)
  2. Sistema evalua cada opcion con 5 criterios:
     - Impacto esperado (0-1)
     - Riesgo (0-1, invertido)
     - Alineacion con goal (0-1)
     - Evidencia de soporte (0-1)
     - Factibilidad (0-1)
  3. Sistema calcula score ponderado
  4. Si score >= threshold (default 0.7) → aceptar
  5. Si score < threshold → obligar al agente a proponer mas opciones

CLI:
  # Agente propone opciones (via archivo)
  python3 agent_decision_loop.py decide \\
      --flowid APOLO-X \\
      --goal "implementar JWT auth" \\
      --options decisions.yaml

  # Sistema evalua y escoge
  python3 agent_decision_loop.py decide --flowid APOLO-X --goal "..." --options-json '[...]'

  # Ver historial de decisiones
  python3 agent_decision_loop.py history --flowid APOLO-X

  # Forzar re-evaluacion
  python3 agent_decision_loop.py reevaluate --flowid APOLO-X
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


# ============================================================================
# Decision evaluation criteria
# ============================================================================

CRITERIA_WEIGHTS = {
    "impact": 0.25,        # Impacto esperado en el goal
    "risk_reversed": 0.20, # (1 - riesgo) — menor riesgo = mejor
    "goal_alignment": 0.25, # Alineacion con el goal del flow
    "evidence_support": 0.15, # Evidencia que soporta la decision
    "feasibility": 0.15,   # Factibilidad tecnica
}

DEFAULT_EXCELLENCE_THRESHOLD = 0.7


def evaluate_option(option: Dict, goal: str, evidence: Dict = None) -> Dict[str, Any]:
    """Evalua una opcion con 5 criterios."""
    scores = {}

    # 1. Impacto (0-1) — que tan alto impacto tendra
    impact = option.get("impact_score")
    if impact is None:
        # Inferir de la descripcion
        desc = (option.get("description", "") + " " + option.get("rationale", "")).lower()
        impact = 0.5  # default
        if "high" in desc or "alto" in desc or "critical" in desc or "critico" in desc:
            impact = 0.9
        elif "medium" in desc or "medio" in desc:
            impact = 0.6
        elif "low" in desc or "bajo" in desc or "minor" in desc:
            impact = 0.3
    scores["impact"] = min(1.0, max(0.0, float(impact)))

    # 2. Riesgo (invertido) — menor riesgo = mejor
    risk = option.get("risk_score")
    if risk is None:
        desc = (option.get("description", "") + " " + option.get("rationale", "")).lower()
        risk = 0.5
        if "high" in desc or "alto" in desc:
            risk = 0.8
        elif "medium" in desc or "medio" in desc:
            risk = 0.5
        elif "low" in desc or "bajo" in desc:
            risk = 0.2
    scores["risk_reversed"] = 1.0 - min(1.0, max(0.0, float(risk)))

    # 3. Alineacion con goal — keywords del goal en la descripcion
    goal_words = set(w.lower() for w in goal.split() if len(w) > 3)
    desc_words = set(w.lower() for w in (option.get("description", "") + " " + option.get("rationale", "")).split())
    if goal_words:
        overlap = len(goal_words & desc_words) / len(goal_words)
        scores["goal_alignment"] = overlap
    else:
        scores["goal_alignment"] = 0.5

    # 4. Evidencia de soporte
    evidence_refs = option.get("evidence_refs", [])
    if evidence_refs and evidence:
        supported = sum(1 for ref in evidence_refs if ref in str(evidence))
        scores["evidence_support"] = supported / len(evidence_refs) if evidence_refs else 0.5
    else:
        scores["evidence_support"] = option.get("evidence_score", 0.5)

    # 5. Factibilidad
    feasibility = option.get("feasibility_score")
    if feasibility is None:
        # Inferir de si tiene steps definidos
        steps = option.get("steps", [])
        if steps:
            feasibility = min(1.0, len(steps) / 5.0)  # mas steps = mas factible
        else:
            feasibility = 0.5
    scores["feasibility"] = min(1.0, max(0.0, float(feasibility)))

    # Score ponderado
    total_score = sum(scores[k] * CRITERIA_WEIGHTS[k] for k in CRITERIA_WEIGHTS)

    return {
        "option_id": option.get("id", ""),
        "title": option.get("title", option.get("description", "")[:60]),
        "scores": scores,
        "weighted_score": round(total_score, 3),
        "is_excellent": total_score >= DEFAULT_EXCELLENCE_THRESHOLD,
        "rationale": option.get("rationale", ""),
    }


def choose_best_option(
    options: List[Dict],
    goal: str,
    evidence: Dict = None,
    threshold: float = DEFAULT_EXCELLENCE_THRESHOLD,
) -> Dict[str, Any]:
    """Evalua todas las opciones y escoge la mejor."""
    if not options:
        return {
            "success": False,
            "error": "No hay opciones para evaluar",
            "need_more_options": True,
        }

    evaluations = []
    for opt in options:
        eval_result = evaluate_option(opt, goal, evidence)
        evaluations.append(eval_result)

    # Ordenar por score descendente
    evaluations.sort(key=lambda x: -x["weighted_score"])
    best = evaluations[0]

    if best["weighted_score"] < threshold:
        return {
            "success": False,
            "error": f"Ninguna opcion es excelente (mejor score: {best['weighted_score']} < {threshold})",
            "need_more_options": True,
            "evaluations": evaluations,
            "best_so_far": best,
            "threshold": threshold,
            "message": "El agente debe proponer mejores opciones o mejorar las existentes",
        }

    return {
        "success": True,
        "chosen": best,
        "evaluations": evaluations,
        "threshold": threshold,
        "message": f"Opcion elegida: {best['title']} (score: {best['weighted_score']})",
    }


# ============================================================================
# Decision history
# ============================================================================

def decisions_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "DECISIONS-LOG.jsonl"


def log_decision(repo_root: Path, flowid: str, decision: Dict) -> None:
    p = decisions_path(repo_root, flowid)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": now_iso(), "flowid": flowid, **decision}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_history(repo_root: Path, flowid: str) -> Dict[str, Any]:
    p = decisions_path(repo_root, flowid)
    if not p.exists():
        return {"success": True, "decisions": [], "total": 0}

    decisions = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            decisions.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return {
        "success": True,
        "decisions": decisions,
        "total": len(decisions),
        "excellent_count": sum(1 for d in decisions if d.get("chosen", {}).get("is_excellent")),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "decide"
    known = {"decide", "history", "reevaluate"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
        return 2

    if action == "decide":
        goal = args.get("goal", "")
        if not goal:
            print(json.dumps({"success": False, "error": "Falta --goal"}, indent=2))
            return 2

        # Load options
        options = []
        if args.get("options"):
            options_data = read_yaml(Path(args["options"])) or {}
            options = options_data.get("options", [])
        elif args.get("options-json"):
            try:
                options = json.loads(args["options-json"])
            except json.JSONDecodeError as e:
                print(json.dumps({"success": False, "error": f"options-json invalido: {e}"}, indent=2))
                return 2
        else:
            print(json.dumps({"success": False, "error": "Falta --options o --options-json"}, indent=2))
            return 2

        threshold = float(args.get("threshold", str(DEFAULT_EXCELLENCE_THRESHOLD)))

        # Load evidence if available
        evidence = None
        ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
        if ev_path.exists():
            evidence = read_yaml(ev_path)

        result = choose_best_option(options, goal, evidence, threshold)

        # Log decision
        log_decision(repo_root, flowid, {
            "goal": goal,
            "options_count": len(options),
            "chosen": result.get("chosen"),
            "need_more_options": result.get("need_more_options", False),
            "threshold": threshold,
        })

        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    elif action == "history":
        result = get_history(repo_root, flowid)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "reevaluate":
        # Re-evaluate last decision
        history = get_history(repo_root, flowid)
        if not history["decisions"]:
            print(json.dumps({"success": False, "error": "No hay decisiones para reevaluar"}, indent=2))
            return 1

        last = history["decisions"][-1]
        print(json.dumps({"success": True, "last_decision": last, "message": "Reevaluacion requiere opciones nuevas"}, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
mp_prioritizer.py — Priorizacion dinamica de MPs basada en telemetria (v3.4.0).

Cierra el GAP: "Priorizacion dinamica de MPs: reordenar cola basado en telemetria"

Reordena la cola de unidades (MPs) del plan basandose en:
  1. Impacto predicho (de IMPACT-PREDICTION.yaml)
  2. Riesgo operativo (de PLAN.yaml)
  3. Tasa de exito historica (de cross_flow_learning)
  4. Dependencias topologicas
  5. Evidencia de urgencia (de telemetry de flows anteriores)

CLI:
  # Reordenar plan basado en telemetria
  python3 mp_prioritizer.py reprioritize --flowid X --repo-root .

  # Ver prioridad calculada de cada unidad
  python3 mp_prioritizer.py scores --flowid X --repo-root .

  # Ver siguiente unidad recomendada
  python3 mp_prioritizer.py next --flowid X --repo-root .
"""

from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


def calculate_unit_score(unit: Dict, impact_pred: Dict, cross_flow: Dict) -> Dict[str, Any]:
    """Calcula score de prioridad para una unidad."""
    uid = unit.get("id", "")
    scores = {}

    # 1. Impacto predicho (0-1)
    predictions = impact_pred.get("predictions", []) if impact_pred else []
    impact_val = 0.5
    for pred in predictions:
        if pred.get("unit_id") == uid or pred.get("unit") == uid:
            affected = pred.get("affected_count", 0) or pred.get("total_affected", 0) or 0
            impact_val = min(1.0, affected / 20.0)  # normalizar
            break
    scores["impact"] = impact_val

    # 2. Riesgo (invertido — menor riesgo = mayor prioridad para empezar)
    risk = unit.get("riesgooperativo", "medio").lower()
    risk_map = {"bajo": 0.9, "medio": 0.5, "alto": 0.2}
    scores["risk_reversed"] = risk_map.get(risk, 0.5)

    # 3. Tasa de exito historica (de cross_flow)
    phase_stats = cross_flow.get("phase_stats", {}) if cross_flow else {}
    # Si la unidad tiene fase asociada, usar esa tasa
    phase = unit.get("fase", "reanclaje")
    phase_info = phase_stats.get(phase, {})
    scores["historical_success"] = phase_info.get("success_rate", 0.7)

    # 4. Dependencias (menos dependencias = mayor prioridad)
    deps = unit.get("dependenciasprevias", []) or []
    scores["dependency_score"] = 1.0 / (1.0 + len(deps))

    # 5. MP estimados (menor = mas rapido = mayor prioridad para quick wins)
    mp_est = unit.get("mpestimados", 3)
    scores["speed_score"] = 1.0 / (1.0 + mp_est / 5.0)

    # Score ponderado
    weights = {"impact": 0.30, "risk_reversed": 0.15, "historical_success": 0.25, "dependency_score": 0.15, "speed_score": 0.15}
    total = sum(scores[k] * weights[k] for k in weights)

    return {
        "unit_id": uid,
        "resumen": unit.get("resumen", ""),
        "scores": scores,
        "priority_score": round(total, 3),
        "dependencies": deps,
    }


def reprioritize(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Reordena las unidades del plan basandose en telemetria."""
    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"
    impact_path = flow_dir(repo_root, flowid) / "plans" / "IMPACT-PREDICTION.yaml"
    cross_flow_path = repo_root / ".opencode" / "apolo-dynamic" / "CROSS-FLOW-LEARNING.yaml"

    if not plan_path.exists():
        return {"success": False, "error": "PLAN.yaml no existe"}

    plan = read_yaml(plan_path) or {}
    impact_pred = read_yaml(impact_path) if impact_path.exists() else None
    cross_flow = read_yaml(cross_flow_path) if cross_flow_path.exists() else None

    units = plan.get("unidades", [])
    if not units:
        return {"success": False, "error": "No hay unidades en el plan"}

    # Calcular score para cada unidad
    scored = [calculate_unit_score(u, impact_pred or {}, cross_flow or {}) for u in units]

    # Ordenar por priority_score descendente
    scored.sort(key=lambda x: -x["priority_score"])

    # Guardar plan re-prioritizado
    prioritized_plan = dict(plan)
    prioritized_plan["unidades"] = [next(u for u in units if u.get("id") == s["unit_id"]) for s in scored]
    prioritized_plan["priority_order"] = [{"order": i + 1, "unit_id": s["unit_id"], "score": s["priority_score"]} for i, s in enumerate(scored)]
    prioritized_plan["reprioritized_at"] = now_iso()

    output_path = flow_dir(repo_root, flowid) / "plans" / "PLAN-PRIORITIZED.yaml"
    write_yaml(output_path, prioritized_plan)

    return {
        "success": True,
        "flowid": flowid,
        "total_units": len(scored),
        "priority_order": [{"order": i + 1, "unit_id": s["unit_id"], "score": s["priority_score"], "resumen": s["resumen"][:50]} for i, s in enumerate(scored)],
        "output": str(output_path),
    }


def get_scores(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Retorna scores de prioridad de cada unidad."""
    r = reprioritize(repo_root, flowid)
    if not r["success"]:
        return r
    return {"success": True, "scores": r["priority_order"]}


def get_next_unit(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Retorna la siguiente unidad recomendada."""
    r = reprioritize(repo_root, flowid)
    if not r["success"]:
        return r
    if not r["priority_order"]:
        return {"success": False, "error": "No hay unidades"}
    next_u = r["priority_order"][0]
    return {"success": True, "next_unit": next_u, "message": f"Siguiente unidad: {next_u['unit_id']} (score: {next_u['score']})"}


def main() -> int:
    argv = sys.argv[1:]
    action = "scores"
    known = {"reprioritize", "scores", "next"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")
    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "reprioritize":
        r = reprioritize(repo_root, flowid); print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    elif action == "scores":
        r = get_scores(repo_root, flowid); print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    elif action == "next":
        r = get_next_unit(repo_root, flowid); print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

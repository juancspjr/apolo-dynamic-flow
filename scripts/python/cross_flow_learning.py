#!/usr/bin/env python3
"""
cross_flow_learning.py — Cross-flow learning: usar evidencia de flows anteriores (v3.1.0).

Cierra el GAP #6 del INTEGRATION-VERDICT.md:
  "Cross-flow learning: usar evidencia de flows anteriores para mejorar nuevos"

Analiza la telemetria y evidencia de flows anteriores para extraer
aprendizajes que mejoren flows nuevos:

  1. Patrones de exito: que combinaciones de (phase, tool, strategy) llevan
     a flows exitosos
  2. Patrones de fallo: que combinaciones llevan a bloqueos
  3. Recommendations contextuales: dado un flow nuevo en fase X, recomendar
     acciones basadas en flows similares anteriores
  4. Routing adjustments: si cierto tool fallo N veces en fase X, ajustar
     routing para evitarlo

Storage: .opencode/apolo-dynamic/CROSS-FLOW-LEARNING.yaml (consolidado)

CLI:
  # Analizar todos los flows y construir base de conocimiento
  python3 cross_flow_learning.py analyze --repo-root . --output knowledge.yaml

  # Recomendar para un flow nuevo
  python3 cross_flow_learning.py recommend --repo-root . --flowid APOLO-X --phase verdad

  # Buscar flows similares
  python3 cross_flow_learning.py similar --repo-root . --flowid APOLO-X

  # Stats de aprendizaje
  python3 cross_flow_learning.py stats --repo-root .
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir, telemetry_path


KNOWLEDGE_FILE = "CROSS-FLOW-LEARNING.yaml"


def knowledge_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / KNOWLEDGE_FILE


def load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def parse_timestamp(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts[:-1] + "+00:00")
        return datetime.fromisoformat(ts)
    except ValueError:
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


# ============================================================================
# Flow analysis
# ============================================================================

def analyze_flow(flow_dir_path: Path, flowid: str) -> Dict[str, Any]:
    """Analiza un flow individual y extrae metricas + patrones."""
    tel_path = telemetry_path(flow_dir_path.parent.parent.parent, flowid)
    # Actually telemetry_path needs repo_root, let me reconstruct
    # flow_dir_path is plan/active/<flowid>, repo_root is 3 levels up
    repo_root = flow_dir_path.parent.parent.parent
    tel_path = repo_root / "plan" / "active" / flowid / "telemetry.jsonl"

    events = load_jsonl(tel_path)
    if not events:
        return {
            "flowid": flowid,
            "analyzed": False,
            "reason": "no telemetry",
        }

    # Metricas basicas
    total_events = len(events)
    error_count = sum(1 for e in events if e.get("severity") == "error")
    warning_count = sum(1 for e in events if e.get("severity") == "warn")
    tool_invocations = [e for e in events if e.get("kind") == "tool-invoked"]
    tool_failures = [e for e in events if "fail" in e.get("kind", "").lower()]
    phase_transitions = [e for e in events if "phase-enter" in e.get("kind", "")]

    # Phases visitadas
    phases_visited = list(set(e.get("phase", "") for e in events if e.get("phase")))

    # Tools usados
    tools_used = list(set(e.get("tool", "") for e in tool_invocations if e.get("tool")))

    # Duracion
    timestamps = [parse_timestamp(e.get("at", "")) for e in events]
    timestamps = [t for t in timestamps if t]
    duration_s = 0
    if timestamps:
        duration_s = (max(timestamps) - min(timestamps)).total_seconds()

    # Veredicto: exito si no hay errores, fallo si hay
    success = error_count == 0 and len(tool_failures) == 0

    # Patron de fallo si fallo
    failure_pattern = None
    if not success:
        first_error = next((e for e in events if e.get("severity") == "error"), None)
        if first_error:
            failure_pattern = {
                "phase": first_error.get("phase", ""),
                "kind": first_error.get("kind", ""),
                "message": first_error.get("message", "")[:200],
                "tool": first_error.get("tool", ""),
            }

    # Evidence pack si existe
    ev_path = flow_dir_path / "evidence" / "EVIDENCE-PACK.yaml"
    evidence_items = 0
    evidence_scope_paths: List[str] = []
    if ev_path.exists():
        ev_data = read_yaml(ev_path) or {}
        items = ev_data.get("items", []) or []
        evidence_items = len(items)
        for item in items:
            src = item.get("source", "")
            if src:
                evidence_scope_paths.append(src)

    return {
        "flowid": flowid,
        "analyzed": True,
        "success": success,
        "total_events": total_events,
        "error_count": error_count,
        "warning_count": warning_count,
        "tool_invocations": len(tool_invocations),
        "tool_failures": len(tool_failures),
        "phases_visited": phases_visited,
        "tools_used": tools_used,
        "duration_s": round(duration_s, 2),
        "evidence_items": evidence_items,
        "evidence_scope_paths": evidence_scope_paths[:10],  # cap
        "failure_pattern": failure_pattern,
    }


def analyze_all_flows(repo_root: Path) -> Dict[str, Any]:
    """Analiza todos los flows y construye base de conocimiento."""
    flows_dir = repo_root / "plan" / "active"
    if not flows_dir.exists():
        return {
            "success": True,
            "flows_analyzed": 0,
            "message": "no flows directory",
        }

    flows_data: List[Dict] = []
    for flow_d in flows_dir.iterdir():
        if not flow_d.is_dir():
            continue
        flow_data = analyze_flow(flow_d, flow_d.name)
        if flow_data.get("analyzed"):
            flows_data.append(flow_data)

    if not flows_data:
        return {
            "success": True,
            "flows_analyzed": 0,
            "message": "no flows with telemetry",
        }

    # Extraer patrones globales
    successful_flows = [f for f in flows_data if f["success"]]
    failed_flows = [f for f in flows_data if not f["success"]]

    # Patrones de exito: tools mas usados en flows exitosos
    success_tools = Counter()
    for f in successful_flows:
        for t in f["tools_used"]:
            success_tools[t] += 1

    # Patrones de fallo: agrupar por phase + kind
    failure_by_phase = Counter()
    failure_by_kind = Counter()
    failure_by_tool = Counter()
    failure_messages: List[str] = []
    for f in failed_flows:
        fp = f.get("failure_pattern") or {}
        if fp.get("phase"):
            failure_by_phase[fp["phase"]] += 1
        if fp.get("kind"):
            failure_by_kind[fp["kind"]] += 1
        if fp.get("tool"):
            failure_by_tool[fp["tool"]] += 1
        if fp.get("message"):
            failure_messages.append(fp["message"])

    # Phase success rates
    phase_stats: Dict[str, Dict] = defaultdict(lambda: {"success": 0, "failure": 0})
    for f in flows_data:
        for p in f["phases_visited"]:
            if f["success"]:
                phase_stats[p]["success"] += 1
            else:
                phase_stats[p]["failure"] += 1

    # Tool success rates
    tool_stats: Dict[str, Dict] = defaultdict(lambda: {"used_in_success": 0, "used_in_failure": 0})
    for f in flows_data:
        for t in f["tools_used"]:
            if f["success"]:
                tool_stats[t]["used_in_success"] += 1
            else:
                tool_stats[t]["used_in_failure"] += 1

    knowledge = {
        "crossflowlearning": "V1",
        "schema_version": "3.1.0",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "flows_analyzed": len(flows_data),
        "successful_flows": len(successful_flows),
        "failed_flows": len(failed_flows),
        "success_rate": round(len(successful_flows) / max(len(flows_data), 1), 3),
        "patterns": {
            "success_tools": dict(success_tools.most_common(20)),
            "failure_by_phase": dict(failure_by_phase),
            "failure_by_kind": dict(failure_by_kind),
            "failure_by_tool": dict(failure_by_tool),
            "failure_sample_messages": failure_messages[:10],
        },
        "phase_stats": {
            p: {
                "success": v["success"],
                "failure": v["failure"],
                "success_rate": round(v["success"] / max(v["success"] + v["failure"], 1), 3),
            }
            for p, v in phase_stats.items()
        },
        "tool_stats": {
            t: {
                "used_in_success": v["used_in_success"],
                "used_in_failure": v["used_in_failure"],
                "success_rate": round(v["used_in_success"] / max(v["used_in_success"] + v["used_in_failure"], 1), 3),
            }
            for t, v in tool_stats.items()
        },
        "flows": flows_data,
    }

    return knowledge


# ============================================================================
# Recommendations
# ============================================================================

def recommend_for_flow(
    repo_root: Path,
    flowid: str,
    current_phase: str = "",
) -> Dict[str, Any]:
    """Recomienda acciones para un flow basandose en flows anteriores."""
    knowledge = read_yaml(knowledge_path(repo_root)) or {}
    if not knowledge:
        # Si no hay conocimiento, analizar primero
        log("No hay conocimiento previo — analizando flows...", "INFO")
        knowledge = analyze_all_flows(repo_root)
        write_yaml(knowledge_path(repo_root), knowledge)

    recommendations: List[Dict[str, Any]] = []

    # 1. Si estamos en una fase con alta tasa de fallo, recomendar precaucion
    if current_phase:
        phase_stats = knowledge.get("phase_stats", {})
        phase_info = phase_stats.get(current_phase, {})
        if phase_info:
            success_rate = phase_info.get("success_rate", 1.0)
            if success_rate < 0.5:
                recommendations.append({
                    "type": "caution",
                    "priority": "high",
                    "message": f"Fase {current_phase} tiene tasa de exito {success_rate:.0%} — revisar evidencia cuidadosamente",
                    "evidence": f"{phase_info.get('failure', 0)} fallos de {phase_info.get('success', 0) + phase_info.get('failure', 0)} flows",
                })

    # 2. Tools con baja tasa de exito — evitar
    tool_stats = knowledge.get("tool_stats", {})
    for tool, stats in tool_stats.items():
        total = stats.get("used_in_success", 0) + stats.get("used_in_failure", 0)
        if total >= 2:  # solo recomendar si hay data suficiente
            success_rate = stats.get("success_rate", 1.0)
            if success_rate < 0.5:
                recommendations.append({
                    "type": "avoid_tool",
                    "priority": "medium",
                    "message": f"Tool {tool} tiene tasa de exito {success_rate:.0%} — considerar alternativa",
                    "evidence": f"{stats.get('used_in_failure', 0)} fallos de {total} usos",
                })

    # 3. Tools con alta tasa de exito — preferir
    success_tools = knowledge.get("patterns", {}).get("success_tools", {})
    for tool, count in list(success_tools.items())[:5]:
        recommendations.append({
            "type": "prefer_tool",
            "priority": "low",
            "message": f"Tool {tool} usada en {count} flows exitosos",
            "evidence": f"{count} flows exitosos",
        })

    # 4. Patrones de fallo comunes en la fase actual
    if current_phase:
        failure_by_phase = knowledge.get("patterns", {}).get("failure_by_phase", {})
        if failure_by_phase.get(current_phase, 0) > 0:
            # Buscar mensajes de fallo en esta fase
            failure_messages = knowledge.get("patterns", {}).get("failure_sample_messages", [])
            relevant = [m for m in failure_messages if current_phase.lower() in m.lower()]
            if relevant:
                recommendations.append({
                    "type": "watch_for",
                    "priority": "high",
                    "message": f"Fallos comunes en {current_phase}: {relevant[0][:100]}",
                    "evidence": f"{failure_by_phase[current_phase]} fallos registrados",
                })

    return {
        "success": True,
        "flowid": flowid,
        "current_phase": current_phase,
        "based_on_flows": knowledge.get("flows_analyzed", 0),
        "recommendations_count": len(recommendations),
        "recommendations": recommendations,
        "generated_at": now_iso(),
    }


def find_similar_flows(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Encuentra flows similares basandose en phases visitadas y tools usados."""
    knowledge = read_yaml(knowledge_path(repo_root)) or {}
    if not knowledge:
        knowledge = analyze_all_flows(repo_root)
        write_yaml(knowledge_path(repo_root), knowledge)

    # Encontrar el flow actual
    current_flow = None
    for f in knowledge.get("flows", []):
        if f["flowid"] == flowid:
            current_flow = f
            break

    if not current_flow:
        return {"success": False, "error": f"flow {flowid} not found in knowledge base"}

    current_phases = set(current_flow["phases_visited"])
    current_tools = set(current_flow["tools_used"])

    # Calcular similitud con otros flows (Jaccard)
    similar: List[Dict] = []
    for f in knowledge.get("flows", []):
        if f["flowid"] == flowid:
            continue
        other_phases = set(f["phases_visited"])
        other_tools = set(f["tools_used"])

        # Jaccard similarity
        phase_union = current_phases | other_phases
        phase_intersect = current_phases & other_phases
        tool_union = current_tools | other_tools
        tool_intersect = current_tools & other_tools

        phase_sim = len(phase_intersect) / len(phase_union) if phase_union else 0
        tool_sim = len(tool_intersect) / len(tool_union) if tool_union else 0

        # Combined similarity (50/50)
        similarity = (phase_sim + tool_sim) / 2

        if similarity > 0:
            similar.append({
                "flowid": f["flowid"],
                "similarity": round(similarity, 3),
                "phase_similarity": round(phase_sim, 3),
                "tool_similarity": round(tool_sim, 3),
                "was_successful": f["success"],
                "common_phases": list(phase_intersect),
                "common_tools": list(tool_intersect),
            })

    similar.sort(key=lambda x: -x["similarity"])

    return {
        "success": True,
        "flowid": flowid,
        "total_other_flows": len(similar),
        "top_similar": similar[:10],
    }


def get_stats(repo_root: Path) -> Dict[str, Any]:
    """Estadisticas del aprendizaje."""
    knowledge = read_yaml(knowledge_path(repo_root)) or {}
    if not knowledge:
        return {
            "success": True,
            "has_knowledge": False,
            "message": "No hay base de conocimiento — ejecuta: analyze --repo-root .",
        }

    return {
        "success": True,
        "has_knowledge": True,
        "flows_analyzed": knowledge.get("flows_analyzed", 0),
        "successful_flows": knowledge.get("successful_flows", 0),
        "failed_flows": knowledge.get("failed_flows", 0),
        "success_rate": knowledge.get("success_rate", 0),
        "phases_tracked": len(knowledge.get("phase_stats", {})),
        "tools_tracked": len(knowledge.get("tool_stats", {})),
        "knowledge_generated_at": knowledge.get("generated_at", ""),
        "knowledge_path": str(knowledge_path(repo_root)),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "stats"
    known = {"analyze", "recommend", "similar", "stats"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "analyze":
        knowledge = analyze_all_flows(repo_root)
        output = args.get("output")
        if output:
            write_yaml(Path(output), knowledge)
        # Tambien persistir en location estandar
        write_yaml(knowledge_path(repo_root), knowledge)
        log(f"Knowledge base → {knowledge_path(repo_root)}", "INFO")
        print(json.dumps({
            "success": True,
            "flows_analyzed": knowledge.get("flows_analyzed", 0),
            "success_rate": knowledge.get("success_rate", 0),
            "phases_tracked": len(knowledge.get("phase_stats", {})),
            "tools_tracked": len(knowledge.get("tool_stats", {})),
            "output": str(knowledge_path(repo_root)),
        }, indent=2))
        return 0

    elif action == "recommend":
        flowid = args.get("flowid", "")
        phase = args.get("phase", "")
        if not flowid:
            print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
            return 2
        result = recommend_for_flow(repo_root, flowid, phase)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "similar":
        flowid = args.get("flowid", "")
        if not flowid:
            print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
            return 2
        result = find_similar_flows(repo_root, flowid)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "stats":
        result = get_stats(repo_root)
        print(json.dumps(result, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

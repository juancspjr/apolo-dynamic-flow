#!/usr/bin/env python3
"""
evidence_replay.py — Replay de evidencia: reproducir un bug paso a paso (v3.1.0).

Cierra el GAP #5 del INTEGRATION-VERDICT.md:
  "Replay de evidencia (reproducir un bug paso a paso desde el audit log)"

Permite reproducir un bug paso a paso desde el audit log (telemetry.jsonl +
DEBUG-TRACE.jsonl). Construye una linea de tiempo con todos los eventos
que llevaron a un fallo, permitiendo al agente entender exactamente que
paso, cuando, y por que.

CLI:
  # Listar flows con telemetry disponible
  python3 evidence_replay.py flows --repo-root .

  # Construir timeline de un flow
  python3 evidence_replay.py timeline --flowid APOLO-X --output timeline.yaml

  # Filtrar por tipo de evento
  python3 evidence_replay.py timeline --flowid APOLO-X --filter kind=tool-invoked

  # Replay de un bug especifico (busca el primer error en telemetry)
  python3 evidence_replay.py bug --flowid APOLO-X --output BUG-REPLAY.yaml

  # Replay con pasos detallados
  python3 evidence_replay.py bug --flowid APOLO-X --verbose --output BUG-REPLAY.yaml

  # Buscar patrones de fallo en todos los flows
  python3 evidence_replay.py patterns --repo-root .
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


def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parsea timestamp ISO 8601 con o sin Z."""
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


def load_jsonl(path: Path) -> List[Dict]:
    """Carga un archivo JSON Lines."""
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


def build_timeline(
    repo_root: Path,
    flowid: str,
    filter_kind: str = "",
    filter_phase: str = "",
    filter_severity: str = "",
) -> Dict[str, Any]:
    """Construye una linea de tiempo con todos los eventos del flow."""
    # Cargar telemetry
    tel_path = telemetry_path(repo_root, flowid)
    telemetry = load_jsonl(tel_path)

    # Cargar DEBUG-TRACE.jsonl si existe
    trace_path = flow_dir(repo_root, flowid) / "DEBUG-TRACE.jsonl"
    trace = load_jsonl(trace_path)

    # Combinar y ordenar por timestamp
    events = []
    for e in telemetry:
        events.append({
            "source": "telemetry",
            "at": e.get("at", ""),
            "kind": e.get("kind", ""),
            "phase": e.get("phase", ""),
            "severity": e.get("severity", "info"),
            "message": e.get("message", ""),
            "actor": e.get("actor", ""),
            "tool": e.get("tool", ""),
            "unit_id": e.get("unit_id", ""),
            "raw": e,
        })

    for t in trace:
        events.append({
            "source": "trace",
            "at": t.get("at", ""),
            "kind": t.get("kind", ""),
            "phase": t.get("from_phase", "") or t.get("to_phase", "") or t.get("phase", ""),
            "severity": "info",
            "message": t.get("message", ""),
            "actor": t.get("actor", ""),
            "tool": "",
            "unit_id": "",
            "from_phase": t.get("from_phase", ""),
            "to_phase": t.get("to_phase", ""),
            "breakpoint_hit": t.get("breakpoint_hit", False),
            "raw": t,
        })

    # Aplicar filtros
    if filter_kind:
        events = [e for e in events if filter_kind.lower() in e["kind"].lower()]
    if filter_phase:
        events = [e for e in events if filter_phase.lower() in e["phase"].lower()]
    if filter_severity:
        events = [e for e in events if filter_severity.lower() in e["severity"].lower()]

    # Ordenar por timestamp
    def sort_key(e):
        ts = parse_timestamp(e.get("at", ""))
        return ts or datetime.min.replace(tzinfo=timezone.utc)

    events.sort(key=sort_key)

    # Calcular duracion total
    if events:
        first_ts = parse_timestamp(events[0].get("at", ""))
        last_ts = parse_timestamp(events[-1].get("at", ""))
        total_duration_s = 0
        if first_ts and last_ts:
            total_duration_s = (last_ts - first_ts).total_seconds()
    else:
        total_duration_s = 0

    # Stats
    kind_counts = Counter(e["kind"] for e in events if e["kind"])
    phase_counts = Counter(e["phase"] for e in events if e["phase"])
    severity_counts = Counter(e["severity"] for e in events if e["severity"])

    return {
        "replaytimeline": "V1",
        "schema_version": "3.1.0",
        "flowid": flowid,
        "generated_at": now_iso(),
        "total_events": len(events),
        "total_duration_s": round(total_duration_s, 2),
        "first_event_at": events[0]["at"] if events else "",
        "last_event_at": events[-1]["at"] if events else "",
        "stats": {
            "by_kind": dict(kind_counts),
            "by_phase": dict(phase_counts),
            "by_severity": dict(severity_counts),
        },
        "events": events,
    }


def find_bug_replay(
    repo_root: Path,
    flowid: str,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Encuentra el primer error en telemetry y construye un replay del bug."""
    timeline = build_timeline(repo_root, flowid)

    # Buscar el primer evento con severity=error o kind=tool-failed
    error_idx = -1
    for i, e in enumerate(timeline["events"]):
        if e["severity"] == "error" or "fail" in e["kind"].lower() or "error" in e["kind"].lower():
            error_idx = i
            break

    if error_idx < 0:
        return {
            "success": True,
            "flowid": flowid,
            "message": "No se encontraron errores en telemetry",
            "total_events_analyzed": timeline["total_events"],
        }

    # Contexto: eventos anteriores al error (causa probable)
    context_before = timeline["events"][max(0, error_idx - 10):error_idx]
    # El error mismo
    error_event = timeline["events"][error_idx]
    # Eventos posteriores (consecuencias)
    context_after = timeline["events"][error_idx + 1:error_idx + 10]

    # Reconstruir el flujo de fases hasta el error
    phase_transitions = []
    for e in timeline["events"][:error_idx + 1]:
        if e.get("from_phase") and e.get("to_phase"):
            phase_transitions.append({
                "at": e["at"],
                "from": e["from_phase"],
                "to": e["to_phase"],
                "breakpoint_hit": e.get("breakpoint_hit", False),
            })

    replay = {
        "bugreplay": "V1",
        "schema_version": "3.1.0",
        "flowid": flowid,
        "generated_at": now_iso(),
        "bug_found": True,
        "error_event": error_event,
        "error_index_in_timeline": error_idx,
        "phase_transitions_before_error": phase_transitions,
        "context_before": context_before if verbose else [
            {"at": e["at"], "kind": e["kind"], "phase": e["phase"], "message": e["message"]}
            for e in context_before
        ],
        "context_after": context_after if verbose else [
            {"at": e["at"], "kind": e["kind"], "phase": e["phase"], "message": e["message"]}
            for e in context_after
        ],
        "analysis": {
            "total_events_before_error": error_idx,
            "events_analyzed_for_context": len(context_before),
            "phase_at_error": error_event.get("phase", ""),
            "tool_at_error": error_event.get("tool", ""),
            "likely_cause": _infer_cause(context_before, error_event),
            "recommendation": _recommend_fix(error_event, context_before),
        },
    }

    return replay


def _infer_cause(context: List[Dict], error: Dict) -> str:
    """Infiere la causa probable del bug basandose en el contexto."""
    if not context:
        return "Sin contexto previo disponible"

    # Buscar el ultimo tool invocado antes del error
    last_tool = None
    for e in reversed(context):
        if e.get("tool") or e.get("kind") == "tool-invoked":
            last_tool = e
            break

    if last_tool:
        return f"El error ocurrio despues de invocar {last_tool.get('tool', 'una tool')} en fase {last_tool.get('phase', '?')}"

    # Buscar la ultima transicion de fase
    last_transition = None
    for e in reversed(context):
        if e.get("from_phase") and e.get("to_phase"):
            last_transition = e
            break

    if last_transition:
        return f"El error ocurrio despues de transitar de {last_transition['from_phase']} a {last_transition['to_phase']}"

    return "Causa no determinable — revisar contexto manualmente"


def _recommend_fix(error: Dict, context: List[Dict]) -> str:
    """Recomienda una fix basandose en el tipo de error."""
    error_msg = (error.get("message", "") + " " + error.get("raw", {}).get("error", "")).lower()

    if "typeerror" in error_msg:
        return "TypeError detectado — verificar tipos de datos en inputs del script"
    if "keyerror" in error_msg:
        return "KeyError detectado — verificar que el YAML tenga las keys esperadas (usar post_script_gates)"
    if "filenotfounderror" in error_msg:
        return "FileNotFoundError — verificar paths relativos al repo_root"
    if "importerror" in error_msg or "modulenotfounderror" in error_msg:
        return "ImportError — verificar PYTHONPATH o dependencias faltantes"
    if "timeout" in error_msg:
        return "Timeout — aumentar timeout o dividir la tarea en pasos mas pequenos"
    if "yaml" in error_msg:
        return "YAML error — usar validate_artifact.py para validar contra schema"
    if "schema" in error_msg:
        return "Schema validation error — revisar contract del artifact"

    return "Revisar el contexto del error y aplicar fix segun el patrón detectado"


def find_patterns(repo_root: Path) -> Dict[str, Any]:
    """Busca patrones de fallo en todos los flows."""
    flows_dir = repo_root / "plan" / "active"
    if not flows_dir.exists():
        return {"success": True, "flows_analyzed": 0, "patterns": []}

    all_errors: List[Dict] = []
    flows_analyzed = 0

    for flow_d in flows_dir.iterdir():
        if not flow_d.is_dir():
            continue
        flowid = flow_d.name
        flows_analyzed += 1

        # Cargar telemetry
        tel_path = telemetry_path(repo_root, flowid)
        events = load_jsonl(tel_path)

        # Extraer errores
        for e in events:
            if e.get("severity") == "error" or "fail" in e.get("kind", "").lower():
                all_errors.append({
                    "flowid": flowid,
                    "at": e.get("at", ""),
                    "kind": e.get("kind", ""),
                    "phase": e.get("phase", ""),
                    "message": e.get("message", ""),
                })

    # Agrupar por kind
    kind_groups: Dict[str, List[Dict]] = defaultdict(list)
    for err in all_errors:
        kind_groups[err["kind"]].append(err)

    # Top patterns
    patterns = []
    for kind, errors in sorted(kind_groups.items(), key=lambda x: -len(x[1])):
        patterns.append({
            "kind": kind,
            "count": len(errors),
            "flows_affected": len(set(e["flowid"] for e in errors)),
            "phases_affected": list(set(e["phase"] for e in errors if e["phase"])),
            "sample_messages": list(set(e["message"][:100] for e in errors))[:3],
        })

    return {
        "success": True,
        "flows_analyzed": flows_analyzed,
        "total_errors": len(all_errors),
        "patterns": patterns,
        "generated_at": now_iso(),
    }


def list_flows(repo_root: Path) -> Dict[str, Any]:
    """Lista flows con telemetry disponible."""
    flows_dir = repo_root / "plan" / "active"
    if not flows_dir.exists():
        return {"success": True, "flows": [], "total": 0}

    flows = []
    for flow_d in flows_dir.iterdir():
        if not flow_d.is_dir():
            continue
        flowid = flow_d.name
        tel_path = telemetry_path(repo_root, flowid)
        event_count = 0
        error_count = 0
        first_event = ""
        last_event = ""
        if tel_path.exists():
            events = load_jsonl(tel_path)
            event_count = len(events)
            error_count = sum(1 for e in events if e.get("severity") == "error")
            if events:
                first_event = events[0].get("at", "")
                last_event = events[-1].get("at", "")
        flows.append({
            "flowid": flowid,
            "telemetry_entries": event_count,
            "error_count": error_count,
            "first_event_at": first_event,
            "last_event_at": last_event,
            "has_errors": error_count > 0,
        })

    return {"success": True, "flows": flows, "total": len(flows)}


def main() -> int:
    argv = sys.argv[1:]
    action = "timeline"
    known = {"timeline", "bug", "patterns", "flows"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "flows":
        result = list_flows(repo_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "timeline":
        flowid = args.get("flowid", "")
        if not flowid:
            print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
            return 2
        filter_kind = args.get("filter", "")
        # Parse filter "kind=value"
        if "=" in filter_kind:
            key, val = filter_kind.split("=", 1)
            if key == "kind":
                filter_kind = val
            else:
                filter_kind = ""
        timeline = build_timeline(repo_root, flowid, filter_kind=filter_kind)
        output = args.get("output")
        if output:
            write_yaml(Path(output), timeline)
            log(f"Timeline → {output}", "INFO")
        print(json.dumps({"success": True, **timeline}, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "bug":
        flowid = args.get("flowid", "")
        if not flowid:
            print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
            return 2
        verbose = args.get("verbose", "false") == "true"
        replay = find_bug_replay(repo_root, flowid, verbose)
        output = args.get("output")
        if output:
            write_yaml(Path(output), replay)
            log(f"Bug replay → {output}", "INFO")
        print(json.dumps({"success": True, **replay}, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "patterns":
        result = find_patterns(repo_root)
        output = args.get("output")
        if output:
            write_yaml(Path(output), result)
            log(f"Patterns → {output}", "INFO")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

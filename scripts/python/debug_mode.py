#!/usr/bin/env python3
"""
debug_mode.py — Modo debug paso a paso con breakpoints en el state machine (v2.8.1).

Cierra el GAP #12: "Modo debug paso a paso (breakpoints en el state machine)".

Permite al usuario inspeccionar el estado del flow en cualquier momento y poner
breakpoints en fases específicas del state machine. Cuando el loop engine
alcanza un breakpoint, registra el estado completo en DEBUG-TRACE.jsonl y
permite al usuario inspeccionar variables, evidencia acumulada, y decisiones
previas antes de continuar.

Funciona en 3 modos:

1. **breakpoint set**: Define breakpoints por fase
   python3 debug_mode.py set --flowid X --phase reanclaje
   python3 debug_mode.py set --flowid X --phase reanclaje,verdad

2. **trace inspect**: Lista todas las transiciones del state machine
   python3 debug_mode.py trace --flowid X
   python3 debug_mode.py trace --flowid X --from-phase verdad --to-phase reanclaje

3. **step**: Avanza un solo paso (simulado — el loop engine real respeta los breakpoints)
   python3 debug_mode.py step --flowid X
   python3 debug_mode.py step --flowid X --inspect evidence

4. **watch**: Monitorea cambios en el state machine en tiempo real
   python3 debug_mode.py watch --flowid X

5. **backtrace**: Muestra el stack de decisiones que llevaron al estado actual
   python3 debug_mode.py backtrace --flowid X

El loop engine TS debe consultar is_breakpoint() antes de cada transición
(vía HTTP o leyendo el archivo DEBUG-BREAKPOINTS.yaml).
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
from common import log, now_iso, parse_args, read_yaml, write_yaml, state_path, telemetry_path, flow_dir


BREAKPOINTS_FILE = "DEBUG-BREAKPOINTS.yaml"
TRACE_FILE = "DEBUG-TRACE.jsonl"


def breakpoints_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / BREAKPOINTS_FILE


def trace_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / TRACE_FILE


def set_breakpoints(repo_root: Path, flowid: str, phases: List[str]) -> Dict[str, Any]:
    """Define breakpoints para un flow."""
    bp_path = breakpoints_path(repo_root, flowid)
    bp_path.parent.mkdir(parents=True, exist_ok=True)

    existing = read_yaml(bp_path) or {}
    current = existing.get("breakpoints", [])
    # Merge
    merged = list(set(current) | set(phases))

    data = {
        "breakpoints": sorted(merged),
        "flowid": flowid,
        "updated_at": now_iso(),
        "enabled": True,
    }
    write_yaml(bp_path, data)
    log(f"Breakpoints set: {data['breakpoints']}", "INFO")
    return data


def clear_breakpoints(repo_root: Path, flowid: str, phases: List[str] = None) -> Dict[str, Any]:
    """Limpia breakpoints (todos o solo los especificados)."""
    bp_path = breakpoints_path(repo_root, flowid)
    if not bp_path.exists():
        return {"breakpoints": [], "cleared": True}

    existing = read_yaml(bp_path) or {}
    current = existing.get("breakpoints", [])
    if phases:
        remaining = [p for p in current if p not in phases]
    else:
        remaining = []
    data = {
        "breakpoints": remaining,
        "flowid": flowid,
        "updated_at": now_iso(),
        "enabled": len(remaining) > 0,
    }
    write_yaml(bp_path, data)
    return data


def is_breakpoint(repo_root: Path, flowid: str, phase: str) -> bool:
    """Verifica si una fase es breakpoint (consultado por el loop engine TS)."""
    bp_path = breakpoints_path(repo_root, flowid)
    if not bp_path.exists():
        return False
    bp = read_yaml(bp_path) or {}
    if not bp.get("enabled", True):
        return False
    return phase in (bp.get("breakpoints") or [])


def append_trace(repo_root: Path, flowid: str, event: Dict[str, Any]) -> None:
    """Agrega un evento al trace de debug (append-only)."""
    tp = trace_path(repo_root, flowid)
    tp.parent.mkdir(parents=True, exist_ok=True)
    event["at"] = now_iso()
    event["flowid"] = flowid
    with open(tp, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def get_trace(repo_root: Path, flowid: str, from_phase: str = "", to_phase: str = "") -> List[Dict[str, Any]]:
    """Lee el trace de debug."""
    tp = trace_path(repo_root, flowid)
    if not tp.exists():
        return []
    results = []
    for line in tp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if from_phase and entry.get("from_phase") != from_phase:
                continue
            if to_phase and entry.get("to_phase") != to_phase:
                continue
            results.append(entry)
        except json.JSONDecodeError:
            continue
    return results


def inspect_state(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Inspecciona el estado actual del flow."""
    sp = state_path(repo_root, flowid)
    state = read_yaml(sp) or {} if sp.exists() else {}

    # Buscar archivos relacionados
    flow_d = flow_dir(repo_root, flowid)
    evidence_files = list((flow_d / "evidence").glob("*.yaml")) if (flow_d / "evidence").exists() else []
    plan_files = list((flow_d / "plans").glob("*.yaml")) if (flow_d / "plans").exists() else []

    return {
        "flowid": flowid,
        "current_phase": state.get("phase", "unknown"),
        "current_status": state.get("status", "unknown"),
        "history_count": len(state.get("history", [])),
        "evidence_files": [str(p.name) for p in evidence_files],
        "plan_files": [str(p.name) for p in plan_files],
        "breakpoints_active": is_breakpoint_active(repo_root, flowid),
        "telemetry_entries": _count_telemetry(repo_root, flowid),
        "state_path": str(sp),
    }


def is_breakpoint_active(repo_root: Path, flowid: str) -> List[str]:
    bp_path = breakpoints_path(repo_root, flowid)
    if not bp_path.exists():
        return []
    bp = read_yaml(bp_path) or {}
    if not bp.get("enabled", True):
        return []
    return bp.get("breakpoints") or []


def _count_telemetry(repo_root: Path, flowid: str) -> int:
    tp = telemetry_path(repo_root, flowid)
    if not tp.exists():
        return 0
    count = 0
    for line in tp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            count += 1
    return count


def backtrace(repo_root: Path, flowid: str) -> List[Dict[str, Any]]:
    """Construye un backtrace de decisiones desde el trace + telemetry."""
    trace = get_trace(repo_root, flowid)
    tp = telemetry_path(repo_root, flowid)
    telemetry: List[Dict[str, Any]] = []
    if tp.exists():
        for line in tp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                telemetry.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Combinar trace + telemetry, ordenar por timestamp
    combined = []
    for t in trace:
        combined.append({
            "source": "trace",
            "at": t.get("at", ""),
            "from_phase": t.get("from_phase", ""),
            "to_phase": t.get("to_phase", ""),
            "kind": t.get("kind", "transition"),
            "message": t.get("message", ""),
            "actor": t.get("actor", "system"),
        })
    for e in telemetry:
        combined.append({
            "source": "telemetry",
            "at": e.get("at", ""),
            "from_phase": "",
            "to_phase": e.get("phase", ""),
            "kind": e.get("kind", "event"),
            "message": e.get("message", ""),
            "actor": e.get("actor", e.get("severity", "system")),
        })

    combined.sort(key=lambda x: x.get("at", ""))
    return combined


def step(repo_root: Path, flowid: str, inspect_target: str = "") -> Dict[str, Any]:
    """Avanza un paso en el flow (en modo debug).

    En la implementación real, el loop engine TS consultaría este comando
    para saber si puede avanzar. Aquí simulamos el avance registrando el
    evento en el trace.
    """
    state_info = inspect_state(repo_root, flowid)
    current_phase = state_info["current_phase"]
    bps = state_info["breakpoints_active"]

    # Determine next phase (simplified state machine)
    next_phase = _next_phase(current_phase)

    # Check if current or next phase is a breakpoint
    bp_hit = current_phase in bps or next_phase in bps

    event = {
        "kind": "step",
        "from_phase": current_phase,
        "to_phase": next_phase,
        "actor": "debug",
        "message": f"Step from {current_phase} to {next_phase}",
        "breakpoint_hit": bp_hit,
        "breakpoint_phase": current_phase if current_phase in bps else (next_phase if next_phase in bps else None),
    }
    append_trace(repo_root, flowid, event)

    result = {
        "stepped": True,
        "from_phase": current_phase,
        "to_phase": next_phase,
        "breakpoint_hit": bp_hit,
        "state": state_info,
    }

    if inspect_target:
        if inspect_target == "evidence":
            sp = state_path(repo_root, flowid)
            ev_dir = flow_dir(repo_root, flowid) / "evidence"
            files = []
            if ev_dir.exists():
                for f in ev_dir.glob("*.yaml"):
                    files.append({
                        "file": str(f.name),
                        "preview": _yaml_preview(f),
                    })
            result["inspected"] = {"target": "evidence", "files": files}
        elif inspect_target == "telemetry":
            tp = telemetry_path(repo_root, flowid)
            entries = []
            if tp.exists():
                for line in tp.read_text(encoding="utf-8").splitlines()[-5:]:
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            result["inspected"] = {"target": "telemetry", "last_5": entries}
        elif inspect_target == "state":
            sp = state_path(repo_root, flowid)
            result["inspected"] = {"target": "state", "full_state": _yaml_preview(sp, 500)}

    return result


def _next_phase(current: str) -> str:
    """State machine simplificado: init → verdad → plan-indice → reanclaje → exec → validar → merge."""
    order = ["init", "verdad", "plan-indice", "reanclaje", "exec", "validar", "merge", "done"]
    if current in order:
        idx = order.index(current)
        if idx + 1 < len(order):
            return order[idx + 1]
    return "done"


def _yaml_preview(path: Path, max_chars: int = 200) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


def main() -> int:
    argv = sys.argv[1:]
    action = "inspect"
    known = {"set", "clear", "trace", "step", "watch", "backtrace", "inspect", "is-bp"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid and action not in ("is-bp",):
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
        return 2

    if action == "set":
        phases_str = args.get("phase", "") or args.get("phases", "")
        phases = [p.strip() for p in phases_str.split(",") if p.strip()]
        if not phases:
            print(json.dumps({"success": False, "error": "Falta --phase (comma-separated)"}, indent=2))
            return 2
        result = set_breakpoints(repo_root, flowid, phases)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0

    elif action == "clear":
        phases_str = args.get("phase", "") or args.get("phases", "")
        phases = [p.strip() for p in phases_str.split(",") if p.strip()] if phases_str else None
        result = clear_breakpoints(repo_root, flowid, phases)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0

    elif action == "trace":
        from_phase = args.get("from-phase", "")
        to_phase = args.get("to-phase", "")
        results = get_trace(repo_root, flowid, from_phase, to_phase)
        print(json.dumps({"success": True, "count": len(results), "trace": results}, ensure_ascii=False, indent=2))
        return 0

    elif action == "step":
        inspect_target = args.get("inspect", "")
        result = step(repo_root, flowid, inspect_target)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0

    elif action == "backtrace":
        results = backtrace(repo_root, flowid)
        print(json.dumps({"success": True, "count": len(results), "backtrace": results}, ensure_ascii=False, indent=2))
        return 0

    elif action == "inspect":
        result = inspect_state(repo_root, flowid)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0

    elif action == "is-bp":
        phase = args.get("phase", "")
        if not phase:
            print(json.dumps({"success": False, "error": "Falta --phase"}, indent=2))
            return 2
        hit = is_breakpoint(repo_root, flowid, phase)
        print(json.dumps({"success": True, "flowid": flowid, "phase": phase, "is_breakpoint": hit}, indent=2))
        return 0

    elif action == "watch":
        # Watch mode: poll state every 2s for 60s
        duration = int(args.get("duration", "60") or 60)
        log(f"Watching {flowid} for {duration}s...", "INFO")
        seen_states = set()
        start = time.time()
        events = []
        while time.time() - start < duration:
            state = inspect_state(repo_root, flowid)
            key = f"{state['current_phase']}:{state['current_status']}"
            if key not in seen_states:
                seen_states.add(key)
                event = {
                    "kind": "watch-detect",
                    "phase": state["current_phase"],
                    "status": state["current_status"],
                    "at": now_iso(),
                }
                events.append(event)
                append_trace(repo_root, flowid, event)
                log(f"State change: {key}", "INFO")
            time.sleep(2)
        print(json.dumps({"success": True, "watched_for_s": int(time.time() - start), "state_changes": events}, ensure_ascii=False, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

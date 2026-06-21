#!/usr/bin/env python3
"""
telemetry_aggregator.py — Agrega eventos de telemetría a un snapshot JSON.

Lee telemetry.jsonl y produce un JSON agregado con stats, timeline y
top-K de eventos. Consumido por panel/index.html.

Uso:
  python3 telemetry_aggregator.py --input telemetry.jsonl --output stats.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from common import log, parse_args, read_json, write_json


def aggregate(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats = {
        "total_events": len(events),
        "events_by_kind": Counter(),
        "events_by_phase": Counter(),
        "events_by_severity": Counter(),
        "total_tokens": 0,
        "total_duration_ms": 0,
        "phase_durations_ms": Counter(),
        "blocks_detected": 0,
        "blocks_resolved": 0,
        "tests_run": 0,
        "tests_failed": 0,
        "rollbacks": 0,
        "tools_absorbed": 0,
        "timeline": [],  # últimos 100 eventos para el panel
        "phase_transitions": [],  # history de phase-enter
    }

    for e in events:
        stats["events_by_kind"][e.get("kind", "?")] += 1
        stats["events_by_phase"][e.get("phase", "?")] += 1
        stats["events_by_severity"][e.get("severity", "?")] += 1
        if e.get("tokens"):
            stats["total_tokens"] += e["tokens"]
        if e.get("duration_ms"):
            stats["total_duration_ms"] += e["duration_ms"]
            stats["phase_durations_ms"][e.get("phase", "?")] += e["duration_ms"]
        if e.get("kind") == "block-detected":
            stats["blocks_detected"] += 1
        if e.get("kind") == "block-resolved":
            stats["blocks_resolved"] += 1
        if e.get("kind") == "test-run":
            stats["tests_run"] += 1
        if e.get("kind") == "test-fail":
            stats["tests_failed"] += 1
        if e.get("kind") == "rollback":
            stats["rollbacks"] += 1
        if e.get("kind") == "tool-absorbed":
            stats["tools_absorbed"] += 1
        if e.get("kind") == "phase-enter":
            stats["phase_transitions"].append({
                "at": e.get("at"),
                "phase": e.get("phase"),
                "message": e.get("message"),
            })

    stats["timeline"] = events[-100:]

    # Convertir Counters a dict para JSON
    stats["events_by_kind"] = dict(stats["events_by_kind"])
    stats["events_by_phase"] = dict(stats["events_by_phase"])
    stats["events_by_severity"] = dict(stats["events_by_severity"])
    stats["phase_durations_ms"] = dict(stats["phase_durations_ms"])
    return stats


def main() -> int:
    args = parse_args(sys.argv[1:])
    input_p = Path(args.get("input", "telemetry.jsonl"))
    output_p = Path(args.get("output", "telemetry-stats.json"))

    if not input_p.exists():
        log(f"input no existe: {input_p}", "ERROR")
        return 2

    events: List[Dict[str, Any]] = []
    for line in input_p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            continue

    stats = aggregate(events)
    write_json(output_p, stats)
    log(f"agregado {len(events)} eventos → {output_p}", "INFO")
    print(json.dumps({
        "success": True,
        "events": len(events),
        "blocks_detected": stats["blocks_detected"],
        "tests_run": stats["tests_run"],
        "tests_failed": stats["tests_failed"],
        "rollbacks": stats["rollbacks"],
        "tokens": stats["total_tokens"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

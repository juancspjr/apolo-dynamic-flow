#!/usr/bin/env python3
"""
self_healing.py — Engine de auto-curación (v2.6.0).

Aprende de fallos pasados analizando telemetry.jsonl y ajusta routing
automáticamente cuando un agente falla consistentemente en una fase.

Si LLM disponible (llm_bridge), usa análisis inteligente de razones de fallo.
Si no, usa heurísticas estadísticas puras (100% determinista).

Uso:
  python3 self_healing.py --repo-root . --flowid APOLO-TEST --output LEARNING-STATE.yaml
  python3 self_healing.py --repo-root . --apply  # aplicar ajustes a routing-rules.json
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


def load_telemetry(telemetry_path: Path) -> List[Dict]:
    if not telemetry_path.exists():
        return []
    events = []
    for line in telemetry_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events


def compute_success_rates(events: List[Dict]) -> Dict[str, Dict[str, Dict]]:
    """Computa success/fail rates por (agent, phase)."""
    stats = defaultdict(lambda: defaultdict(lambda: {"total": 0, "success": 0, "fail": 0}))
    
    for e in events:
        actor = e.get("actor", "")
        if not actor.startswith("agent:"):
            continue
        agent = actor.replace("agent:", "")
        phase = e.get("phase", "unknown")
        outcome = e.get("outcome", "")
        action = e.get("action", "")
        
        # Only count decision/test events
        if action not in ("decision_made", "test_executed", "test_passed", "test_failed",
                          "mp_admitted", "mp_rejected", "blocker_raised"):
            continue
        
        stats[agent][phase]["total"] += 1
        if outcome in ("success",):
            stats[agent][phase]["success"] += 1
        elif outcome in ("failure", "warning", "blocked"):
            stats[agent][phase]["fail"] += 1
    
    # Calculate rates
    result = {}
    for agent, phases in stats.items():
        result[agent] = {}
        for phase, counts in phases.items():
            total = counts["total"]
            success = counts["success"]
            fail = counts["fail"]
            rate = success / total if total > 0 else 0.0
            result[agent][phase] = {
                "total": total,
                "success": success,
                "fail": fail,
                "success_rate": round(rate, 3),
            }
    return result


def suggest_adjustments(success_rates: Dict) -> List[Dict]:
    """Sugiere ajustes de routing cuando un agente falla >60% en una fase."""
    suggestions = []
    for agent, phases in success_rates.items():
        for phase, stats in phases.items():
            if stats["total"] < 3:
                continue  # Need minimum samples
            if stats["success_rate"] < 0.4:
                # Agent fails >60% in this phase
                alternatives = {
                    "planner": "truth-auditor",
                    "truth-auditor": "surface-scanner",
                    "surface-scanner": "evidence-acquisition",
                    "implementer": "microplanner",
                    "microplanner": "planner",
                }
                alt = alternatives.get(agent, "orchestrator")
                suggestions.append({
                    "agent": agent,
                    "phase": phase,
                    "success_rate": stats["success_rate"],
                    "total_attempts": stats["total"],
                    "suggestion": f"Redirect {phase} from {agent} to {alt} ({agent} has {stats['success_rate']*100:.0f}% success)",
                    "alternative_agent": alt,
                    "confidence": round(1.0 - stats["success_rate"], 3),
                })
    return suggestions


def analyze_failure_patterns(events: List[Dict]) -> List[Dict]:
    """Identifica patrones de fallo recurrentes."""
    patterns = defaultdict(lambda: {"count": 0, "examples": []})
    
    for e in events:
        if e.get("outcome") not in ("failure", "warning"):
            continue
        action = e.get("action", "unknown")
        phase = e.get("phase", "unknown")
        msg = e.get("message", "")[:100]
        key = f"{action}@{phase}"
        patterns[key]["count"] += 1
        if len(patterns[key]["examples"]) < 3:
            patterns[key]["examples"].append(msg)
    
    return [{"pattern": k, "count": v["count"], "examples": v["examples"]} 
            for k, v in patterns.items() if v["count"] >= 2]


def apply_adjustments(routing_rules_path: Path, suggestions: List[Dict]) -> bool:
    """Aplica ajustes a routing-rules.json (con backup)."""
    if not suggestions:
        return False
    
    rules = read_yaml(routing_rules_path) or {}
    if not rules.get("rules"):
        return False
    
    # Backup
    backup_path = routing_rules_path.with_suffix(".json.bak")
    write_yaml(backup_path, rules)
    
    applied = 0
    for s in suggestions:
        for rule in rules.get("rules", []):
            when = rule.get("when", {})
            then = rule.get("then", {})
            if when.get("phase") == s["phase"] and then.get("next_agent") == s["agent"]:
                then["next_agent"] = s["alternative_agent"]
                then["reason"] = f"Self-healing: {s['suggestion']}"
                applied += 1
                break
    
    if applied > 0:
        rules["version"] = f"{rules.get('version', 'v2.0')}-healed"
        write_yaml(routing_rules_path, rules)
        log(f"Self-healing: {applied} ajustes aplicados a routing-rules.json", "INFO")
        return True
    return False


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")
    output = Path(args.get("output", "LEARNING-STATE.yaml"))
    apply = args.get("apply", "") == "true"
    
    # Find telemetry
    tel_path = None
    if flowid:
        tel_path = repo_root / "plan" / "active" / flowid / "telemetry.jsonl"
    else:
        # Search all flows
        active_dir = repo_root / "plan" / "active"
        if active_dir.exists():
            all_events = []
            for flow_dir in active_dir.iterdir():
                tp = flow_dir / "telemetry.jsonl"
                if tp.exists():
                    all_events.extend(load_telemetry(tp))
            events = all_events
        else:
            events = []
    
    if tel_path and tel_path.exists():
        events = load_telemetry(tel_path)
    elif not flowid:
        pass  # events already set above
    else:
        events = []
    
    if not events:
        log("No telemetry events found", "WARN")
        events = []
    
    success_rates = compute_success_rates(events)
    suggestions = suggest_adjustments(success_rates)
    patterns = analyze_failure_patterns(events)
    
    learning_state = {
        "learningstate": "V1",
        "version": 1,
        "updated_at": now_iso(),
        "flowid": flowid,
        "events_analyzed": len(events),
        "agent_performance": success_rates,
        "suggested_adjustments": suggestions,
        "failure_patterns": patterns,
        "applied_adjustments": [],
    }
    
    # Try LLM analysis if available
    try:
        from llm_bridge import is_available, analyze_code
        if is_available() and patterns:
            llm_analysis = analyze_code(
                json.dumps(patterns[:5], indent=2),
                "What are the root causes of these failure patterns? Suggest 3 concrete improvements."
            )
            if llm_analysis:
                learning_state["llm_analysis"] = llm_analysis[:2000]
                log("LLM analysis included in learning state", "INFO")
    except ImportError:
        pass
    
    write_yaml(output, learning_state)
    
    if apply and suggestions:
        routing_path = repo_root / "routing-rules.json"
        if apply_adjustments(routing_path, suggestions):
            learning_state["applied_adjustments"] = suggestions
            write_yaml(output, learning_state)
    
    log(f"Self-healing: {len(events)} events, {len(success_rates)} agents, {len(suggestions)} suggestions", "INFO")
    print(json.dumps({
        "success": True,
        "events_analyzed": len(events),
        "agents_analyzed": len(success_rates),
        "suggestions": len(suggestions),
        "patterns": len(patterns),
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

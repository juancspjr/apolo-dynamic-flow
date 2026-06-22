#!/usr/bin/env python3
"""
multi_agent_coordinator.py — Coordina 2+ agentes en paralelo sobre el mismo MP (v3.4.0).

Cierra el GAP: "Multi-agent coordination: 2+ agentes en paralelo sobre el mismo MP"

Permite que multiples agentes trabajen en paralelo sobre diferentes unidades (MPs)
del mismo plan, coordinandose via un archivo de lock compartido y merging results.

CLI:
  # Registrar un agente para trabajar en una unidad
  python3 multi_agent_coordinator.py register --flowid X --agent-id agent-1 --unit-id U-01

  # Ver que agentes estan trabajando
  python3 multi_agent_coordinator.py status --flowid X

  # Marcar unidad como completada
  python3 multi_agent_coordinator.py complete --flowid X --agent-id agent-1 --unit-id U-01 --result-json '{"success":true}'

  # Ver conflicts (si 2 agentes tocaron los mismos archivos)
  python3 multi_agent_coordinator.py conflicts --flowid X

  # Merge results de todos los agentes
  python3 multi_agent_coordinator.py merge --flowid X
"""

from __future__ import annotations
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


def coord_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "MULTI-AGENT-COORDINATION.yaml"


def load_coord(repo_root: Path, flowid: str) -> Dict[str, Any]:
    p = coord_path(repo_root, flowid)
    if not p.exists():
        return {"flowid": flowid, "agents": {}, "units": {}, "conflicts": [], "started_at": now_iso()}
    return read_yaml(p) or {}


def save_coord(repo_root: Path, flowid: str, data: Dict) -> None:
    p = coord_path(repo_root, flowid)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(p, data)


def register_agent(repo_root: Path, flowid: str, agent_id: str, unit_id: str, files: List[str] = None) -> Dict[str, Any]:
    """Registra un agente para trabajar en una unidad."""
    coord = load_coord(repo_root, flowid)

    # Verificar que la unidad no este tomada por otro agente
    existing = coord.get("units", {}).get(unit_id, {})
    if existing.get("agent_id") and existing.get("agent_id") != agent_id and existing.get("status") == "in_progress":
        return {"success": False, "error": f"Unidad {unit_id} ya tomada por {existing['agent_id']}"}

    coord.setdefault("agents", {})[agent_id] = {
        "agent_id": agent_id,
        "unit_id": unit_id,
        "files": files or [],
        "status": "in_progress",
        "started_at": now_iso(),
    }
    coord.setdefault("units", {})[unit_id] = {
        "agent_id": agent_id,
        "status": "in_progress",
        "started_at": now_iso(),
    }

    # Detectar conflicts: si 2 agentes tocan los mismos archivos
    if files:
        for aid, agent in coord.get("agents", {}).items():
            if aid == agent_id:
                continue
            overlap = set(files) & set(agent.get("files", []))
            if overlap:
                coord.setdefault("conflicts", []).append({
                    "agent_1": aid,
                    "agent_2": agent_id,
                    "files": list(overlap),
                    "detected_at": now_iso(),
                })
                log(f"⚠ CONFLICT: {agent_id} y {aid} tocan archivos en comun: {overlap}", "WARN")

    save_coord(repo_root, flowid, coord)
    return {"success": True, "agent_id": agent_id, "unit_id": unit_id, "conflicts_detected": len(coord.get("conflicts", []))}


def complete_unit(repo_root: Path, flowid: str, agent_id: str, unit_id: str, result: Dict) -> Dict[str, Any]:
    """Marca una unidad como completada por un agente."""
    coord = load_coord(repo_root, flowid)
    if unit_id not in coord.get("units", {}):
        return {"success": False, "error": f"Unidad {unit_id} no registrada"}

    coord["units"][unit_id]["status"] = "completed"
    coord["units"][unit_id]["completed_at"] = now_iso()
    coord["units"][unit_id]["result"] = result

    if agent_id in coord.get("agents", {}):
        coord["agents"][agent_id]["status"] = "completed"
        coord["agents"][agent_id]["completed_at"] = now_iso()

    save_coord(repo_root, flowid, coord)
    return {"success": True, "unit_id": unit_id, "agent_id": agent_id}


def get_status(repo_root: Path, flowid: str) -> Dict[str, Any]:
    coord = load_coord(repo_root, flowid)
    agents = coord.get("agents", {})
    units = coord.get("units", {})
    return {
        "success": True,
        "flowid": flowid,
        "total_agents": len(agents),
        "active_agents": sum(1 for a in agents.values() if a.get("status") == "in_progress"),
        "completed_agents": sum(1 for a in agents.values() if a.get("status") == "completed"),
        "total_units": len(units),
        "completed_units": sum(1 for u in units.values() if u.get("status") == "completed"),
        "conflicts": coord.get("conflicts", []),
    }


def get_conflicts(repo_root: Path, flowid: str) -> Dict[str, Any]:
    coord = load_coord(repo_root, flowid)
    return {"success": True, "conflicts": coord.get("conflicts", []), "total": len(coord.get("conflicts", []))}


def merge_results(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Merge results de todos los agentes completados."""
    coord = load_coord(repo_root, flowid)
    units = coord.get("units", {})
    completed = {uid: u for uid, u in units.items() if u.get("status") == "completed"}

    merged = {
        "flowid": flowid,
        "merged_at": now_iso(),
        "total_units_completed": len(completed),
        "results": {},
        "all_success": all(u.get("result", {}).get("success", False) for u in completed.values()),
    }
    for uid, u in completed.items():
        merged["results"][uid] = u.get("result", {})

    write_yaml(flow_dir(repo_root, flowid) / "MERGED-RESULTS.yaml", merged)
    return {"success": True, **merged}


def main() -> int:
    argv = sys.argv[1:]
    action = "status"
    known = {"register", "complete", "status", "conflicts", "merge"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")
    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "register":
        agent_id = args.get("agent-id", "")
        unit_id = args.get("unit-id", "")
        files_str = args.get("files", "")
        files = [f.strip() for f in files_str.split(",") if f.strip()] if files_str else []
        if not agent_id or not unit_id:
            print(json.dumps({"success": False, "error": "Falta --agent-id y --unit-id"}, indent=2)); return 2
        r = register_agent(repo_root, flowid, agent_id, unit_id, files)
        print(json.dumps(r, indent=2)); return 0 if r["success"] else 1
    elif action == "complete":
        agent_id = args.get("agent-id", "")
        unit_id = args.get("unit-id", "")
        result_json = args.get("result-json", "{}")
        try: result = json.loads(result_json)
        except: result = {"raw": result_json}
        r = complete_unit(repo_root, flowid, agent_id, unit_id, result)
        print(json.dumps(r, indent=2)); return 0 if r["success"] else 1
    elif action == "status":
        r = get_status(repo_root, flowid); print(json.dumps(r, indent=2)); return 0
    elif action == "conflicts":
        r = get_conflicts(repo_root, flowid); print(json.dumps(r, indent=2)); return 0
    elif action == "merge":
        r = merge_results(repo_root, flowid); print(json.dumps(r, ensure_ascii=False, indent=2, default=str)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

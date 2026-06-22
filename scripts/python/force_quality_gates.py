#!/usr/bin/env python3
"""
force_quality_gates.py — Gates que OBLIGAN al agente a actuar con calidad (v3.2.0).

RESPONDE a la intencion del usuario:
  "obligado hacer las cosas con calidad a actuar"
  "determinismo para obligar al agente decir la verdad actuar con todos los
   pasos sin descanso"

A diferencia de post_script_gates.py (que valida outputs YAML), estos gates
validan el COMPORTAMIENTO del agente:

  1. COMPLETITUD: el agente no puede saltarse pasos del ciclo
  2. VERACIDAD: el agente no puede declarar "done" si los tests fallan
  3. EVIDENCIA: el agente no puede avanzar sin evidence pack valido
  4. NO_SILENT_FAIL: el agente debe reportar errores, no ocultarlos
  5. TESTS_PASS: el agente no puede declarar success si tests fallan
  6. SCAFFOLD_USED: el agente debe implementar usando el scaffold generado
  7. NO_REGRESSION: el agente no puede romper tests existentes

Si un gate falla, el sistema BLOQUEA al agente (no puede avanzar de fase)
hasta que cumpla.

CLI:
  # Verificar todos los gates para un flow
  python3 force_quality_gates.py check --flowid APOLO-X --repo-root .

  # Verificar un gate especifico
  python3 force_quality_gates.py check-one --gate tests_pass --flowid APOLO-X

  # Listar gates configurados
  python3 force_quality_gates.py list

  # Reset gates bloqueados (despues de fix)
  python3 force_quality_gates.py reset --flowid APOLO-X
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, flow_dir, state_path, telemetry_path


# ============================================================================
# Quality gates definition
# ============================================================================

QUALITY_GATES = [
    {
        "id": "QG-01",
        "name": "completitud",
        "description": "El agente no puede saltarse pasos del ciclo",
        "check": "phases_completed",
        "blocking": True,
    },
    {
        "id": "QG-02",
        "name": "veracidad",
        "description": "El agente no puede declarar done si hay errores en telemetry",
        "check": "no_errors_in_telemetry",
        "blocking": True,
    },
    {
        "id": "QG-03",
        "name": "evidence_valida",
        "description": "El agente no puede avanzar sin evidence pack con items >= 1",
        "check": "evidence_has_items",
        "blocking": True,
    },
    {
        "id": "QG-04",
        "name": "no_silent_fail",
        "description": "El agente debe reportar errores, no ocultarlos",
        "check": "errors_reported",
        "blocking": True,
    },
    {
        "id": "QG-05",
        "name": "tests_pass",
        "description": "El agente no puede declarar success si tests fallan",
        "check": "tests_passing",
        "blocking": True,
    },
    {
        "id": "QG-06",
        "name": "scaffold_used",
        "description": "El agente debe implementar usando el scaffold generado",
        "check": "scaffold_referenced",
        "blocking": False,  # warn only
    },
    {
        "id": "QG-07",
        "name": "no_regression",
        "description": "El agente no puede romper tests existentes",
        "check": "no_new_test_failures",
        "blocking": True,
    },
]


# ============================================================================
# Gate checks
# ============================================================================

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


def check_phases_completed(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-01: Verifica que las fases requeridas esten completadas."""
    orch_state_path = flow_dir(repo_root, flowid) / "ORCHESTRATOR-STATE.yaml"
    if not orch_state_path.exists():
        return {"passed": False, "reason": "ORCHESTRATOR-STATE.yaml no existe — el orquestador no ha corrido"}

    state = read_yaml(orch_state_path) or {}
    completed = state.get("completed_phases", [])

    required = ["init", "index", "collect", "score", "plan"]
    missing = [p for p in required if p not in completed]

    if missing:
        return {
            "passed": False,
            "reason": f"Fases incompletas: {missing}. El agente no puede saltarse pasos.",
            "completed": completed,
            "missing": missing,
        }
    return {"passed": True, "completed": completed}


def check_no_errors_in_telemetry(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-02: Verifica que no haya errores en telemetry."""
    tel_path = telemetry_path(repo_root, flowid)
    events = load_jsonl(tel_path)

    errors = [e for e in events if e.get("severity") == "error" or "fail" in e.get("kind", "").lower()]

    if errors:
        return {
            "passed": False,
            "reason": f"{len(errors)} errores en telemetry — el agente no puede declarar done",
            "error_count": len(errors),
            "sample_errors": errors[:3],
        }
    return {"passed": True, "total_events": len(events)}


def check_evidence_has_items(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-03: Verifica que evidence pack tenga items."""
    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    if not ev_path.exists():
        return {"passed": False, "reason": "EVIDENCE-PACK.yaml no existe"}

    ev_data = read_yaml(ev_path) or {}
    items = ev_data.get("items", [])

    if len(items) < 1:
        return {
            "passed": False,
            "reason": "Evidence pack vacio — el agente no puede avanzar sin evidencia",
            "items_count": 0,
        }
    return {"passed": True, "items_count": len(items)}


def check_errors_reported(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-04: Verifica que errores hayan sido reportados (no ocultos)."""
    tel_path = telemetry_path(repo_root, flowid)
    events = load_jsonl(tel_path)

    # Si hay eventos con severity=error, deben tener message no vacio
    errors = [e for e in events if e.get("severity") == "error"]
    unreported = [e for e in errors if not e.get("message", "").strip()]

    if unreported:
        return {
            "passed": False,
            "reason": f"{len(unreported)} errores sin mensaje — el agente debe reportar errores",
            "unreported_count": len(unreported),
        }
    return {"passed": True, "errors_with_messages": len(errors)}


def check_tests_passing(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-05: Verifica que los tests esten pasando."""
    # Buscar el ultimo resultado de tests en telemetry
    tel_path = telemetry_path(repo_root, flowid)
    events = load_jsonl(tel_path)

    test_events = [e for e in events if "test" in e.get("kind", "").lower() or "test" in e.get("phase", "").lower()]

    if not test_events:
        return {"passed": True, "reason": "No hay eventos de tests (puede ser pre-implementacion)"}

    last_test = test_events[-1]
    if last_test.get("severity") == "error" or "fail" in last_test.get("kind", "").lower():
        return {
            "passed": False,
            "reason": f"Ultimo test fallo: {last_test.get('message', '')}",
            "last_test_event": last_test,
        }
    return {"passed": True, "last_test_event": last_test}


def check_scaffold_referenced(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-06: Verifica que el scaffold fue referenciado (warn only)."""
    scaffold_path = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD-V3.yaml"
    if not scaffold_path.exists():
        return {"passed": True, "reason": "No hay scaffold v3 (puede ser fase previa)"}

    scaffold = read_yaml(scaffold_path) or {}
    # Verificar que el scaffold tiene files_to_create concretos
    files_to_create = scaffold.get("files_to_create", [])
    if not files_to_create:
        return {
            "passed": False,
            "reason": "Scaffold v3 no tiene files_to_create — el agente debe usar scaffold concreto",
            "blocking": False,
        }
    return {"passed": True, "files_to_create": len(files_to_create)}


def check_no_new_test_failures(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """QG-07: Verifica que no haya nuevas fallas de tests."""
    # Simplificado: si hay mas de 3 errores de tests en telemetry, bloquear
    tel_path = telemetry_path(repo_root, flowid)
    events = load_jsonl(tel_path)

    test_failures = [
        e for e in events
        if "test" in e.get("kind", "").lower() and e.get("severity") == "error"
    ]

    if len(test_failures) > 3:
        return {
            "passed": False,
            "reason": f"{len(test_failures)} fallas de tests — posible regresion",
            "failure_count": len(test_failures),
        }
    return {"passed": True, "failure_count": len(test_failures)}


GATE_CHECKS = {
    "phases_completed": check_phases_completed,
    "no_errors_in_telemetry": check_no_errors_in_telemetry,
    "evidence_has_items": check_evidence_has_items,
    "errors_reported": check_errors_reported,
    "tests_passing": check_tests_passing,
    "scaffold_referenced": check_scaffold_referenced,
    "no_new_test_failures": check_no_new_test_failures,
}


# ============================================================================
# Run all gates
# ============================================================================

def run_all_gates(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Ejecuta todos los quality gates."""
    results = []
    blocking_failures = []
    warnings = []

    for gate in QUALITY_GATES:
        check_fn = GATE_CHECKS.get(gate["check"])
        if not check_fn:
            results.append({"gate": gate["id"], "name": gate["name"], "passed": False, "reason": "check function not found"})
            continue

        result = check_fn(repo_root, flowid)
        result["gate"] = gate["id"]
        result["name"] = gate["name"]
        result["description"] = gate["description"]
        result["blocking"] = gate["blocking"]
        results.append(result)

        if not result["passed"]:
            if gate["blocking"]:
                blocking_failures.append(result)
            else:
                warnings.append(result)

    overall_pass = len(blocking_failures) == 0
    return {
        "forcequalitygates": "V1",
        "schema_version": "3.2.0",
        "flowid": flowid,
        "generated_at": now_iso(),
        "total_gates": len(QUALITY_GATES),
        "gates_passed": sum(1 for r in results if r["passed"]),
        "gates_failed": sum(1 for r in results if not r["passed"]),
        "blocking_failures": len(blocking_failures),
        "warnings": len(warnings),
        "overall_pass": overall_pass,
        "verdict": "PASS — agente puede avanzar" if overall_pass else f"BLOCKED — {len(blocking_failures)} gate(s) bloqueantes",
        "results": results,
        "blocking_details": blocking_failures,
        "warning_details": warnings,
    }


def gates_state_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "QUALITY-GATES-STATE.yaml"


def reset_gates(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Reset gates bloqueados (despues de fix)."""
    p = gates_state_path(repo_root, flowid)
    if p.exists():
        p.unlink()
    return {"success": True, "flowid": flowid, "message": "Gates reseteados — re-ejecutar check"}


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    argv = sys.argv[1:]
    action = "check"
    known = {"check", "check-one", "list", "reset"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if action == "list":
        gates = [{"id": g["id"], "name": g["name"], "description": g["description"], "blocking": g["blocking"]} for g in QUALITY_GATES]
        print(json.dumps({"success": True, "total": len(gates), "gates": gates}, indent=2))
        return 0

    if not flowid and action != "list":
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
        return 2

    if action == "check":
        result = run_all_gates(repo_root, flowid)
        # Persist state
        write_yaml(gates_state_path(repo_root, flowid), result)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2, default=str))
        return 0 if result["overall_pass"] else 1

    elif action == "check-one":
        gate_name = args.get("gate", "")
        if not gate_name:
            print(json.dumps({"success": False, "error": "Falta --gate"}, indent=2))
            return 2

        gate = next((g for g in QUALITY_GATES if g["name"] == gate_name or g["id"] == gate_name), None)
        if not gate:
            print(json.dumps({"success": False, "error": f"Gate {gate_name} no encontrado"}, indent=2))
            return 1

        check_fn = GATE_CHECKS.get(gate["check"])
        if not check_fn:
            print(json.dumps({"success": False, "error": f"Check {gate['check']} no implementado"}, indent=2))
            return 1

        result = check_fn(repo_root, flowid)
        result["gate"] = gate["id"]
        result["name"] = gate["name"]
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1

    elif action == "reset":
        result = reset_gates(repo_root, flowid)
        print(json.dumps(result, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

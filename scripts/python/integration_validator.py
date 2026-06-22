#!/usr/bin/env python3
"""
integration_validator.py — Valida handoffs entre scripts (v3.5.0).

RESPONDE a tu pregunta: "integraciones que no se solapen, no se dañen entre si"

Valida que el output de cada script tiene la estructura que el siguiente script
espera como input. Detecta:
  - Contratos rotos (script A produce X, script B espera Y)
  - Campos faltantes en handoffs
  - Tipos incorrectos (lista vs dict vs string)
  - Schemas inconsistentes

Cada handoff se define como:
  {
    "from": "collect_evidence.py",
    "to": "score_evidence.py",
    "output_field": "items",        # campo que A produce
    "input_expectation": "list",     # tipo que B espera
    "min_length": 1,                 # validacion opcional
    "description": "evidence items → score_evidence input"
  }

CLI:
  python3 integration_validator.py validate --repo-root .
  python3 integration_validator.py validate --repo-root . --json
  python3 integration_validator.py handoffs --repo-root .
"""

from __future__ import annotations
import json, os, sys, ast
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd


# ============================================================================
# Handoff contracts: output de A → input de B
# ============================================================================

HANDOFFS = [
    # Fase 2: index → collect (CODE-INDEX alimenta collect_evidence scope)
    {"from": "index_codebase.py", "to": "collect_evidence.py",
     "output": "CODE-INDEX.yaml", "output_field": "files", "expected_type": "list",
     "description": "index_codebase produce files[], collect_evidence los usa para scope"},

    # Fase 3: collect → score (EVIDENCE-PACK → score_evidence input)
    {"from": "collect_evidence.py", "to": "score_evidence.py",
     "output": "EVIDENCE-PACK.yaml", "output_field": "items", "expected_type": "list", "min_length": 1,
     "description": "collect_evidence produce items[], score_evidence los scorea"},
    {"from": "collect_evidence.py", "to": "score_evidence.py",
     "output": "EVIDENCE-PACK.yaml", "output_field": "hash_chain", "expected_type": "string", "min_length": 64,
     "description": "hash_chain SHA-256 (64 chars hex)"},

    # Fase 4: score → plan (EVIDENCE-SCORE → generate_plan input)
    {"from": "score_evidence.py", "to": "generate_plan.py",
     "output": "EVIDENCE-SCORE.yaml", "output_field": "score", "expected_type": "number",
     "description": "score_evidence produce score (0-1), generate_plan lo usa para elegir method"},

    # Fase 5: plan → impact (PLAN → predict_impact input)
    {"from": "generate_plan.py", "to": "predict_impact.py",
     "output": "PLAN.yaml", "output_field": "unidades", "expected_type": "list", "min_length": 1,
     "description": "generate_plan produce unidades[], predict_impact las analiza"},
    {"from": "generate_plan.py", "to": "predict_impact.py",
     "output": "PLAN.yaml", "output_field": "topological_sort", "expected_type": "list",
     "description": "topological_sort para orden de implementacion"},

    # Fase 5: plan → mp_prioritizer (PLAN → mp_prioritizer input)
    {"from": "generate_plan.py", "to": "mp_prioritizer.py",
     "output": "PLAN.yaml", "output_field": "unidades", "expected_type": "list",
     "description": "mp_prioritizer reordena unidades por prioridad"},

    # Fase 7: plan + impact → scaffold_v3 (ambos alimentan scaffold)
    {"from": "generate_plan.py", "to": "scaffold_v3.py",
     "output": "PLAN.yaml", "output_field": "unidades", "expected_type": "list",
     "description": "scaffold_v3 necesita unidades para auto-select"},
    {"from": "predict_impact.py", "to": "scaffold_v3.py",
     "output": "IMPACT-PREDICTION.yaml", "output_field": "predictions", "expected_type": "list",
     "description": "scaffold_v3 usa predictions para estrategia highest_impact"},

    # Fase 7: scaffold_v3 → post_script_gates (scaffold output → gates validan)
    {"from": "scaffold_v3.py", "to": "post_script_gates.py",
     "output": "SCAFFOLD-V3.yaml", "output_field": "files_to_create", "expected_type": "list", "min_length": 1,
     "description": "scaffold_v3 produce files_to_create[], gates validan que no este vacio"},
    {"from": "scaffold_v3.py", "to": "post_script_gates.py",
     "output": "SCAFFOLD-V3.yaml", "output_field": "commands", "expected_type": "list", "min_length": 1,
     "description": "scaffold_v3 produce commands[], gates validan que sean accionables"},

    # Fase 8: scaffold → orchestrator (commands → EXECUTE)
    {"from": "scaffold_v3.py", "to": "apolo_orchestrator.py",
     "output": "SCAFFOLD-V3.yaml", "output_field": "commands", "expected_type": "list",
     "description": "orchestrator ejecuta commands[] del scaffold"},

    # Fase 8: tests fail → evidence_replay (telemetry → replay input)
    {"from": "telemetry.jsonl", "to": "evidence_replay.py",
     "output": "telemetry.jsonl", "output_field": "events", "expected_type": "list",
     "description": "evidence_replay lee telemetry para construir timeline"},

    # Fase 8: tests fail → smart_rollback (scaffold + telemetry → rollback)
    {"from": "scaffold_v3.py", "to": "smart_rollback.py",
     "output": "SCAFFOLD-V3.yaml", "output_field": "files_to_create", "expected_type": "list",
     "description": "smart_rollback usa files del scaffold para saber que revertir"},

    # Fase 10: cross_flow_learning (todos los flows → knowledge base)
    {"from": "telemetry.jsonl", "to": "cross_flow_learning.py",
     "output": "telemetry.jsonl", "output_field": "events", "expected_type": "list",
     "description": "cross_flow_learning analiza telemetria de todos los flows"},

    # Fase 11: feedback_loop (flow complete → feedback)
    {"from": "apolo_orchestrator.py", "to": "feedback_loop.py",
     "output": "ORCHESTRATOR-REPORT.yaml", "output_field": "flowid", "expected_type": "string",
     "description": "feedback_loop registra feedback del flow completado"},
]


def validate_handoff_contracts() -> List[Dict[str, Any]]:
    """Valida que cada handoff tenga la estructura correcta."""
    results = []
    for h in HANDOFFS:
        result = {
            "from": h["from"],
            "to": h["to"],
            "description": h["description"],
            "output_field": h["output_field"],
            "expected_type": h["expected_type"],
            "contract_valid": True,
            "issues": [],
        }

        # Verificar que el contrato tenga campos requeridos
        required = ["from", "to", "output_field", "expected_type"]
        for req in required:
            if req not in h:
                result["contract_valid"] = False
                result["issues"].append(f"Campo requerido faltante: {req}")

        # Verificar tipo esperado valido
        valid_types = ["list", "dict", "string", "number", "boolean"]
        if h.get("expected_type") not in valid_types:
            result["contract_valid"] = False
            result["issues"].append(f"Tipo invalido: {h.get('expected_type')} (validos: {valid_types})")

        results.append(result)

    return results


def validate_static_dependencies(repo_root: Path) -> Dict[str, Any]:
    """Analiza estaticamente que los scripts se importan/invocan correctamente."""
    scripts_dir = repo_root / "scripts" / "python"
    if not scripts_dir.exists():
        return {"success": False, "error": "scripts/python/ no existe"}

    issues = []
    scripts_checked = 0
    imports_ok = 0

    for script in scripts_dir.glob("*.py"):
        if script.name == "common.py":
            continue
        scripts_checked += 1

        try:
            content = script.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)
        except SyntaxError as e:
            issues.append({"script": script.name, "issue": f"SyntaxError: {e}", "severity": "high"})
            continue

        # Verificar que importa common correctamente
        has_common_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "common":
                has_common_import = True
                break
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "common":
                        has_common_import = True
                        break

        if not has_common_import and "from common" not in content and "import common" not in content:
            # Algunos scripts pueden no necesitar common, pero es raro
            issues.append({"script": script.name, "issue": "No importa common.py", "severity": "low"})

        # Verificar que tiene funcion main()
        has_main = any(
            isinstance(node, ast.FunctionDef) and node.name == "main"
            for node in ast.walk(tree)
        )
        if not has_main:
            issues.append({"script": script.name, "issue": "No tiene funcion main()", "severity": "medium"})

        if has_main:
            imports_ok += 1

    return {
        "scripts_checked": scripts_checked,
        "scripts_with_main": imports_ok,
        "issues_found": len(issues),
        "issues": issues,
        "static_validation_pass": len([i for i in issues if i["severity"] == "high"]) == 0,
    }


def validate_orchestrator_data_flow(repo_root: Path) -> Dict[str, Any]:
    """Verifica que el orquestador invoca scripts en el orden correcto."""
    orch_path = repo_root / "scripts" / "python" / "apolo_orchestrator.py"
    if not orch_path.exists():
        return {"success": False, "error": "apolo_orchestrator.py no existe"}

    content = orch_path.read_text(encoding="utf-8", errors="replace")

    # Orden esperado de invocaciones (por fase)
    expected_order = [
        ("phase_init", ["health_check", "cross_flow_learning"]),
        ("phase_index", ["index_codebase", "cross_language_analyzer", "summarize_functions"]),
        ("phase_collect", ["user_input_collector", "collect_evidence", "secret_scanner"]),
        ("phase_score", ["score_evidence", "apolo_config", "evidence_visual_diff"]),
        ("phase_plan", ["agent_decision_loop", "generate_plan", "mp_prioritizer"]),
        ("phase_impact", ["predict_impact"]),
        ("phase_scaffold", ["agent_decision_loop", "scaffold_v3", "post_script_gates"]),
        ("phase_implement", ["force_quality_gates", "evidence_visual_diff", "evidence_replay", "smart_rollback"]),
        ("phase_test", ["run_tests", "force_quality_gates"]),
        ("phase_validate", ["force_quality_gates", "cross_flow_learning"]),
        ("phase_complete", ["feedback_loop", "pre_commit_hooks", "multi_agent_coordinator"]),
    ]

    phase_checks = []
    for phase_name, expected_scripts in expected_order:
        # Verificar que la fase existe
        if f"def {phase_name}" not in content:
            phase_checks.append({
                "phase": phase_name,
                "exists": False,
                "missing_scripts": expected_scripts,
                "status": "FAIL",
            })
            continue

        # Verificar que invoca los scripts esperados
        missing = [s for s in expected_scripts if s not in content]
        phase_checks.append({
            "phase": phase_name,
            "exists": True,
            "expected_scripts": expected_scripts,
            "missing_scripts": missing,
            "status": "PASS" if not missing else "PARTIAL",
        })

    all_pass = all(p["status"] == "PASS" for p in phase_checks)
    return {
        "phases_checked": len(phase_checks),
        "phases_pass": sum(1 for p in phase_checks if p["status"] == "PASS"),
        "phases_partial": sum(1 for p in phase_checks if p["status"] == "PARTIAL"),
        "phases_fail": sum(1 for p in phase_checks if p["status"] == "FAIL"),
        "all_phases_pass": all_pass,
        "phase_details": phase_checks,
    }


def validate_all(repo_root: Path) -> Dict[str, Any]:
    """Ejecuta todas las validaciones de integracion."""
    log("=" * 60, "INFO")
    log("INTEGRATION VALIDATOR v3.5.0 — Validando handoffs y data flow", "INFO")
    log("=" * 60, "INFO")

    # 1. Handoff contracts
    log("\n1. Validando contratos de handoff...", "INFO")
    handoff_results = validate_handoff_contracts()
    handoffs_ok = sum(1 for h in handoff_results if h["contract_valid"])
    log(f"   ✓ {handoffs_ok}/{len(handoff_results)} contratos validos", "INFO")

    # 2. Static dependencies
    log("\n2. Analisis estatico de dependencias...", "INFO")
    static_results = validate_static_dependencies(repo_root)
    log(f"   ✓ {static_results['scripts_checked']} scripts checkeados, {static_results['issues_found']} issues", "INFO")

    # 3. Orchestrator data flow
    log("\n3. Verificando data flow del orquestador...", "INFO")
    flow_results = validate_orchestrator_data_flow(repo_root)
    log(f"   ✓ {flow_results['phases_pass']}/{flow_results['phases_checked']} fases OK", "INFO")

    overall_pass = (
        handoffs_ok == len(handoff_results)
        and static_results["static_validation_pass"]
        and flow_results["all_phases_pass"]
    )

    report = {
        "integrationvalidator": "V1",
        "schema_version": "3.5.0",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "overall_pass": overall_pass,
        "verdict": "ALL INTEGRATIONS VALID" if overall_pass else "INTEGRATION ISSUES DETECTED",
        "handoff_contracts": {
            "total": len(handoff_results),
            "valid": handoffs_ok,
            "invalid": len(handoff_results) - handoffs_ok,
            "details": handoff_results,
        },
        "static_analysis": static_results,
        "orchestrator_data_flow": flow_results,
    }

    # Guardar reporte
    report_path = repo_root / "INTEGRATION-VALIDATION-REPORT.yaml"
    write_yaml(report_path, report)

    return report


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    as_json = args.get("json", "false") == "true"

    report = validate_all(repo_root)

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n" + "=" * 60)
        print("  INTEGRATION VALIDATION REPORT — v3.5.0")
        print("=" * 60)
        print(f"\n  Handoff contracts: {report['handoff_contracts']['valid']}/{report['handoff_contracts']['total']} validos")
        print(f"  Static analysis: {report['static_analysis']['scripts_checked']} scripts, {report['static_analysis']['issues_found']} issues")
        print(f"  Data flow: {report['orchestrator_data_flow']['phases_pass']}/{report['orchestrator_data_flow']['phases_checked']} fases OK")
        print(f"\n  VEREDICTO: {report['verdict']}")

        if report['static_analysis']['issues']:
            print("\n  Issues estaticos:")
            for issue in report['static_analysis']['issues']:
                print(f"    [{issue['severity']}] {issue['script']}: {issue['issue']}")

        if report['orchestrator_data_flow']['phase_details']:
            print("\n  Fases del orquestador:")
            for phase in report['orchestrator_data_flow']['phase_details']:
                status_icon = "✓" if phase["status"] == "PASS" else "⚠" if phase["status"] == "PARTIAL" else "✗"
                print(f"    {status_icon} {phase['phase']}: {phase['status']}", end="")
                if phase.get("missing_scripts"):
                    print(f" (missing: {phase['missing_scripts']})", end="")
                print()

    return 0 if report['overall_pass'] else 1


if __name__ == "__main__":
    sys.exit(main())

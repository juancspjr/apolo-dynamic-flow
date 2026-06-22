#!/usr/bin/env python3
"""
script_classifier.py — Clasifica scripts del repo en funcionales vs testeo (v3.5.2).

DIRECTIVA 4: "Analiza de forma automatica los 67 scripts del repositorio.
Descarta por completo aquellos que pertenezcan a suites de pruebas o
validaciones temporales del mismo sistema. Identifica los scripts funcionales
nativos de apolo-dynamic-flow."

Clasifica cada script en:
  - FUNCTIONAL: script nativo de apolo-dynamic-flow, invocable por el orquestador
  - TEST_INTERNAL: script de testeo del propio sistema (tests/test_*.py)
  - UTILITY: script de utilidad (install, migrate, serve_panel)
  - DEPRECATED: script obsoleto o temporal

Genera SCRIPT-CLASSIFICATION.yaml con la clasificacion completa.

CLI:
  python3 script_classifier.py classify --repo-root .
  python3 script_classifier.py functional --repo-root .
  python3 script_classifier.py stats --repo-root .
"""

from __future__ import annotations
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


# Scripts que son de testeo del propio sistema (NO se invocan en produccion)
TEST_PATTERNS = [
    r"^test_.*\.py$",
    r"^run_all_tests\.py$",
    r".*_test\.py$",
    r"^smoke_.*\.py$",
    r"^verify_.*\.py$",
]

# Scripts de utilidad (instalacion, migracion, no del flujo operativo)
UTILITY_SCRIPTS = {
    "install_deps.py",
    "serve_panel.py",
    "migrar.py",
    "fix_*.py",
}

# Scripts funcionales nativos del orquestador (ya integrados)
ORCHESTRATOR_INTEGRATED = {
    "common.py",
    "apolo_orchestrator.py",
    "index_codebase.py",
    "collect_evidence.py",
    "score_evidence.py",
    "generate_plan.py",
    "predict_impact.py",
    "scaffold_impl.py",
    "scaffold_v3.py",
    "cross_language_analyzer.py",
    "summarize_functions.py",
    "code_quality.py",
    "test_coverage.py",
    "lsp_integration.py",
    "vulnerability_scanner.py",
    "code_smells.py",
    "full_audit.py",
    "self_healing.py",
    "generate_tests.py",
    "semantic_search.py",
    "refactor_engine.py",
    "llm_bridge.py",
    "code_generator.py",
    "doc_generator.py",
    "project_templates.py",
    "onboarding.py",
    "github_actions.py",
    "secret_scanner.py",
    "absorb_external_skills.py",
    "absorb_mcp.py",
    "validate_artifact.py",
    "context_query.py",
    "registry_recommend.py",
    "health_check.py",
    "telemetry_aggregator.py",
    "inspect_tools.py",
    "rollback.py",
    "run_tests.py",
    "feedback_loop.py",
    "interactive_docs.py",
    "debug_mode.py",
    "integration_validation.py",
    "hooks_validator.py",
    "auto_hooks.py",
    "post_script_gates.py",
    "apolo_config.py",
    "evidence_visual_diff.py",
    "evidence_replay.py",
    "cross_flow_learning.py",
    "agent_decision_loop.py",
    "script_generator.py",
    "force_quality_gates.py",
    "user_input_collector.py",
    "multi_agent_coordinator.py",
    "smart_rollback.py",
    "mp_prioritizer.py",
    "pre_commit_hooks.py",
    "flow_verifier.py",
    "integration_validator.py",
    "data_flow_validator.py",
    "agent_honesty_enforcer.py",
    "static_analyzer.py",
    "agent_escape_hatch.py",
    "guided_recovery.py",
    "self_healing_loop.py",
    "script_classifier.py",
    "script_dynamic_invoker.py",
}


def classify_script(script_path: Path) -> Dict[str, Any]:
    """Clasifica un script Python."""
    name = script_path.name

    # 1. Es de testeo?
    for pattern in TEST_PATTERNS:
        if re.match(pattern, name):
            return {
                "script": name,
                "classification": "TEST_INTERNAL",
                "reason": f"Match patron de test: {pattern}",
                "invocable_by_orchestrator": False,
            }

    # 2. Es de utilidad?
    if name in UTILITY_SCRIPTS or name.startswith("fix_") or name.startswith("migrar"):
        return {
            "script": name,
            "classification": "UTILITY",
            "reason": "Script de utilidad (instalacion/migracion)",
            "invocable_by_orchestrator": False,
        }

    # 3. Es funcional nativo?
    if name in ORCHESTRATOR_INTEGRATED:
        # Verificar si ya esta integrado en el orquestador
        orch_path = script_path.parent / "apolo_orchestrator.py"
        in_orchestrator = False
        if orch_path.exists():
            content = orch_path.read_text(encoding="utf-8", errors="replace")
            in_orchestrator = name in content

        return {
            "script": name,
            "classification": "FUNCTIONAL",
            "reason": "Script funcional nativo de apolo-dynamic-flow",
            "invocable_by_orchestrator": True,
            "in_orchestrator": in_orchestrator,
        }

    # 4. Analizar contenido para clasificar
    try:
        content = script_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content)
    except Exception:
        return {
            "script": name,
            "classification": "UNKNOWN",
            "reason": "No se pudo analizar",
            "invocable_by_orchestrator": False,
        }

    # Verificar si tiene main() y importa common
    has_main = any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in ast.walk(tree))
    has_common = "from common" in content or "import common" in content

    if has_main and has_common:
        return {
            "script": name,
            "classification": "FUNCTIONAL_UNINTEGRATED",
            "reason": "Script funcional pero NO integrado en orquestador",
            "invocable_by_orchestrator": True,
            "in_orchestrator": False,
            "recommendation": "Considerar integrar en orquestador o invocar dinamicamente",
        }

    return {
        "script": name,
        "classification": "UNKNOWN",
        "reason": "No cumple patrones conocidos",
        "invocable_by_orchestrator": False,
    }


def classify_all_scripts(repo_root: Path) -> Dict[str, Any]:
    """Clasifica todos los scripts Python del repo."""
    scripts_dir = repo_root / "scripts" / "python"
    if not scripts_dir.exists():
        return {"success": False, "error": "scripts/python/ no existe"}

    classifications = []
    for script_path in sorted(scripts_dir.glob("*.py")):
        if script_path.name == "__init__.py":
            continue
        result = classify_script(script_path)
        classifications.append(result)

    # Stats
    by_class = {}
    for c in classifications:
        cls = c["classification"]
        by_class[cls] = by_class.get(cls, 0) + 1

    functional = [c for c in classifications if c["classification"] in ("FUNCTIONAL", "FUNCTIONAL_UNINTEGRATED")]
    test_internal = [c for c in classifications if c["classification"] == "TEST_INTERNAL"]
    utility = [c for c in classifications if c["classification"] == "UTILITY"]

    report = {
        "scriptclassification": "V1",
        "schema_version": "3.5.2",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "total_scripts": len(classifications),
        "by_class": by_class,
        "functional_scripts": [c["script"] for c in functional],
        "test_internal_scripts": [c["script"] for c in test_internal],
        "utility_scripts": [c["script"] for c in utility],
        "functional_count": len(functional),
        "test_internal_count": len(test_internal),
        "utility_count": len(utility),
        "unintegrated_functional": [c["script"] for c in functional if not c.get("in_orchestrator", False)],
        "classifications": classifications,
        "verdict": f"{len(functional)} funcionales, {len(test_internal)} test interno (descartados), {len(utility)} utilidad",
    }

    # Guardar
    output_path = repo_root / ".opencode" / "apolo-dynamic" / "SCRIPT-CLASSIFICATION.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(output_path, report)

    return report


def get_functional_scripts(repo_root: Path) -> List[str]:
    """Retorna solo los scripts funcionales (no test, no utility)."""
    report = classify_all_scripts(repo_root)
    return report.get("functional_scripts", [])


def get_stats(repo_root: Path) -> Dict[str, Any]:
    """Stats de clasificacion."""
    report = classify_all_scripts(repo_root)
    return {
        "success": True,
        "total": report["total_scripts"],
        "functional": report["functional_count"],
        "test_internal": report["test_internal_count"],
        "utility": report["utility_count"],
        "unintegrated": len(report.get("unintegrated_functional", [])),
        "verdict": report["verdict"],
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "classify"
    known = {"classify", "functional", "stats"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "classify":
        r = classify_all_scripts(repo_root)
        print(json.dumps({
            "success": True,
            "total": r["total_scripts"],
            "functional": r["functional_count"],
            "test_internal": r["test_internal_count"],
            "utility": r["utility_count"],
            "verdict": r["verdict"],
            "unintegrated_functional": r.get("unintegrated_functional", []),
        }, ensure_ascii=False, indent=2))
        return 0
    elif action == "functional":
        scripts = get_functional_scripts(repo_root)
        print(json.dumps({"success": True, "total": len(scripts), "scripts": scripts}, indent=2))
        return 0
    elif action == "stats":
        r = get_stats(repo_root)
        print(json.dumps(r, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

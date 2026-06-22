#!/usr/bin/env python3
"""
script_dynamic_invoker.py — Invoca scripts funcionales dinamicamente (v3.5.2).

DIRECTIVA 4: "invocalos de manera dinamica segun las demandas del flujo
operativo. permite al agente Si determinas que un script en un uso no cubre
la necesidad especifica del proceso que esta ejecutando permitele que
autogenere un script adaptado en tiempo real para resolver la parte que
cubre en cuanto al producto que esta tratando"

El orquestador puede invocar CUALQUIER script funcional dinamicamente:
  1. Clasifica los scripts disponibles (script_classifier)
  2. Si un script funcional cubre la necesidad → lo invoca
  3. Si ningun script cubre la necesidad → script_generator crea uno nuevo
  4. El script generado se registra y se invoca

IMPORTANTE: el agente NO puede crear scripts que modifiquen el FLUJO del
orquestador. Solo puede crear scripts para resolver necesidades del PRODUCTO
(analizar codigo, generar artefactos, validar datos). El flujo se mantiene
determinista.

CLI:
  python3 script_dynamic_invoker.py invoke --repo-root . --task "analizar seguridad de src/"
  python3 script_dynamic_invoker.py invoke --repo-root . --task "validar schema de config.yaml"
  python3 script_dynamic_invoker.py available --repo-root .
  python3 script_dynamic_invoker.py generate-and-invoke --repo-root . --task "..." --name "custom_validator"
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd


# ============================================================================
# Task → Script matching
# ============================================================================

# Map de tareas comunes a scripts funcionales
TASK_SCRIPT_MAP = {
    # Analisis de codigo
    "analizar seguridad": "vulnerability_scanner.py",
    "security scan": "vulnerability_scanner.py",
    "cve": "vulnerability_scanner.py",
    "code quality": "code_quality.py",
    "calidad codigo": "code_quality.py",
    "code smells": "code_smells.py",
    "dead code": "code_smells.py",
    "complejidad": "code_smells.py",
    "coverage": "test_coverage.py",
    "cobertura": "test_coverage.py",
    "lsp": "lsp_integration.py",
    "find references": "lsp_integration.py",
    "cross language": "cross_language_analyzer.py",
    "cross-lenguaje": "cross_language_analyzer.py",
    "resumir funciones": "summarize_functions.py",
    "function summary": "summarize_functions.py",
    "index codebase": "index_codebase.py",
    "indexar": "index_codebase.py",
    "audit": "full_audit.py",
    "auditoria": "full_audit.py",

    # Generacion
    "generar codigo": "code_generator.py",
    "generate code": "code_generator.py",
    "generar doc": "doc_generator.py",
    "documentation": "doc_generator.py",
    "plantilla": "project_templates.py",
    "template": "project_templates.py",
    "onboarding": "onboarding.py",
    "github actions": "github_actions.py",
    "ci/cd": "github_actions.py",

    # Inteligencia
    "self-heal": "self_healing.py",
    "self healing": "self_healing.py",
    "generar tests": "generate_tests.py",
    "generate tests": "generate_tests.py",
    "semantic search": "semantic_search.py",
    "busqueda semantica": "semantic_search.py",
    "refactor": "refactor_engine.py",
    "refactoring": "refactor_engine.py",
    "llm": "llm_bridge.py",

    # Evidencia
    "collect evidence": "collect_evidence.py",
    "recolectar evidencia": "collect_evidence.py",
    "score evidence": "score_evidence.py",
    "scorear": "score_evidence.py",
    "predict impact": "predict_impact.py",
    "impacto": "predict_impact.py",
    "scaffold": "scaffold_v3.py",
    "andamio": "scaffold_v3.py",

    # Seguridad
    "secret scan": "secret_scanner.py",
    "escanear secretos": "secret_scanner.py",
    "validate artifact": "validate_artifact.py",
    "validar artifact": "validate_artifact.py",
    "absorb skills": "absorb_external_skills.py",
    "absorb mcp": "absorb_mcp.py",

    # Flow
    "context query": "context_query.py",
    "recommend tool": "registry_recommend.py",
    "health check": "health_check.py",
    "feedback": "feedback_loop.py",
    "interactive docs": "interactive_docs.py",
    "debug mode": "debug_mode.py",

    # Validadores
    "validate integration": "integration_validator.py",
    "validate dataflow": "data_flow_validator.py",
    "verify honesty": "agent_honesty_enforcer.py",
    "static analyze": "static_analyzer.py",
    "verify flow": "flow_verifier.py",

    # Recovery
    "escape hatch": "agent_escape_hatch.py",
    "guided recovery": "guided_recovery.py",
    "self-heal loop": "self_healing_loop.py",

    # Multi-agent
    "multi-agent": "multi_agent_coordinator.py",
    "rollback": "smart_rollback.py",
    "prioritize": "mp_prioritizer.py",
    "pre-commit": "pre_commit_hooks.py",
}


def find_script_for_task(task: str, repo_root: Path) -> Optional[str]:
    """Encuentra el script funcional que cubre una tarea."""
    task_lower = task.lower()

    # 1. Buscar por keyword en el mapa
    for keyword, script in TASK_SCRIPT_MAP.items():
        if keyword in task_lower:
            script_path = repo_root / "scripts" / "python" / script
            if script_path.exists():
                return script

    # 2. Buscar por similitud de nombre
    try:
        from script_classifier import get_functional_scripts
        functional = get_functional_scripts(repo_root)
        task_words = set(task_lower.replace("_", " ").split())
        for script in functional:
            script_words = set(script.replace(".py", "").replace("_", " ").split())
            overlap = task_words & script_words
            if len(overlap) >= 2:
                return script
    except Exception:
        pass

    return None


def invoke_script(script_name: str, args: List[str], repo_root: Path, timeout: int = 60) -> Dict[str, Any]:
    """Invoca un script funcional dinamicamente."""
    script_path = repo_root / "scripts" / "python" / script_name
    if not script_path.exists():
        return {"success": False, "error": f"Script no encontrado: {script_name}"}

    cmd = ["python3", str(script_path)] + args
    start = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=timeout,
        )
        duration_ms = int((time.time() - start) * 1000)
        parsed = None
        if result.stdout:
            try:
                idx = result.stdout.find("{")
                if idx >= 0:
                    parsed = json.loads(result.stdout[idx:])
            except json.JSONDecodeError:
                pass
        return {
            "success": result.returncode == 0,
            "script": script_name,
            "exit_code": result.returncode,
            "duration_ms": duration_ms,
            "stdout": result.stdout[:1000],
            "stderr": result.stderr[:500] if result.stderr else "",
            "parsed": parsed,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "script": script_name, "error": "timeout"}
    except Exception as e:
        return {"success": False, "script": script_name, "error": str(e)}


def generate_and_invoke(
    task: str,
    repo_root: Path,
    script_name: str = "",
    description: str = "",
    inputs: str = "",
    outputs: str = "",
    timeout: int = 60,
) -> Dict[str, Any]:
    """Si ningun script cubre la tarea, genera uno nuevo y lo invoca."""
    # Generar nombre si no se proporciona
    if not script_name:
        # Generar nombre desde task
        words = re.findall(r"[a-z]+", task.lower())
        script_name = "_".join(words[:3]) if words else "custom_task"

    # Verificar que no existe ya
    script_path = repo_root / "scripts" / "python" / f"{script_name}.py"
    if script_path.exists():
        log(f"Script {script_name}.py ya existe, invocando directamente", "INFO")
        return invoke_script(f"{script_name}.py", ["--repo-root", str(repo_root)], repo_root, timeout)

    # Generar script nuevo via script_generator
    if not description:
        description = f"Script autogenerado para tarea: {task}"

    gen_result = invoke_script("script_generator.py", [
        "create", "--repo-root", str(repo_root),
        "--name", script_name,
        "--description", description,
        "--purpose", "dynamic_task",
        "--inputs", inputs or "repo_root:path",
        "--outputs", outputs or "result:dict",
    ], repo_root, 15)

    if not gen_result.get("success"):
        return {
            "success": False,
            "error": f"No se pudo generar script para tarea: {task}",
            "gen_result": gen_result,
        }

    # Invocar el script recien creado
    log(f"Script {script_name}.py generado, invocando...", "INFO")
    return invoke_script(f"{script_name}.py", ["--repo-root", str(repo_root)], repo_root, timeout)


def invoke_for_task(
    task: str,
    repo_root: Path,
    args: List[str] = None,
    generate_if_missing: bool = True,
) -> Dict[str, Any]:
    """Invoca el script que cubre una tarea, o genera uno nuevo si no existe."""
    args = args or ["--repo-root", str(repo_root)]

    # 1. Buscar script existente
    script = find_script_for_task(task, repo_root)

    if script:
        log(f"Script encontrado para '{task}': {script}", "INFO")
        return invoke_script(script, args, repo_root)

    # 2. No se encontro — generar o reportar
    if generate_if_missing:
        log(f"No se encontro script para '{task}', generando uno nuevo...", "WARN")
        return generate_and_invoke(task, repo_root)

    return {
        "success": False,
        "error": f"No se encontro script funcional para tarea: {task}",
        "task": task,
        "hint": "Usa --generate-if-missing para autogenerar",
    }


def list_available_scripts(repo_root: Path) -> Dict[str, Any]:
    """Lista todos los scripts funcionales disponibles."""
    try:
        from script_classifier import get_functional_scripts
        functional = get_functional_scripts(repo_root)
    except Exception:
        functional = []

    return {
        "success": True,
        "total_functional": len(functional),
        "scripts": functional,
        "task_map_entries": len(TASK_SCRIPT_MAP),
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "invoke"
    known = {"invoke", "available", "generate-and-invoke"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "invoke":
        task = args.get("task", "")
        if not task:
            print(json.dumps({"success": False, "error": "Falta --task"}, indent=2)); return 2
        generate = args.get("generate-if-missing", "true") == "true"
        r = invoke_for_task(task, repo_root, generate_if_missing=generate)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0 if r.get("success") else 1
    elif action == "available":
        r = list_available_scripts(repo_root)
        print(json.dumps(r, indent=2))
        return 0
    elif action == "generate-and-invoke":
        task = args.get("task", "")
        name = args.get("name", "")
        if not task:
            print(json.dumps({"success": False, "error": "Falta --task"}, indent=2)); return 2
        r = generate_and_invoke(task, repo_root, name)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0 if r.get("success") else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

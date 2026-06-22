#!/usr/bin/env python3
"""
apolo_natural.py — UN solo comando en lenguaje natural (v3.5.3).

RESPONDE a tu indicacion: "un solo comando que inteligentemente llame los
comandos que el usuario solicita segun su requerimiento o cuando el mismo
agente lo necesite"

El usuario escribe en lenguaje natural lo que quiere, y el sistema:
  1. Analiza la intencion (NLP simple por keywords)
  2. Identifica que comando/combinacion de comandos ejecutar
  3. Lo ejecuta automaticamente
  4. Si necesita input del usuario, lo pide
  5. Si necesita multiples pasos, los encadena

Ejemplos de lo que el usuario puede escribir:
  apolo "implementar JWT auth en plugin/index.ts"
  apolo "analizar seguridad del codigo"
  apolo "verificar que todo funciona"
  apolo "auditoria completa"
  apolo "que codigo no tiene tests"
  apolo "crear un script para validar schemas"
  apolo "diagnosticar el error TypeError en full_audit"
  apolo "revertir los cambios que fallaron"
  apolo "que fase sigue"

El sistema entiende la intencion y ejecuta el comando correcto.

CLI:
  python3 apolo_natural.py --repo-root . --request "..."
  python3 apolo_natural.py --repo-root . --request "..." --flowid APOLO-X
"""

from __future__ import annotations
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, flow_dir


# ============================================================================
# Intent detection — maps natural language to commands
# ============================================================================

INTENT_MAP = {
    # === FLOW LIFECYCLE ===
    "run_flow": {
        "keywords": ["implementar", "ejecutar", "correr", "run", "hacer", "crear feature", "desarrollar", "construir", "empezar"],
        "description": "Ejecutar el ciclo completo de orquestacion",
        "command": "orchestrator",
        "needs_flowid": True,
        "needs_goal": True,
    },
    "continue_flow": {
        "keywords": ["continuar", "seguir", "continue", "reanudar", "proseguir"],
        "description": "Continuar el ciclo pausado",
        "command": "orchestrator_continue",
        "needs_flowid": True,
    },
    "status_flow": {
        "keywords": ["estado", "status", "como va", "que paso", "donde estoy", "avance"],
        "description": "Ver estado del flow",
        "command": "orchestrator_status",
        "needs_flowid": True,
    },

    # === ANALYSIS ===
    "security_scan": {
        "keywords": ["seguridad", "security", "vulnerabilidad", "cve", "vulnerabilities"],
        "description": "Escaneo de vulnerabilidades CVE",
        "command": "vulnerability_scanner",
    },
    "code_quality": {
        "keywords": ["calidad", "quality", "lint", "bandit", "eslint"],
        "description": "Analisis de calidad de codigo",
        "command": "code_quality",
    },
    "code_smells": {
        "keywords": ["smells", "code smells", "dead code", "complejidad", "god class", "long method"],
        "description": "Deteccion de code smells y dead code",
        "command": "code_smells",
    },
    "test_coverage": {
        "keywords": ["coverage", "cobertura", "que no tiene tests", "sin tests", "untested"],
        "description": "Coverage por simbolo",
        "command": "test_coverage",
    },
    "full_audit": {
        "keywords": ["auditoria", "audit", "revision completa", "full audit", "chequeo completo"],
        "description": "Auditoria completa (11 pasos, score A-F)",
        "command": "full_audit",
    },
    "index_codebase": {
        "keywords": ["indexar", "index", "ast", "parsear codigo", "simbolos"],
        "description": "Indexar codebase (AST)",
        "command": "index_codebase",
    },

    # === VALIDATION ===
    "verify_all": {
        "keywords": ["verificar que todo funciona", "verificar todo", "check todo", "validar todo"],
        "description": "Verificar que TODOS los super poderes funcionan",
        "command": "flow_verifier",
    },
    "validate_integration": {
        "keywords": ["handoffs", "contratos", "integracion", "integration"],
        "description": "Validar handoffs entre scripts",
        "command": "integration_validator",
    },
    "validate_dataflow": {
        "keywords": ["data flow", "flujo de datos", "artefactos", "dataflow"],
        "description": "Verificar que data fluye por donde debe",
        "command": "data_flow_validator",
    },
    "verify_honesty": {
        "keywords": ["honestidad", "honesty", "claims", "evidencia"],
        "description": "Verificar que claims del agente tienen evidencia",
        "command": "agent_honesty_enforcer",
    },
    "static_analyze": {
        "keywords": ["dependencias", "circular", "static analyze", "grafo"],
        "description": "Analisis estatico de dependencias",
        "command": "static_analyzer",
    },
    "hooks_check": {
        "keywords": ["hooks", "opencode", "plugin cargado", "mcp"],
        "description": "Verificar mecanismo de hooks de OpenCode",
        "command": "hooks_validator",
    },

    # === RECOVERY ===
    "diagnose_error": {
        "keywords": ["diagnosticar", "error", "fallo", "TypeError", "KeyError", "ModuleNotFound", "crash"],
        "description": "Diagnosticar un error y proponer fix",
        "command": "guided_recovery",
        "needs_error": True,
    },
    "rollback": {
        "keywords": ["revertir", "rollback", "deshacer", "volver atras"],
        "description": "Revertir SOLO los archivos que fallaron",
        "command": "smart_rollback",
        "needs_flowid": True,
    },
    "escape_hatch": {
        "keywords": ["escape", "saltar", "skip", "alternativa", "salida"],
        "description": "Ofrecer salidas guiadas",
        "command": "agent_escape_hatch",
        "needs_flowid": True,
    },
    "self_heal": {
        "keywords": ["auto-reparar", "self-heal", "reparar sistema", "fix sistema"],
        "description": "Auto-reparar fallas del sistema",
        "command": "self_healing_loop",
    },

    # === GENERATION ===
    "gen_script": {
        "keywords": ["crear script", "generar script", "nuevo script", "script nuevo"],
        "description": "Generar un script nuevo",
        "command": "script_generator",
        "needs_name": True,
    },
    "gen_code": {
        "keywords": ["generar codigo", "generate code", "crear funcion", "crear clase"],
        "description": "Generacion de codigo",
        "command": "code_generator",
    },
    "gen_tests": {
        "keywords": ["generar tests", "create tests", "escribir tests", "test skeleton"],
        "description": "Generacion automatica de tests",
        "command": "generate_tests",
    },
    "gen_docs": {
        "keywords": ["documentacion", "docs", "readme", "docstring"],
        "description": "Generacion de documentacion",
        "command": "doc_generator",
    },

    # === INTELLIGENCE ===
    "semantic_search": {
        "keywords": ["buscar", "search", "encontrar", "donde esta", "semantic"],
        "description": "Busqueda semantica en el codigo",
        "command": "semantic_search",
        "needs_query": True,
    },
    "refactor": {
        "keywords": ["refactor", "refactoring", "mejorar codigo", "clean code"],
        "description": "Refactoring automatico",
        "command": "refactor_engine",
    },
    "context_query": {
        "keywords": ["que fase sigue", "contexto", "que hacer", "next phase", "siguiente"],
        "description": "Context query (17 tipos de preguntas)",
        "command": "context_query",
    },
    "cross_flow": {
        "keywords": ["cross-flow", "flows anteriores", "aprender de flows", "recommend"],
        "description": "Cross-flow learning",
        "command": "cross_flow_learning",
    },

    # === EVIDENCE ===
    "visual_diff": {
        "keywords": ["diff", "baseline", "roto", "post-fix", "comparar", "visual"],
        "description": "Evidence visual diff",
        "command": "evidence_visual_diff",
        "needs_flowid": True,
    },
    "evidence_replay": {
        "keywords": ["replay", "reproducir bug", "paso a paso", "timeline", "bug replay"],
        "description": "Replay de bug paso a paso",
        "command": "evidence_replay",
        "needs_flowid": True,
    },

    # === CONFIG ===
    "config_show": {
        "keywords": ["config", "configuracion", "thresholds", "ajustes"],
        "description": "Ver configuracion",
        "command": "apolo_config_show",
    },
    "classify_scripts": {
        "keywords": ["clasificar scripts", "cuantos scripts", "script count"],
        "description": "Clasificar scripts del repo",
        "command": "script_classifier",
    },

    # === TEST ===
    "run_tests": {
        "keywords": ["correr tests", "ejecutar tests", "pasar tests", "test suite"],
        "description": "Ejecutar test suite",
        "command": "run_tests",
    },
    "full_test": {
        "keywords": ["test exhaustivo", "full test", "todos los tests", "apolo-full-test"],
        "description": "Test exhaustivo completo",
        "command": "full_test",
    },
}


def detect_intent(request: str) -> Tuple[str, Dict]:
    """Detecta la intencion del request en lenguaje natural."""
    request_lower = request.lower()
    scores: Dict[str, int] = {}

    for intent_name, config in INTENT_MAP.items():
        score = 0
        for keyword in config["keywords"]:
            if keyword in request_lower:
                score += len(keyword)  # mas largo = mas especifico
        if score > 0:
            scores[intent_name] = score

    if not scores:
        return "unknown", {"request": request, "message": "No se reconocio la intencion"}

    # Mejor match
    best_intent = max(scores, key=scores.get)
    return best_intent, INTENT_MAP[best_intent]


def execute_intent(
    intent_name: str,
    config: Dict,
    repo_root: Path,
    flowid: str = "",
    goal: str = "",
    request: str = "",
) -> Dict[str, Any]:
    """Ejecuta el comando correspondiente a la intencion detectada."""
    command = config["command"]
    log(f"Intent: {intent_name} → {command}", "INFO")
    log(f"Descripcion: {config['description']}", "INFO")

    # === FLOW LIFECYCLE ===
    if command == "orchestrator":
        if not goal:
            goal = request  # usar el request como goal
        if not flowid:
            flowid = f"APOLO-{now_iso().replace('-', '').replace(':', '')[:8]}-NATURAL"
        return _run_orchestrator(repo_root, flowid, goal)

    elif command == "orchestrator_continue":
        return _run_script(repo_root, "apolo_orchestrator.py", ["continue", "--repo-root", str(repo_root), "--flowid", flowid])

    elif command == "orchestrator_status":
        return _run_script(repo_root, "apolo_orchestrator.py", ["status", "--repo-root", str(repo_root), "--flowid", flowid])

    # === ANALYSIS ===
    elif command == "vulnerability_scanner":
        return _run_script(repo_root, "vulnerability_scanner.py", ["--repo-root", str(repo_root)])

    elif command == "code_quality":
        return _run_script(repo_root, "code_quality.py", ["--repo-root", str(repo_root)])

    elif command == "code_smells":
        ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
        return _run_script(repo_root, "code_smells.py", ["--repo-root", str(repo_root), "--code-index", str(ci_path)])

    elif command == "test_coverage":
        ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
        return _run_script(repo_root, "test_coverage.py", ["--repo-root", str(repo_root), "--code-index", str(ci_path)])

    elif command == "full_audit":
        return _run_script(repo_root, "full_audit.py", ["--repo-root", str(repo_root)])

    elif command == "index_codebase":
        ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
        return _run_script(repo_root, "index_codebase.py", ["--repo-root", str(repo_root), "--output", str(ci_path)])

    # === VALIDATION ===
    elif command == "flow_verifier":
        return _run_script(repo_root, "flow_verifier.py", ["verify", "--repo-root", str(repo_root)])

    elif command == "integration_validator":
        return _run_script(repo_root, "integration_validator.py", ["validate", "--repo-root", str(repo_root)])

    elif command == "data_flow_validator":
        return _run_script(repo_root, "data_flow_validator.py", ["validate", "--repo-root", str(repo_root), "--flowid", flowid or "DEFAULT"])

    elif command == "agent_honesty_enforcer":
        return _run_script(repo_root, "agent_honesty_enforcer.py", ["verify", "--repo-root", str(repo_root), "--flowid", flowid or "DEFAULT"])

    elif command == "static_analyzer":
        return _run_script(repo_root, "static_analyzer.py", ["analyze", "--repo-root", str(repo_root)])

    elif command == "hooks_validator":
        return _run_script(repo_root, "hooks_validator.py", ["--repo-root", str(repo_root)])

    # === RECOVERY ===
    elif command == "guided_recovery":
        # Extraer error del request
        error = request
        return _run_script(repo_root, "guided_recovery.py", ["diagnose", "--repo-root", str(repo_root), "--flowid", flowid or "DEFAULT", "--error", error])

    elif command == "smart_rollback":
        return _run_script(repo_root, "smart_rollback.py", ["rollback", "--repo-root", str(repo_root), "--flowid", flowid, "--dry-run", "true"])

    elif command == "agent_escape_hatch":
        return _run_script(repo_root, "agent_escape_hatch.py", ["offer", "--repo-root", str(repo_root), "--flowid", flowid, "--phase", "unknown", "--reason", request])

    elif command == "self_healing_loop":
        return _run_script(repo_root, "self_healing_loop.py", ["check", "--repo-root", str(repo_root), "--flowid", flowid or "DEFAULT"])

    # === GENERATION ===
    elif command == "script_generator":
        # Extraer nombre del request
        name_match = re.search(r"(?:llamado|named|nombre)\s+(\w+)", request, re.IGNORECASE)
        name = name_match.group(1) if name_match else "custom_script"
        return _run_script(repo_root, "script_generator.py", ["create", "--repo-root", str(repo_root), "--name", name, "--description", request, "--purpose", "dynamic"])

    elif command == "code_generator":
        return _run_script(repo_root, "code_generator.py", ["--language", "python", "--type", "function", "--name", "custom", "--args", "x"])

    elif command == "generate_tests":
        ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
        return _run_script(repo_root, "generate_tests.py", ["--repo-root", str(repo_root), "--code-index", str(ci_path), "--output", "/tmp/gen_tests/"])

    elif command == "doc_generator":
        return _run_script(repo_root, "doc_generator.py", ["--repo-root", str(repo_root), "--type", "readme-section", "--section", "overview"])

    # === INTELLIGENCE ===
    elif command == "semantic_search":
        return _run_script(repo_root, "semantic_search.py", ["--repo-root", str(repo_root), "--query", request, "--top", "5"])

    elif command == "refactor_engine":
        ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
        return _run_script(repo_root, "refactor_engine.py", ["--repo-root", str(repo_root), "--code-index", str(ci_path)])

    elif command == "context_query":
        return _run_script(repo_root, "context_query.py", ["--flowid", flowid or "DEFAULT", "--repo-root", str(repo_root), "--phase", "unknown", "--question", request])

    elif command == "cross_flow_learning":
        return _run_script(repo_root, "cross_flow_learning.py", ["recommend", "--repo-root", str(repo_root), "--flowid", flowid or "DEFAULT", "--phase", "unknown"])

    # === EVIDENCE ===
    elif command == "evidence_visual_diff":
        return _run_script(repo_root, "evidence_visual_diff.py", ["compare", "--repo-root", str(repo_root), "--flowid", flowid])

    elif command == "evidence_replay":
        return _run_script(repo_root, "evidence_replay.py", ["bug", "--repo-root", str(repo_root), "--flowid", flowid])

    # === CONFIG ===
    elif command == "apolo_config_show":
        return _run_script(repo_root, "apolo_config.py", ["show", "--repo-root", str(repo_root)])

    elif command == "script_classifier":
        return _run_script(repo_root, "script_classifier.py", ["classify", "--repo-root", str(repo_root)])

    # === TEST ===
    elif command == "run_tests":
        return _run_script(repo_root, "run_tests.py", ["--repo-root", str(repo_root), "--trigger", "manual"])

    elif command == "full_test":
        log("Ejecutando: bash apolo-full-test.sh", "INFO")
        code, out, err = run_cmd(["bash", "apolo-full-test.sh"], cwd=str(repo_root), timeout=300)
        return {"success": code == 0, "stdout": out[:2000], "stderr": err[:500]}

    return {"success": False, "error": f"Comando no implementado: {command}"}


def _run_script(repo_root: Path, script_name: str, args: List[str]) -> Dict[str, Any]:
    """Ejecuta un script Python y retorna resultado."""
    script_path = repo_root / "scripts" / "python" / script_name
    if not script_path.exists():
        return {"success": False, "error": f"Script no encontrado: {script_name}"}

    cmd = ["python3", str(script_path)] + args
    start = time.time()
    try:
        result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, timeout=120)
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
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500] if result.stderr else "",
            "parsed": parsed,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _run_orchestrator(repo_root: Path, flowid: str, goal: str) -> Dict[str, Any]:
    """Ejecuta el orquestador completo."""
    return _run_script(repo_root, "apolo_orchestrator.py", [
        "run", "--repo-root", str(repo_root),
        "--flowid", flowid, "--goal", goal, "--yes",
    ])


def process_natural_request(
    repo_root: Path,
    request: str,
    flowid: str = "",
) -> Dict[str, Any]:
    """Procesa un request en lenguaje natural y ejecuta el comando correcto."""
    log("=" * 60, "INFO")
    log("APOLONATURAL — UN comando en lenguaje natural", "INFO")
    log("=" * 60, "INFO")
    log(f"Request: {request}", "INFO")
    log(f"FlowID: {flowid or '(auto-generar si needed)'}", "INFO")

    # 1. Detectar intencion
    intent_name, config = detect_intent(request)

    if intent_name == "unknown":
        # Si no se reconoce, intentar con script_dynamic_invoker
        log("Intencion no reconocida, intentando invocacion dinamica...", "WARN")
        return _run_script(repo_root, "script_dynamic_invoker.py", [
            "invoke", "--repo-root", str(repo_root), "--task", request,
        ])

    log(f"Intencion detectada: {intent_name}", "INFO")
    log(f"Ejecutando: {config['description']}", "INFO")

    # 2. Ejecutar comando
    result = execute_intent(intent_name, config, repo_root, flowid, request=request, goal=request)

    # 3. Si necesita flowid y no se proporciono, informar
    if config.get("needs_flowid") and not flowid:
        result["warning"] = "Este comando necesita --flowid. Usa: apolo \"...\" --flowid APOLO-X"

    return {
        "success": result.get("success", False),
        "request": request,
        "intent": intent_name,
        "command": config["command"],
        "description": config["description"],
        "result": result,
        "processed_at": now_iso(),
    }


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    request = args.get("request", "") or args.get("goal", "")
    flowid = args.get("flowid", "")

    if not request:
        print(json.dumps({
            "success": False,
            "error": "Falta --request (lo que quieres en lenguaje natural)",
            "examples": [
                'apolo "implementar JWT auth en plugin/index.ts"',
                'apolo "analizar seguridad del codigo"',
                'apolo "verificar que todo funciona"',
                'apolo "auditoria completa"',
                'apolo "que codigo no tiene tests"',
                'apolo "diagnosticar el error TypeError"',
                'apolo "revertir los cambios que fallaron"',
                'apolo "que fase sigue"',
            ],
        }, ensure_ascii=False, indent=2))
        return 2

    result = process_natural_request(repo_root, request, flowid)

    # Output legible
    print("\n" + "=" * 60)
    print(f"  APOLONATURAL — Resultado")
    print("=" * 60)
    print(f"  Request: {request[:80]}")
    print(f"  Intent:  {result.get('intent', '?')}")
    print(f"  Command: {result.get('command', '?')}")
    print(f"  Success: {result.get('success', False)}")
    if result.get("result", {}).get("stdout"):
        print(f"\n  Output:\n{result['result']['stdout'][:500]}")
    print("=" * 60)

    # JSON para machine consumption
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
guided_recovery.py — Sistema ayuda al agente a recuperar de errores (v3.5.1).

RESPONDE a tu indicacion: "el sistema ayuda pero ya hemos visto muchos pequeñas
fallas yo insisto seguir revisando"

Cuando un script falla, el sistema no solo reporta el error — ANALIZA la causa
y propone SOLUCIONES CONCRETAS que el agente puede ejecutar. Como un mecánico
que diagnostica y repara.

Tipos de recovery:
  1. MISSING_DEPENDENCY: falta instalar paquete → proponer pip install
  2. YAML_PARSE_ERROR: YAML invalido → mostrar linea exacta + fix
  3. FILE_NOT_FOUND: archivo falta → proponer crear o buscar alternativa
  4. PERMISSION_DENIED: permisos → proponer chmod
  5. TIMEOUT: script lento → proponer aumentar timeout o dividir tarea
  6. SCHEMA_MISMATCH: YAML no cumple schema → mostrar campos faltantes
  7. CIRCULAR_DEPENDENCY: dependencia circular → proponer orden alternativo
  8. TEST_FAILURE: test fallo → mostrar diff + evidence_replay + smart_rollback

CLI:
  python3 guided_recovery.py diagnose --flowid X --error "TypeError: ..."
  python3 guided_recovery.py diagnose --flowid X --script collect_evidence.py --exit-code 2
  python3 guided_recovery.py suggest --error-type yaml_parse_error --details "line 5: ..."
"""

from __future__ import annotations
import json, os, re, sys, traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


RECOVERY_PATTERNS = {
    "missing_dependency": {
        "patterns": [r"ModuleNotFoundError: No module named '(\w+)'", r"ImportError: (\w+)"],
        "diagnosis": "Falta instalar una dependencia Python",
        "fix_template": "pip3 install --user {module}",
        "fix_description": "Instalar el modulo faltante",
    },
    "yaml_parse_error": {
        "patterns": [r"yaml\.YAMLError", r"YAMLError", r"while parsing", r"expected <block end>"],
        "diagnosis": "Error de sintaxis en archivo YAML",
        "fix_template": "Revisar sintaxis YAML en {file}. Usar: python3 -c 'import yaml; yaml.safe_load(open(\"{file}\"))'",
        "fix_description": "Corregir sintaxis YAML",
    },
    "file_not_found": {
        "patterns": [r"FileNotFoundError: \[Errno 2\] No such file or directory: '([^']+)'", r"No such file or directory: '([^']+)'"],
        "diagnosis": "Archivo no encontrado",
        "fix_template": "Crear archivo {file} o verificar path. Buscar: find . -name '{basename}'",
        "fix_description": "Crear o localizar el archivo",
    },
    "permission_denied": {
        "patterns": [r"PermissionError: \[Errno 13\] Permission denied: '([^']+)'"],
        "diagnosis": "Permisos insuficientes",
        "fix_template": "chmod +x {file} o chmod 644 {file}",
        "fix_description": "Corregir permisos",
    },
    "timeout": {
        "patterns": [r"TimeoutExpired", r"timed? ?out"],
        "diagnosis": "El script tardo demasiado",
        "fix_template": "Aumentar timeout en apolo_config.yaml (bfs.max_depth, circuit_breaker.max_loops_per_phase) o dividir la tarea en partes mas pequenas",
        "fix_description": "Aumentar timeout o dividir tarea",
    },
    "type_error": {
        "patterns": [r"TypeError: (.+)", r"'<' not supported between instances of '(\w+)' and '(\w+)'"],
        "diagnosis": "Error de tipo — se esperaba un tipo pero se recibio otro",
        "fix_template": "Verificar tipos en el input. Usar _as_count() para normalizar int|list|dict → int. Revisar post_script_gates para validar contenido YAML",
        "fix_description": "Normalizar tipos de datos",
    },
    "key_error": {
        "patterns": [r"KeyError: '(\w+)'"],
        "diagnosis": "Falta una key en el YAML — el contrato se rompio",
        "fix_template": "El script espera la key '{key}' pero no esta en el YAML. Verificar que el script anterior (handoff) la produzca. Usar: post_script_gates check --script <anterior> --output <yaml>",
        "fix_description": "Reparar contrato de handoff",
    },
    "test_failure": {
        "patterns": [r"FAILED", r"AssertionError", r"assert "],
        "diagnosis": "Tests fallaron",
        "fix_template": "1. evidence_replay bug --flowid {flowid} (analizar causa) 2. smart_rollback rollback --flowid {flowid} (revertir cambios) 3. evidence_visual_diff compare --flowid {flowid} (ver que cambio)",
        "fix_description": "Analizar, revertir y comparar",
    },
}


def diagnose_error(repo_root: Path, flowid: str, error: str, script: str = "", exit_code: int = -1) -> Dict[str, Any]:
    """Diagnostica un error y propone recovery."""
    diagnoses = []

    for error_type, config in RECOVERY_PATTERNS.items():
        for pattern in config["patterns"]:
            match = re.search(pattern, error, re.IGNORECASE)
            if match:
                fix = config["fix_template"]
                # Reemplazar placeholders
                groups = match.groups()
                if groups:
                    fix = fix.replace("{module}", groups[0] if len(groups) > 0 else "")
                    fix = fix.replace("{file}", groups[0] if len(groups) > 0 else "")
                    fix = fix.replace("{basename}", Path(groups[0]).name if len(groups) > 0 else "")
                    fix = fix.replace("{key}", groups[0] if len(groups) > 0 else "")
                fix = fix.replace("{flowid}", flowid)

                diagnoses.append({
                    "error_type": error_type,
                    "diagnosis": config["diagnosis"],
                    "matched_pattern": pattern,
                    "fix_command": fix,
                    "fix_description": config["fix_description"],
                    "confidence": "high" if len(groups) > 0 else "medium",
                })

    if not diagnoses:
        # Diagnostico generico
        diagnoses.append({
            "error_type": "unknown",
            "diagnosis": "Error no reconocido — analisis manual necesario",
            "fix_command": f"1. Revisar error completo 2. Buscar en telemetry: evidence_replay bug --flowid {flowid} 3. Si es sistema: usar agent_escape_hatch offer --flowid {flowid} --phase unknown --reason 'error no reconocido'",
            "fix_description": "Analisis manual + tools de diagnostico",
            "confidence": "low",
        })

    # Log del diagnostico
    log_entry = {
        "at": now_iso(),
        "flowid": flowid,
        "script": script,
        "exit_code": exit_code,
        "error_snippet": error[:500],
        "diagnoses_count": len(diagnoses),
    }
    _log_diagnosis(repo_root, flowid, log_entry)

    return {
        "success": True,
        "flowid": flowid,
        "script": script,
        "exit_code": exit_code,
        "error_snippet": error[:500],
        "diagnoses": diagnoses,
        "recommended_fix": diagnoses[0] if diagnoses else None,
        "message": f"Diagnostico completo: {len(diagnoses)} posible(s) causa(s). Fix recomendado: {diagnoses[0]['fix_description'] if diagnoses else 'manual'}",
    }


def _log_diagnosis(repo_root: Path, flowid: str, entry: Dict) -> None:
    p = flow_dir(repo_root, flowid) / "RECOVERY-DIAGNOSES.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def suggest_recovery(error_type: str, details: str = "") -> Dict[str, Any]:
    """Sugiere recovery para un tipo de error conocido."""
    if error_type not in RECOVERY_PATTERNS:
        return {"success": False, "error": f"Tipo de error no reconocido: {error_type}. Validos: {list(RECOVERY_PATTERNS.keys())}"}

    config = RECOVERY_PATTERNS[error_type]
    return {
        "success": True,
        "error_type": error_type,
        "diagnosis": config["diagnosis"],
        "fix_command": config["fix_template"].replace("{details}", details),
        "fix_description": config["fix_description"],
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "diagnose"
    known = {"diagnose", "suggest"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if action == "diagnose":
        error = args.get("error", "")
        script = args.get("script", "")
        exit_code = int(args.get("exit-code", "-1"))
        if not error:
            print(json.dumps({"success": False, "error": "Falta --error (mensaje de error)"}, indent=2)); return 2
        r = diagnose_error(repo_root, flowid, error, script, exit_code)
        print(json.dumps(r, ensure_ascii=False, indent=2)); return 0
    elif action == "suggest":
        error_type = args.get("error-type", "")
        details = args.get("details", "")
        r = suggest_recovery(error_type, details)
        print(json.dumps(r, ensure_ascii=False, indent=2)); return 0 if r["success"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

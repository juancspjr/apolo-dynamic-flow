#!/usr/bin/env python3
"""
validate_artifact.py — Validador de artefactos YAML/JSON contra schemas.

v2.3.0: usa `jsonschema` (hard dependency) para validación completa:
  - $ref, allOf, oneOf, anyOf
  - additionalProperties
  - patternProperties
  - format (date-time, etc.)
  - dependencies condicionales

Soporta 2 modos de schema:
  - JSON Schema draft-07 (archivos .json en schemas/json/)
  - Schemas YAML simplificados (archivos .yaml en schemas/) — convertidos a JSON Schema

Exit codes:
  0 = válido
  1 = inválido (errores)
  2 = error de ejecución (schema no encontrado, dependencia faltante, etc.)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Hard dependency (v2.3.0)
try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
except ImportError:
    print("[FATAL] jsonschema no instalado. Instalar con: pip3 install jsonschema", file=sys.stderr)
    print("        El validador minimalista fue eliminado en v2.3.0.", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).parent))
from common import log, parse_args, read_yaml


def load_schema(schema_path: Path) -> Dict[str, Any]:
    """Carga un schema desde .json o .yaml."""
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema no encontrado: {schema_path}")

    if schema_path.suffix == ".json":
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # YAML schema: convertir a JSON Schema
        schema = read_yaml(schema_path)
        if schema is None:
            raise ValueError(f"Schema YAML vacío o inválido: {schema_path}")
        # Asegurar que tiene $schema si no lo tiene
        if "$schema" not in schema:
            schema["$schema"] = "http://json-schema.org/draft-07/schema#"
        return schema


def validate(artifact: Any, schema: Dict[str, Any]) -> List[str]:
    """Valida un artifact contra un JSON Schema usando jsonschema.

    Returns lista de errores (vacía si es válido).
    """
    errors: List[str] = []

    # Crear validator con Draft7
    validator = Draft7Validator(schema)

    # Recopilar todos los errores
    for error in validator.iter_errors(artifact):
        # Formatear el path del error
        path = ".".join(str(p) for p in error.absolute_path) or "$"
        errors.append(f"{path}: {error.message}")

    return errors


def validate_artifact(artifact_path: Path, schema_path: Path) -> Dict[str, Any]:
    """Valida un artifact contra un schema. Retorna dict con resultados."""
    result = {
        "artifact": str(artifact_path),
        "schema": str(schema_path),
        "valid": False,
        "errors": [],
        "error_count": 0,
    }

    # Cargar artifact
    if not artifact_path.exists():
        result["errors"].append(f"Artifact no encontrado: {artifact_path}")
        result["error_count"] = 1
        return result

    if artifact_path.suffix == ".json":
        with open(artifact_path, "r", encoding="utf-8") as f:
            artifact = json.load(f)
    else:
        artifact = read_yaml(artifact_path)
        if artifact is None:
            result["errors"].append(f"Artifact YAML vacío o inválido: {artifact_path}")
            result["error_count"] = 1
            return result

    # Cargar schema
    try:
        schema = load_schema(schema_path)
    except Exception as e:
        result["errors"].append(f"Error cargando schema: {e}")
        result["error_count"] = 1
        return result

    # Validar
    errors = validate(artifact, schema)
    result["errors"] = errors
    result["error_count"] = len(errors)
    result["valid"] = len(errors) == 0

    return result


def main() -> int:
    args = parse_args(sys.argv[1:])
    artifact_p = args.get("artifact", "")
    schema_p = args.get("schema", "")
    as_json = args.get("json", "") == "json"

    if not artifact_p or not schema_p:
        log("--artifact y --schema requeridos", "ERROR")
        return 2

    result = validate_artifact(Path(artifact_p), Path(schema_p))

    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if result["valid"]:
            log(f"VALID: {artifact_p} cumple {schema_p}", "INFO")
        else:
            log(f"INVALID: {result['error_count']} errores", "ERROR")
            for e in result["errors"]:
                print(f"  - {e}", file=sys.stderr)

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())

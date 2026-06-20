#!/usr/bin/env python3
"""
validate_artifact.py — Validador de artefactos YAML contra schemas.

Sin jsonschema (dependencia externa). Implementa validación mínima:
  - required fields
  - type checking (object, array, string, integer, boolean, null)
  - enum
  - pattern (regex)
  - minItems / maxItems
  - minLength / maxLength
  - additionalProperties: false (warn only)

Exit codes:
  0 = válido
  1 = inválido (errores)
  2 = error de ejecución
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, parse_args, read_yaml


def validate_value(
    value: Any,
    schema: Dict[str, Any],
    path: str,
    errors: List[str],
) -> None:
    if not isinstance(schema, dict):
        return

    # type
    expected_type = schema.get("type")
    if expected_type:
        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "boolean": bool,
            "number": (int, float),
            "null": type(None),
        }
        py_type = type_map.get(expected_type)
        if py_type and not isinstance(value, py_type):
            errors.append(f"{path}: esperaba {expected_type}, obtuvo {type(value).__name__}")
            return

    # enum
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: valor {value!r} no está en enum {schema['enum']}")

    # pattern (strings)
    if "pattern" in schema and isinstance(value, str):
        if not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: valor {value!r} no cumple pattern {schema['pattern']!r}")

    # const
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: valor {value!r} != const {schema['const']!r}")

    # minLength / maxLength
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: string demasiado corta ({len(value)} < {schema['minLength']})")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: string demasiado larga ({len(value)} > {schema['maxLength']})")

    # minItems / maxItems
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: lista con {len(value)} < {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: lista con {len(value)} > {schema['maxItems']} items")

    # minimum / maximum
    if isinstance(value, (int, float)):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")

    # object: required + properties + additionalProperties
    if isinstance(value, dict) and expected_type == "object":
        required = schema.get("required", [])
        for r in required:
            if r not in value:
                errors.append(f"{path}.{r}: campo requerido faltante")
        props = schema.get("properties", {})
        for key, val in value.items():
            if key in props:
                validate_value(val, props[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: propiedad no permitida (additionalProperties=false)")

    # array: items
    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        for i, item in enumerate(value):
            validate_value(item, item_schema, f"{path}[{i}]", errors)


def validate(artifact: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    validate_value(artifact, schema, "$", errors)
    return errors


def main() -> int:
    args = parse_args(sys.argv[1:])
    artifact_p = args.get("artifact", "")
    schema_p = args.get("schema", "")

    if not artifact_p or not schema_p:
        log("--artifact y --schema requeridos", "ERROR")
        return 2

    artifact = read_yaml(Path(artifact_p))
    schema = read_yaml(Path(schema_p))
    if artifact is None:
        log(f"no se pudo leer artifact: {artifact_p}", "ERROR")
        return 2
    if schema is None:
        log(f"no se pudo leer schema: {schema_p}", "ERROR")
        return 2

    errors = validate(artifact, schema)
    if errors:
        log(f"INVALID: {len(errors)} errores", "ERROR")
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(json.dumps({"valid": False, "errors": errors}))
        return 1

    log(f"VALID: {artifact_p} cumple {schema_p}", "INFO")
    print(json.dumps({"valid": True, "errors": []}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

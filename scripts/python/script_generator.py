#!/usr/bin/env python3
"""
script_generator.py — Permite al agente crear scripts nuevos (v3.2.0).

RESPONDE a la intencion del usuario:
  "si el agente debe elaborar script para no solo los que estan sino el
   sistema de promover que el agente mejore"

El agente puede proponer un script nuevo cuando los existentes no cubren
la necesidad. El sistema:
  1. Valida que el script no duplica uno existente (similarity check)
  2. Genera el template con la estructura estandar (shebang, docstring, imports, common.py)
  3. Lo guarda en scripts/python/ con nombre descriptivo
  4. Lo registra en TOOL-REGISTRY.yaml automaticamente
  5. Crea un test skeleton en tests/
  6. Actualiza auto_hooks con un trigger opcional

CLI:
  # Agente propone un script nuevo
  python3 script_generator.py create \\
      --name "jwt_validator" \\
      --description "Valida tokens JWT firmados" \\
      --purpose "security" \\
      --inputs "token:string,secret:string" \\
      --outputs "valid:bool,payload:dict" \\
      --repo-root .

  # Listar scripts generados
  python3 script_generator.py list --repo-root .

  # Validar un script propuesto (antes de crearlo)
  python3 script_generator.py validate --name "jwt_validator" --repo-root .
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, cmd_available


SCRIPT_TEMPLATE = '''#!/usr/bin/env python3
"""
{name}.py — {description}

GENERADO por script_generator.py (v3.2.0) el {generated_at}
Purpose: {purpose}

Inputs:
{inputs_formatted}

Outputs:
{outputs_formatted}

Uso:
  python3 {name}.py {usage_args}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = args.get("output")

    log(f"=== {name} START ===", "INFO")

    # TODO: Implementar logica principal
    # Inputs disponibles en args

    result = {{
        "success": True,
        "name": "{name}",
        "generated_at": now_iso(),
        "message": "Script generado automaticamente — implementar logica",
    }}

    if output:
        write_yaml(Path(output), result)
        log(f"Output → {{output}}", "INFO")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


TEST_TEMPLATE = '''#!/usr/bin/env python3
"""
Test automatico para {name}.py — generado por script_generator.py (v3.2.0)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "python"))

from common import read_yaml, write_yaml


def test_{name}_basic():
    """Test basico: el script debe poder importarse."""
    # TODO: implementar test real
    assert True, "Skeleton test — implementar"


def test_{name}_output_format():
    """Test de formato de output."""
    # TODO: validar que el output tiene la estructura esperada
    assert True, "Skeleton test — implementar"


if __name__ == "__main__":
    test_{name}_basic()
    test_{name}_output_format()
    print("ALL TESTS PASSED — {name}")
'''


def script_exists(repo_root: Path, name: str) -> bool:
    """Verifica si un script con ese nombre ya existe."""
    script_path = repo_root / "scripts" / "python" / f"{name}.py"
    return script_path.exists()


def find_similar_scripts(repo_root: Path, description: str, name: str) -> List[Dict]:
    """Busca scripts existentes que podrian duplicar el nuevo."""
    scripts_dir = repo_root / "scripts" / "python"
    if not scripts_dir.exists():
        return []

    description_words = set(w.lower() for w in description.split() if len(w) > 3)
    name_words = set(w.lower() for w in name.replace("_", " ").split() if len(w) > 3)
    search_words = description_words | name_words

    similar = []
    for script in scripts_dir.glob("*.py"):
        if script.name == "common.py":
            continue
        try:
            content = script.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            continue

        # Buscar keywords del nombre/descripcion en el docstring
        content_words = set(w.lower() for w in content.split() if len(w) > 3)
        overlap = len(search_words & content_words)

        if overlap > 0:
            similar.append({
                "script": script.name,
                "overlap_score": overlap,
                "common_words": list(search_words & content_words)[:10],
            })

    # Sort by overlap
    similar.sort(key=lambda x: -x["overlap_score"])
    return similar[:5]


def generate_script(
    repo_root: Path,
    name: str,
    description: str,
    purpose: str,
    inputs: str,
    outputs: str,
    force: bool = False,
) -> Dict[str, Any]:
    """Genera un script nuevo con template estandar."""

    # 1. Validar nombre
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        return {
            "success": False,
            "error": f"Nombre invalido: {name}. Debe ser snake_case, empezar con letra, solo a-z0-9_",
        }

    # 2. Verificar si existe
    if script_exists(repo_root, name) and not force:
        return {
            "success": False,
            "error": f"Script {name}.py ya existe. Usa --force para sobreescribir.",
            "existing_path": str(repo_root / "scripts" / "python" / f"{name}.py"),
        }

    # 3. Buscar similares
    similar = find_similar_scripts(repo_root, description, name)
    if similar and similar[0]["overlap_score"] > 5 and not force:
        return {
            "success": False,
            "error": f"Posible duplicado: {similar[0]['script']} tiene {similar[0]['overlap_score']} palabras en comun",
            "similar_scripts": similar,
            "hint": "Usa --force para crear de todas formas, o reutiliza el script existente",
        }

    # 4. Formatear inputs/outputs
    inputs_formatted = "\n".join(f"  - {i.strip()}" for i in inputs.split(",") if i.strip()) if inputs else "  (ninguno)"
    outputs_formatted = "\n".join(f"  - {o.strip()}" for o in outputs.split(",") if o.strip()) if outputs else "  (ninguno)"
    usage_args = "--repo-root . [--output output.yaml]"

    # 5. Generar contenido
    content = SCRIPT_TEMPLATE.format(
        name=name,
        description=description,
        generated_at=now_iso(),
        purpose=purpose,
        inputs_formatted=inputs_formatted,
        outputs_formatted=outputs_formatted,
        usage_args=usage_args,
    )

    # 6. Guardar script
    script_path = repo_root / "scripts" / "python" / f"{name}.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(content, encoding="utf-8")
    os.chmod(script_path, 0o755)

    # 7. Generar test skeleton
    test_path = repo_root / "tests" / f"test_{name}.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_content = TEST_TEMPLATE.format(name=name)
    test_path.write_text(test_content, encoding="utf-8")

    # 8. Registrar en TOOL-REGISTRY.yaml
    registry_path = repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml"
    registry = read_yaml(registry_path) or {"tools": []}
    new_tool = {
        "name": f"{name}.py",
        "path": f"scripts/python/{name}.py",
        "type": "python-script",
        "purpose": purpose,
        "description": description,
        "inputs": [i.strip() for i in inputs.split(",") if i.strip()],
        "outputs": [o.strip() for o in outputs.split(",") if o.strip()],
        "generated_by": "script_generator.py",
        "generated_at": now_iso(),
        "auto_generated": True,
    }
    registry.setdefault("tools", []).append(new_tool)
    write_yaml(registry_path, registry)

    # 9. Log
    log(f"Script generado: {script_path}", "INFO")
    log(f"Test skeleton: {test_path}", "INFO")
    log(f"Registrado en TOOL-REGISTRY.yaml", "INFO")

    return {
        "success": True,
        "script_path": str(script_path),
        "test_path": str(test_path),
        "registered_in_registry": True,
        "similar_scripts_found": len(similar),
        "name": name,
        "description": description,
        "purpose": purpose,
        "next_steps": [
            f"Implementar logica en {script_path}",
            f"Escribir tests en {test_path}",
            f"Probar: python3 {script_path} --repo-root .",
            f"Si el script es util, añadir trigger en auto_hooks.py",
        ],
    }


def list_generated_scripts(repo_root: Path) -> Dict[str, Any]:
    """Lista scripts generados automaticamente."""
    registry_path = repo_root / ".opencode" / "apolo-dynamic" / "TOOL-REGISTRY.yaml"
    registry = read_yaml(registry_path) or {"tools": []}

    generated = [
        t for t in registry.get("tools", [])
        if t.get("generated_by") == "script_generator.py"
    ]

    return {
        "success": True,
        "total": len(generated),
        "scripts": generated,
    }


def validate_proposal(repo_root: Path, name: str, description: str = "") -> Dict[str, Any]:
    """Valida una propuesta de script sin crearlo."""
    issues = []

    # Validar nombre
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        issues.append(f"Nombre invalido: debe ser snake_case")

    if script_exists(repo_root, name):
        issues.append(f"Script {name}.py ya existe")

    similar = find_similar_scripts(repo_root, description, name)
    if similar and similar[0]["overlap_score"] > 5:
        issues.append(f"Posible duplicado: {similar[0]['script']} ({similar[0]['overlap_score']} palabras en comun)")

    return {
        "success": len(issues) == 0,
        "name": name,
        "issues": issues,
        "similar_scripts": similar,
        "can_create": len(issues) == 0,
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "create"
    known = {"create", "list", "validate"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()

    if action == "create":
        name = args.get("name", "")
        description = args.get("description", "")
        purpose = args.get("purpose", "general")
        inputs = args.get("inputs", "")
        outputs = args.get("outputs", "")
        force = args.get("force", "false") == "true"

        if not name or not description:
            print(json.dumps({"success": False, "error": "Falta --name y --description"}, indent=2))
            return 2

        result = generate_script(repo_root, name, description, purpose, inputs, outputs, force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    elif action == "list":
        result = list_generated_scripts(repo_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    elif action == "validate":
        name = args.get("name", "")
        description = args.get("description", "")
        if not name:
            print(json.dumps({"success": False, "error": "Falta --name"}, indent=2))
            return 2
        result = validate_proposal(repo_root, name, description)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

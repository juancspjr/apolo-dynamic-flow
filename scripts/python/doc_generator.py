#!/usr/bin/env python3
"""
doc_generator.py — Generación automática de documentación (v2.7.0).

Genera:
  - Docstrings para funciones/classes sin documentación
  - Secciones de README (instalación, uso, API)
  - API docs (OpenAPI/Swagger para REST, JSDoc para TS)
  - CHANGELOG entries desde git log

Si LLM disponible: genera documentación inteligente.
Si no: usa heurísticas deterministas (firmas, nombres, patrones).

Uso:
  python3 doc_generator.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml --type docstrings
  python3 doc_generator.py --repo-root . --type readme-section --section "Installation"
  python3 doc_generator.py --repo-root . --type api-docs
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd


def generate_python_docstring(name: str, args: List[str], return_type: str = "") -> str:
    """Genera docstring Python (Google style)."""
    doc = f'"""{name} function.'
    if args:
        doc += '\n\n'
        for arg in args:
            doc += f'    Args:\n        {arg}: Description of {arg}.\n'
    if return_type:
        doc += f'\n    Returns:\n        {return_type}: Description of return value.\n'
    doc += '\n    Raises:\n        NotImplementedError: If not yet implemented.\n'
    doc += '    """'
    return doc


def generate_jsdoc(name: str, args: List[str], return_type: str = "") -> str:
    """Genera JSDoc para TypeScript/JavaScript."""
    doc = '/**\n'
    doc += f' * {name} function.\n'
    if args:
        for arg in args:
            doc += f' * @param {{{arg}}} {arg} - Description.\n'
    if return_type:
        doc += f' * @returns {{{return_type}}} Description.\n'
    doc += ' */'
    return doc


def generate_go_doc(name: str, args: List[str]) -> str:
    """Genera comentario Go."""
    return f'// {name} processes the given inputs.\n// TODO: Add detailed documentation.'


def generate_rust_doc(name: str, args: List[str]) -> str:
    """Genera comentario Rust."""
    doc = f'/// {name} function.\n'
    if args:
        doc += '///\n'
        for arg in args:
            doc += f'/// # Arguments\n///\n/// * `{arg}` - Description\n'
    return doc


def generate_java_doc(name: str, args: List[str]) -> str:
    """Genera JavaDoc."""
    doc = '/**\n'
    doc += f' * {name} method.\n'
    if args:
        for arg in args:
            doc += f' * @param {arg} Description\n'
    doc += ' */'
    return doc


def generate_readme_section(section_type: str, project_name: str = "apolo-dynamic-flow") -> str:
    """Genera una sección de README."""
    sections = {
        "installation": f'''## Installation

```bash
git clone https://github.com/juancspjr/{project_name}.git
cd {project_name}
./install.sh
```

### Prerequisites

- Node.js >= 18
- Python >= 3.10
- PyYAML, jsonschema (auto-installed by install.sh)
''',
        "usage": f'''## Usage

```bash
# Initialize a flow
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-$(date +%Y%m%d)-MY-FLOW

# Absorb tools
bash scripts/bash/apolo-inspect.sh absorb --repo-root .

# Collect evidence
python3 scripts/python/collect_evidence.py --flowid APOLO-TEST --repo-root . --output evidence.yaml

# Generate plan
python3 scripts/python/generate_plan.py --flowid APOLO-TEST --evidence evidence.yaml --verdad verdad.yaml --output plan.yaml

# Run tests
python3 scripts/python/run_tests.py --flowid APOLO-TEST --trigger micro-change --kind unit --targets-json '["src/main.py"]'
```
''',
        "api": f'''## API Reference

### Core Tools

- `apolo.flow.init` — Initialize a new flow
- `apolo.flow.tick` — Execute one loop iteration
- `apolo.evidence.collect` — Collect evidence (hybrid mode)
- `apolo.plan.generate` — Generate dynamic plan (3 modes)
- `apolo.tests.run` — Run tests after changes
- `apolo.tools.absorb` — Absorb external tools
- `apolo.context.query` — Query system state
- `apolo.registry.recommend` — Recommend tools for task
- `apolo.health.check` — Health check with hot reload

### CLI

```bash
bash scripts/bash/apolo-inspect.sh <subcommand> [--flowid FLOW] [--repo-root PATH]
```
''',
        "contributing": f'''## Contributing

1. Fork the repo
2. Create branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -m 'Add my-feature'`
4. Push: `git push origin feature/my-feature`
5. Pull request

### Before PR

```bash
python3 tests/run_all_tests.py
npx tsc && node --test dist/tests/plugin.test.js
bash apolo-full-test.sh
```
''',
    }
    return sections.get(section_type, "")


def generate_api_docs(code_index: Dict, repo_root: Path) -> Dict[str, Any]:
    """Genera API docs desde el code index."""
    endpoints = []
    for f in code_index.get("files", []):
        path = f.get("path", "")
        full = repo_root / path
        if not full.exists():
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Detect REST endpoints
        for m in re.finditer(r'(?:GET|POST|PUT|DELETE|PATCH)\s+(/[a-zA-Z0-9/_-]+)', content):
            endpoints.append({
                "method": m.group(0).split()[0],
                "path": m.group(1),
                "file": path,
                "line": content[:m.start()].count("\n") + 1,
            })

    return {
        "apidocs": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "total_endpoints": len(endpoints),
        "endpoints": endpoints,
    }


def generate_changelog_entry(repo_root: Path) -> str:
    """Genera entrada de changelog desde git log."""
    code, out, _ = run_cmd(
        ["git", "log", "--oneline", "-10", "--pretty=format:%s"],
        cwd=repo_root,
        timeout=10,
    )
    if code != 0:
        return "Unable to generate changelog from git log."

    lines = out.strip().split("\n") if out.strip() else []
    entry = "### Recent Changes\n\n"
    for line in lines:
        entry += f"- {line}\n"
    return entry


def generate_docstrings_for_file(file_path: Path, language: str, use_llm: bool = True) -> List[Dict]:
    """Genera docstrings para funciones sin documentación en un archivo."""
    results = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return results

    if language == "py":
        # Find functions without docstrings
        lines = content.split("\n")
        for i, line in enumerate(lines):
            m = re.match(r'^\s*(?:def|async def)\s+(\w+)\s*\(([^)]*)\)', line)
            if not m:
                continue
            name = m.group(1)
            args_str = m.group(2).strip()
            args = [a.strip().split(":")[0].split("=")[0].strip() for a in args_str.split(",") if a.strip()]

            # Check if next line has docstring
            has_doc = False
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].strip().startswith('"""') or lines[j].strip().startswith("'''"):
                    has_doc = True
                    break
                if lines[j].strip() and not lines[j].strip().startswith("#"):
                    break

            if not has_doc:
                docstring = generate_python_docstring(name, args)
                results.append({
                    "file": str(file_path.name),
                    "function": name,
                    "line": i + 1,
                    "docstring": docstring,
                    "language": "python",
                })

    return results


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    doc_type = args.get("type", "docstrings")
    section = args.get("section", "installation")
    output = args.get("output", "")

    if doc_type == "readme-section":
        result = generate_readme_section(section)
        if output:
            Path(output).write_text(result, encoding="utf-8")
        print(result)
        return 0

    if doc_type == "api-docs":
        code_index = read_yaml(ci_path) or {}
        result = generate_api_docs(code_index, repo_root)
        if output:
            write_yaml(output, result)
        print(json.dumps({"success": True, "endpoints": result["total_endpoints"]}))
        return 0

    if doc_type == "changelog":
        result = generate_changelog_entry(repo_root)
        if output:
            Path(output).write_text(result, encoding="utf-8")
        print(result)
        return 0

    if doc_type == "docstrings":
        code_index = read_yaml(ci_path) or {}
        all_docs = []
        for f in code_index.get("files", []):
            path = repo_root / f.get("path", "")
            lang = f.get("language", "")
            if lang in ("py", "python"):
                docs = generate_docstrings_for_file(path, "py")
                all_docs.extend(docs)

        result = {
            "docstrings": "V1",
            "version": 1,
            "generated_at": now_iso(),
            "total_missing": len(all_docs),
            "docstrings": all_docs,
        }
        if output:
            write_yaml(output, result)
        print(json.dumps({"success": True, "missing_docstrings": len(all_docs)}))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

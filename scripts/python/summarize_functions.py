#!/usr/bin/env python3
"""
summarize_functions.py — Resumen automático de funciones (v2.6.6).

Genera un resumen de 1 línea para cada función del codebase.

Si LLM disponible: usa llm_bridge.analyze_code() para generar resúmenes inteligentes.
Si no: usa heurísticas deterministas:
  - Parsea docstrings
  - Analiza verbos en el nombre (get, set, create, delete, etc.)
  - Analiza return statements
  - Analiza funciones llamadas internamente
  - Genera: "Gets user by ID from database" o "Validates email format"

Uso:
  python3 summarize_functions.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


# ============================================================================
# Heuristic patterns
# ============================================================================

# Verb prefixes that indicate function purpose
VERB_PATTERNS = {
    "get": "Gets {object} from {source}",
    "set": "Sets {object} value",
    "create": "Creates a new {object}",
    "delete": "Deletes {object}",
    "remove": "Removes {object}",
    "update": "Updates {object}",
    "check": "Checks if {object} is valid",
    "validate": "Validates {object}",
    "parse": "Parses {object} from input",
    "format": "Formats {object} for output",
    "convert": "Converts {object} to target format",
    "load": "Loads {object} from source",
    "save": "Saves {object} to destination",
    "find": "Finds {object} by criteria",
    "search": "Searches for {object}",
    "filter": "Filters {object} by condition",
    "sort": "Sorts {object} by key",
    "merge": "Merges {object} items",
    "split": "Splits {object} into parts",
    "join": "Joins {object} items together",
    "count": "Counts {object} items",
    "has": "Checks if has {object}",
    "is": "Checks if {object} is true",
    "can": "Checks if can {object}",
    "should": "Checks if should {object}",
    "init": "Initializes {object}",
    "start": "Starts {object} process",
    "stop": "Stops {object} process",
    "run": "Runs {object} operation",
    "execute": "Executes {object} command",
    "apply": "Applies {object} transformation",
    "build": "Builds {object} structure",
    "generate": "Generates {object} output",
    "extract": "Extracts {object} from data",
    "transform": "Transforms {object} data",
    "compute": "Computes {object} value",
    "calculate": "Calculates {object} result",
    "read": "Reads {object} from source",
    "write": "Writes {object} to destination",
    "send": "Sends {object} to target",
    "receive": "Receives {object} from source",
    "fetch": "Fetches {object} from remote",
    "process": "Processes {object} data",
    "handle": "Handles {object} event",
    "render": "Renders {object} view",
    "display": "Displays {object} to user",
    "log": "Logs {object} message",
    "print": "Prints {object} to output",
    "scan": "Scans {object} for patterns",
    "detect": "Detects {object} in data",
    "resolve": "Resolves {object} reference",
    "register": "Registers {object} handler",
    "absorb": "Absorbs {object} from external source",
    "collect": "Collects {object} evidence",
    "score": "Scores {object} quality",
    "predict": "Predicts {object} impact",
    "scaffold": "Scaffolds {object} structure",
    "recommend": "Recommends {object} option",
    "verify": "Verifies {object} integrity",
    "rollback": "Rolls back {object} changes",
}


def extract_docstring_summary(content: str, func_line: int) -> Optional[str]:
    """Extrae la primera línea de un docstring después de la función."""
    lines = content.split("\n")
    start = max(0, func_line - 1)
    
    for i in range(start + 1, min(start + 10, len(lines))):
        line = lines[i].strip()
        if not line:
            continue
        # Python docstring
        if line.startswith('"""') or line.startswith("'''"):
            text = line[3:].strip().rstrip('"\'')
            if text:
                return text[:120]
            # Multi-line docstring
            for j in range(i + 1, min(i + 20, len(lines))):
                text = lines[j].strip().rstrip('"""\'')
                if text:
                    return text[:120]
                if '"""' in lines[j] or "'''" in lines[j]:
                    break
            return None
        # JS/TS docstring
        if line.startswith('* ') and not line.startswith('*/'):
            return line[2:].strip()[:120]
        # Go docstring
        if line.startswith('// '):
            return line[3:].strip()[:120]
        # Not a docstring
        if not line.startswith('#') and not line.startswith('*') and not line.startswith('//'):
            break
    
    return None


def infer_summary_from_name(name: str) -> str:
    """Infiere un resumen desde el nombre de la función."""
    # Split camelCase, snake_case, PascalCase
    words = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', name)
    if not words:
        return f"Function {name}"
    
    first_word = words[0].lower()
    
    if first_word in VERB_PATTERNS:
        # Extract object from remaining words
        obj_words = words[1:] if len(words) > 1 else ["data"]
        obj = " ".join(obj_words).lower()
        template = VERB_PATTERNS[first_word]
        return template.format(object=obj, source="source", destination="destination")
    
    return f"Function that processes {name}"


def infer_summary_from_body(content: str, func_line: int, name: str) -> str:
    """Infiere un resumen desde el cuerpo de la función."""
    lines = content.split("\n")
    start = max(0, func_line - 1)
    body = "\n".join(lines[start:start + 30])
    
    # Check for return statements
    returns = re.findall(r'return\s+([^;]+)', body)
    if returns:
        first_return = returns[0].strip()[:60]
        if first_return.startswith('"') or first_return.startswith("'"):
            return f"Returns a string value"
        if first_return.lower() in ('true', 'false'):
            return f"Returns a boolean indicating {name}"
        if first_return.isdigit():
            return f"Returns a numeric value"
        if first_return.startswith('[') or first_return.startswith('{'):
            return f"Returns a collection"
        if 'None' in first_return or 'null' in first_return:
            return f"Returns {first_return} or None"
    
    # Check for specific patterns
    if re.search(r'select\s+.*\s+from', body, re.IGNORECASE):
        return f"Queries database for {name}"
    if re.search(r'insert\s+into', body, re.IGNORECASE):
        return f"Inserts {name} into database"
    if re.search(r'update\s+.*\s+set', body, re.IGNORECASE):
        return f"Updates {name} in database"
    if re.search(r'delete\s+from', body, re.IGNORECASE):
        return f"Deletes {name} from database"
    if re.search(r'raise\s+\w+Error|throw\s+new\s+\w+Error', body):
        return f"Validates and raises error if {name} fails"
    if re.search(r'for\s+.*\s+in\s+', body):
        return f"Iterates over collection in {name}"
    if re.search(r'if\s+.*\s*:', body) and re.search(r'else\s*:', body):
        return f"Conditionally processes {name} based on logic"
    if re.search(r'open\s*\(|with\s+open', body):
        return f"Reads or writes file in {name}"
    if re.search(r'requests\.(get|post|put|delete)|fetch\s*\(', body):
        return f"Makes HTTP request in {name}"
    
    # Fallback to name-based inference
    return infer_summary_from_name(name)


def generate_summary(name: str, content: str, func_line: int, use_llm: bool = True) -> str:
    """Genera un resumen de 1 línea para una función."""
    # 1. Try docstring first
    docstring = extract_docstring_summary(content, func_line)
    if docstring:
        return docstring
    
    # 2. Try LLM if available
    if use_llm:
        try:
            from llm_bridge import is_available, analyze_code
            if is_available():
                lines = content.split("\n")
                start = max(0, func_line - 1)
                code_snippet = "\n".join(lines[start:start + 20])
                llm_summary = analyze_code(code_snippet, f"In one sentence, what does the function '{name}' do?")
                if llm_summary and len(llm_summary) < 200:
                    return llm_summary.strip()
        except ImportError:
            pass
    
    # 3. Heuristic: name + body analysis
    return infer_summary_from_body(content, func_line, name)


def summarize_all_functions(repo_root: Path, code_index: Dict) -> Dict[str, Any]:
    """Genera resúmenes para todas las funciones del codebase."""
    summaries: List[Dict[str, Any]] = []
    
    for f in code_index.get("files", []):
        path = f.get("path", "")
        full_path = repo_root / path
        if not full_path.exists():
            continue
        
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        
        for func in f.get("symbols", {}).get("functions", []):
            name = func.get("name", "")
            if not name or name.startswith("_"):
                continue
            
            line = func.get("line", 0)
            summary = generate_summary(name, content, line)
            
            summaries.append({
                "file": path,
                "function": name,
                "line": line,
                "summary": summary,
                "method": "docstring" if extract_docstring_summary(content, line) else "heuristic",
            })
    
    return {
        "functionsummaries": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "total_functions": len(summaries),
        "summaries": summaries,
    }


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    output = Path(args.get("output", "FUNCTION-SUMMARIES.yaml"))
    
    code_index = read_yaml(ci_path) or {}
    if not code_index.get("files"):
        log("CODE-INDEX vacío", "ERROR")
        return 2
    
    result = summarize_all_functions(repo_root, code_index)
    write_yaml(output, result)
    
    log(f"Summarized {result['total_functions']} functions", "INFO")
    print(json.dumps({
        "success": True,
        "total_functions": result["total_functions"],
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

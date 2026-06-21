#!/usr/bin/env python3
"""
refactor_engine.py — Refactoring automático (v2.6.0).

Detecta code smells y sugiere/ aplica refactoring.
Si LLM disponible, genera código refactorizado. Si no, solo sugiere.

Uso:
  python3 refactor_engine.py --repo-root . --code-index CODE-INDEX.yaml --output REFACTOR-SUGGESTIONS.yaml
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


LONG_FUNCTION_THRESHOLD = 50
HIGH_COMPLEXITY_THRESHOLD = 15
GOD_CLASS_METHODS = 10
DUPLICATE_THRESHOLD = 0.8


def count_lines(repo_root: Path, file_path: str, start_line: int, func_name: str) -> int:
    """Cuenta líneas de una función aproximando desde su inicio hasta la siguiente función."""
    full = repo_root / file_path
    if not full.exists():
        return 0
    try:
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return 0
    
    start = max(0, start_line - 1)
    # Find end: next function/class definition at same or lesser indent
    base_indent = len(lines[start]) - len(lines[start].lstrip()) if start < len(lines) else 0
    end = len(lines)
    for i in range(start + 1, min(start + 200, len(lines))):
        line = lines[i]
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("//"):
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent and re.match(r'^\s*(def |function |func |public |private |class |export )', line):
                end = i
                break
    return end - start


def estimate_complexity(func: Dict, repo_root: Path, file_path: str) -> int:
    """Estima complejidad ciclomática contando ramas."""
    full = repo_root / file_path
    if not full.exists():
        return 1
    try:
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return 1
    
    start = max(0, func.get("line", 1) - 1)
    # Look at next 50 lines
    chunk = "\n".join(lines[start:start + 50])
    
    branches = len(re.findall(r'\b(if|else|elif|for|while|switch|case|catch|&&|\|\|)\b', chunk))
    return branches + 1


def detect_smells(code_index: Dict, repo_root: Path) -> List[Dict]:
    """Detecta code smells."""
    smells = []
    
    for f in code_index.get("files", []):
        path = f.get("path", "")
        lang = f.get("language", "")
        
        # Long functions
        for func in f.get("symbols", {}).get("functions", []):
            name = func.get("name", "")
            if not name or name.startswith("_"):
                continue
            
            line_count = count_lines(repo_root, path, func.get("line", 0), name)
            if line_count > LONG_FUNCTION_THRESHOLD:
                smells.append({
                    "id": f"RF-{len(smells)+1:03d}",
                    "file": path,
                    "function": name,
                    "smell": "long_function",
                    "severity": "high" if line_count > 100 else "medium",
                    "lines": line_count,
                    "suggestion": f"Extract sub-logic from {name} ({line_count} lines) into smaller functions",
                })
            
            # High complexity
            complexity = estimate_complexity(func, repo_root, path)
            if complexity > HIGH_COMPLEXITY_THRESHOLD:
                smells.append({
                    "id": f"RF-{len(smells)+1:03d}",
                    "file": path,
                    "function": name,
                    "smell": "high_complexity",
                    "severity": "high" if complexity > 25 else "medium",
                    "complexity": complexity,
                    "suggestion": f"Reduce branching in {name} (complexity={complexity})",
                })
        
        # God classes
        classes = f.get("symbols", {}).get("classes", [])
        for cls in classes:
            methods = cls.get("methods", [])
            if len(methods) > GOD_CLASS_METHODS:
                smells.append({
                    "id": f"RF-{len(smells)+1:03d}",
                    "file": path,
                    "class": cls.get("name", ""),
                    "smell": "god_class",
                    "severity": "high",
                    "methods": len(methods),
                    "suggestion": f"Split {cls.get('name', '')} ({len(methods)} methods) into smaller classes",
                })
    
    return smells


def generate_refactored(smell: Dict, repo_root: Path) -> Optional[str]:
    """Genera código refactorizado usando LLM si disponible."""
    try:
        from llm_bridge import suggest_refactor, is_available
        if not is_available():
            return None
        
        file_path = repo_root / smell.get("file", "")
        if not file_path.exists():
            return None
        
        code = file_path.read_text(encoding="utf-8", errors="replace")[:3000]
        return suggest_refactor(code, smell.get("smell", ""), smell.get("file", "").split(".")[-1])
    except ImportError:
        return None


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    output = Path(args.get("output", "REFACTOR-SUGGESTIONS.yaml"))
    
    code_index = read_yaml(ci_path) or {}
    if not code_index.get("files"):
        log("CODE-INDEX vacío", "ERROR")
        return 2
    
    smells = detect_smells(code_index, repo_root)
    log(f"Detectados {len(smells)} code smells", "INFO")
    
    # Try LLM for top 5
    for smell in smells[:5]:
        refactored = generate_refactored(smell, repo_root)
        if refactored:
            smell["refactored_code"] = refactored[:1000]
    
    result = {
        "refactorsuggestions": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "total_smells": len(smells),
        "by_severity": {
            "high": sum(1 for s in smells if s.get("severity") == "high"),
            "medium": sum(1 for s in smells if s.get("severity") == "medium"),
        },
        "suggestions": smells,
    }
    
    write_yaml(output, result)
    print(json.dumps({"success": True, "smells": len(smells), "output": str(output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

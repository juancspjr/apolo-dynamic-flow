#!/usr/bin/env python3
"""
code_smells.py — Detección de code smells y dead code (v2.8.0).

Detecta:
  - Code smells: duplicación, god classes, long methods, deep nesting
  - Dead code: funciones/clases nunca referenciadas
  - Complejidad ciclomática con herramientas nativas (radon, gocyclo)

Agnóstico al lenguaje: Python, TS/JS, Go, Java, C++, PHP.

Uso:
  python3 code_smells.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, cmd_available


# ============================================================================
# Code Smell Detection
# ============================================================================

LONG_METHOD_LINES = 50
DEEP_NESTING_LEVEL = 4
GOD_CLASS_METHODS = 10
DUPLICATE_THRESHOLD = 0.8


def detect_long_methods(repo_root: Path, code_index: Dict) -> List[Dict]:
    """Detecta métodos largos (>50 líneas)."""
    smells = []
    for f in code_index.get("files", []):
        path = repo_root / f.get("path", "")
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
        except Exception:
            continue
        
        for func in f.get("symbols", {}).get("functions", []):
            name = func.get("name", "")
            if not name:
                continue
            line_num = func.get("line", 0)
            if line_num == 0:
                continue
            
            # Estimate function length
            start = max(0, line_num - 1)
            base_indent = len(lines[start]) - len(lines[start].lstrip()) if start < len(lines) else 0
            end = len(lines)
            for i in range(start + 1, min(start + 200, len(lines))):
                line = lines[i]
                if line.strip() and not line.strip().startswith(("#", "//", "*")):
                    indent = len(line) - len(line.lstrip())
                    if indent <= base_indent and re.match(r'^\s*(def |function |func |public |private |class |export )', line):
                        end = i
                        break
            length = end - start
            
            if length > LONG_METHOD_LINES:
                smells.append({
                    "type": "long_method",
                    "file": f["path"],
                    "function": name,
                    "lines": length,
                    "severity": "high" if length > 100 else "medium",
                    "suggestion": f"Extract sub-logic from {name} ({length} lines)",
                })
    return smells


def detect_god_classes(code_index: Dict) -> List[Dict]:
    """Detecta god classes (>10 métodos)."""
    smells = []
    for f in code_index.get("files", []):
        for cls in f.get("symbols", {}).get("classes", []):
            methods = cls.get("methods", [])
            if len(methods) > GOD_CLASS_METHODS:
                smells.append({
                    "type": "god_class",
                    "file": f["path"],
                    "class": cls.get("name", "?"),
                    "methods": len(methods),
                    "severity": "high",
                    "suggestion": f"Split {cls.get('name', '?')} into smaller classes",
                })
    return smells


def detect_deep_nesting(repo_root: Path, code_index: Dict) -> List[Dict]:
    """Detecta nesting profundo (>4 niveles)."""
    smells = []
    for f in code_index.get("files", []):
        path = repo_root / f.get("path", "")
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        
        lines = content.split("\n")
        for i, line in enumerate(lines):
            # Count indentation levels
            stripped = line.lstrip()
            if not stripped:
                continue
            indent = len(line) - len(stripped)
            # Estimate nesting level (assuming 2 or 4 spaces per level)
            indent_chars = 2 if "  " in line[:10] else 4
            level = indent // indent_chars if indent_chars > 0 else 0
            
            if level >= DEEP_NESTING_LEVEL and re.search(r'\b(if|for|while|switch|try)\b', stripped):
                smells.append({
                    "type": "deep_nesting",
                    "file": f["path"],
                    "line": i + 1,
                    "nesting_level": level,
                    "severity": "medium",
                    "suggestion": f"Extract nested logic at line {i+1} (depth {level})",
                })
    return smells


def detect_duplication(code_index: Dict) -> List[Dict]:
    """Detecta código duplicado (funciones con >80% similitud en nombres de variables)."""
    smells = []
    all_funcs = []
    
    for f in code_index.get("files", []):
        for func in f.get("symbols", {}).get("functions", []):
            name = func.get("name", "")
            if not name or name.startswith("_"):
                continue
            args = tuple(sorted(func.get("args", [])))
            all_funcs.append({
                "name": name,
                "args": args,
                "file": f["path"],
                "line": func.get("line", 0),
            })
    
    # Compare pairs
    seen = set()
    for i, a in enumerate(all_funcs):
        for b in all_funcs[i+1:]:
            # Same args count and similar name
            if len(a["args"]) == len(b["args"]) and a["args"] == b["args"]:
                # Name similarity (simple: same prefix or suffix)
                a_name = a["name"].lower()
                b_name = b["name"].lower()
                if a_name == b_name:
                    continue  # Same function in different file — OK
                # Check if names share a common stem
                common = os.path.commonprefix([a_name, b_name])
                if len(common) >= 4:
                    pair = tuple(sorted([a["name"], b["name"]]))
                    if pair not in seen:
                        seen.add(pair)
                        smells.append({
                            "type": "possible_duplication",
                            "function_a": a["name"],
                            "file_a": a["file"],
                            "function_b": b["name"],
                            "file_b": b["file"],
                            "common_prefix": common,
                            "severity": "low",
                            "suggestion": f"Review {a['name']} and {b['name']} for duplication",
                        })
    return smells


# ============================================================================
# Dead Code Detection
# ============================================================================

def detect_dead_code(repo_root: Path, code_index: Dict) -> List[Dict]:
    """Detecta funciones/clases exportadas que nunca son referenciadas."""
    dead = []
    
    # Collect all exported symbols
    all_symbols = {}  # name -> [{file, line, type}]
    for f in code_index.get("files", []):
        path = f.get("path", "")
        for func in f.get("symbols", {}).get("functions", []):
            if func.get("is_exported"):
                name = func.get("name", "")
                if name:
                    all_symbols.setdefault(name, []).append({
                        "file": path, "line": func.get("line", 0), "type": "function"
                    })
        for cls in f.get("symbols", {}).get("classes", []):
            if cls.get("is_exported"):
                name = cls.get("name", "")
                if name:
                    all_symbols.setdefault(name, []).append({
                        "file": path, "line": cls.get("line", 0), "type": "class"
                    })
    
    # Search for references in all files
    all_files = [repo_root / f["path"] for f in code_index.get("files", []) if f.get("path")]
    all_text = ""
    for fp in all_files:
        if fp.exists():
            try:
                all_text += fp.read_text(encoding="utf-8", errors="replace") + "\n"
            except Exception:
                pass
    
    for name, locations in all_symbols.items():
        # Skip very common names
        if name in ("init", "main", "run", "start", "stop", "test", "log", "print"):
            continue
        if len(name) < 3:
            continue
        
        # Count references (excluding the definition itself)
        # Simple: count occurrences of the name in all_text
        count = len(re.findall(r'\b' + re.escape(name) + r'\b', all_text))
        
        # If only 1 reference, it's the definition itself → dead code
        if count <= 1:
            for loc in locations:
                dead.append({
                    "type": "dead_code",
                    "symbol": name,
                    "symbol_type": loc["type"],
                    "file": loc["file"],
                    "line": loc["line"],
                    "references": count,
                    "severity": "medium",
                    "suggestion": f"{name} is defined but never referenced — consider removing",
                })
    
    return dead


# ============================================================================
# Cyclomatic Complexity with Native Tools
# ============================================================================

def compute_complexity_native(repo_root: Path, code_index: Dict) -> List[Dict]:
    """Computa complejidad ciclomática con herramientas nativas."""
    results = []
    
    # Python: radon
    if cmd_available("radon"):
        for f in code_index.get("files", []):
            if f.get("language") != "py":
                continue
            path = repo_root / f.get("path", "")
            if not path.exists():
                continue
            code, out, _ = run_cmd(["radon", "cc", str(path), "-s", "-j"], cwd=repo_root, timeout=10)
            if code == 0:
                try:
                    data = json.loads(out)
                    for filename, funcs in data.items():
                        for func in funcs:
                            results.append({
                                "tool": "radon",
                                "file": f["path"],
                                "function": func.get("name", "?"),
                                "complexity": func.get("complexity", 0),
                                "rank": func.get("rank", "?"),
                                "severity": "high" if func.get("complexity", 0) > 15 else "medium" if func.get("complexity", 0) > 10 else "low",
                            })
                except Exception:
                    pass
    
    # Go: gocyclo
    if cmd_available("gocyclo"):
        for f in code_index.get("files", []):
            if f.get("language") != "go":
                continue
            path = repo_root / f.get("path", "")
            if not path.exists():
                continue
            code, out, _ = run_cmd(["gocyclo", str(path)], cwd=repo_root, timeout=10)
            if code == 0:
                for line in out.split("\n"):
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            complexity = int(parts[0])
                            func_name = parts[-1].split(".")[-1] if "." in parts[-1] else parts[-1]
                            results.append({
                                "tool": "gocyclo",
                                "file": f["path"],
                                "function": func_name,
                                "complexity": complexity,
                                "severity": "high" if complexity > 15 else "medium" if complexity > 10 else "low",
                            })
                        except (ValueError, IndexError):
                            pass
    
    # Fallback: regex estimation for all languages
    if not results:
        for f in code_index.get("files", []):
            path = repo_root / f.get("path", "")
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for func in f.get("symbols", {}).get("functions", []):
                name = func.get("name", "")
                line = func.get("line", 0)
                lines = content.split("\n")
                chunk = "\n".join(lines[max(0, line-1):line+50])
                branches = len(re.findall(r'\b(if|else|elif|for|while|switch|case|catch|&&|\|\|)\b', chunk))
                complexity = branches + 1
                results.append({
                    "tool": "regex-estimation",
                    "file": f["path"],
                    "function": name,
                    "complexity": complexity,
                    "severity": "high" if complexity > 15 else "medium" if complexity > 10 else "low",
                })
    
    return results


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    output = Path(args.get("output", "CODE-SMELLS.yaml"))
    
    code_index = read_yaml(ci_path) or {}
    if not code_index.get("files"):
        log("CODE-INDEX vacío", "ERROR")
        return 2
    
    log("Detecting code smells...", "INFO")
    long_methods = detect_long_methods(repo_root, code_index)
    god_classes = detect_god_classes(code_index)
    deep_nesting = detect_deep_nesting(repo_root, code_index)
    duplication = detect_duplication(code_index)
    
    log("Detecting dead code...", "INFO")
    dead_code = detect_dead_code(repo_root, code_index)
    
    log("Computing cyclomatic complexity...", "INFO")
    complexity = compute_complexity_native(repo_root, code_index)
    
    all_smells = long_methods + god_classes + deep_nesting + duplication + dead_code
    high_complexity = [c for c in complexity if c.get("complexity", 0) > 15]
    
    result = {
        "codesmells": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "summary": {
            "total_smells": len(all_smells),
            "long_methods": len(long_methods),
            "god_classes": len(god_classes),
            "deep_nesting": len(deep_nesting),
            "duplication": len(duplication),
            "dead_code": len(dead_code),
            "high_complexity_functions": len(high_complexity),
        },
        "smells": all_smells,
        "complexity": complexity,
        "recommendation": (
            "Code is clean" if len(all_smells) == 0 and len(high_complexity) == 0
            else f"{len(all_smells)} smells and {len(high_complexity)} high-complexity functions found"
        ),
    }
    
    write_yaml(output, result)
    log(f"Code smells: {len(all_smells)} smells, {len(high_complexity)} high complexity", "INFO")
    print(json.dumps({
        "success": True,
        "total_smells": len(all_smells),
        "dead_code": len(dead_code),
        "high_complexity": len(high_complexity),
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
index_codebase.py — Indexador semántico de código basado en AST.

GAP 1: Rapidez de comprensión de código sin discrepancia.

Genera `.opencode/apolo-dynamic/CODE-INDEX.yaml` con un índice liviano de:
  - Funciones/clases/interfaces exportadas con sus firmas
  - Imports (dependencias directas)
  - Última modificación git
  - Hash de contenido (para detectar cambios sin releer)
  - Resumen de 2 líneas generado por AST (no por LLM)

El agente consulta CODE-INDEX.yaml en vez de leer archivos directos
-> 10x menos tokens por comprensión de estructura.

Soporta: Python (.py via `ast`), TypeScript/JavaScript (.ts/.tsx/.js/.jsx via regex
con patrones de export), Go (.go via regex). Otros archivos se registran
solo con hash + size + git-mtime.

Uso:
  python3 index_codebase.py --repo-root /path --output CODE-INDEX.yaml
  python3 index_codebase.py --repo-root /path --output CODE-INDEX.yaml \\
    --include "src/**/*.ts" --exclude "node_modules/**"
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    cmd_available,
    gen_uuid,
    hash_file,
    log,
    now_iso,
    parse_args,
    run_cmd,
    sha256,
    write_yaml,
)


# ============================================================================
# Config
# ============================================================================

DEFAULT_INCLUDES = [
    "**/*.py",
    "**/*.ts",
    "**/*.tsx",
    "**/*.js",
    "**/*.jsx",
    "**/*.go",
    "**/*.json",
    "**/*.yaml",
    "**/*.yml",
]

DEFAULT_EXCLUDES = [
    "**/node_modules/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/.venv/**",
    "**/venv/**",
    "**/*.min.js",
    "**/*.map",
]


# ============================================================================
# Git helpers
# ============================================================================

def git_last_modified(repo_root: Path, file_path: Path) -> Optional[str]:
    """Retorna ISO timestamp de la última modificación git del archivo."""
    try:
        rel = str(file_path.relative_to(repo_root))
        code, out, _ = run_cmd(
            ["git", "log", "-1", "--format=%cI", "--", rel],
            cwd=repo_root,
            timeout=5,
        )
        if code == 0 and out.strip():
            return out.strip()
    except Exception:
        pass
    return None


def git_is_tracked(repo_root: Path, file_path: Path) -> bool:
    try:
        rel = str(file_path.relative_to(repo_root))
        code, _, _ = run_cmd(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=repo_root,
            timeout=5,
        )
        return code == 0
    except Exception:
        return False


# ============================================================================
# Symbol extractors
# ============================================================================

def extract_python_symbols(file_path: Path) -> Dict[str, Any]:
    """Extrae símbolos de un archivo Python usando el módulo `ast` (stdlib)."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return {"error": "syntax-error", "functions": [], "classes": [], "imports": []}
    except Exception as e:
        return {"error": str(e), "functions": [], "classes": [], "imports": []}

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            defaults_n = len(node.args.defaults) if node.args.defaults else 0
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "args": args,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "is_exported": not node.name.startswith("_"),
                "decorators": [
                    (d.id if isinstance(d, ast.Name) else
                     d.attr if isinstance(d, ast.Attribute) else "?")
                    for d in node.decorator_list
                ],
                "docstring": ast.get_docstring(node, clean=True)[:200] if ast.get_docstring(node) else None,
            })
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        "name": item.name,
                        "line": item.lineno,
                        "is_async": isinstance(item, ast.AsyncFunctionDef),
                        "args": [a.arg for a in item.args.args],
                    })
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": [
                    (b.id if isinstance(b, ast.Name) else
                     b.attr if isinstance(b, ast.Attribute) else "?")
                    for b in node.bases
                ],
                "methods": methods,
                "is_exported": not node.name.startswith("_"),
                "docstring": ast.get_docstring(node, clean=True)[:200] if ast.get_docstring(node) else None,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "module": alias.name,
                    "alias": alias.asname,
                    "kind": "import",
                    "line": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append({
                    "module": module,
                    "name": alias.name,
                    "alias": alias.asname,
                    "kind": "from-import",
                    "line": node.lineno,
                })

    return {
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "module_docstring": ast.get_docstring(tree, clean=True)[:300] if ast.get_docstring(tree) else None,
    }


# Patrones regex para TS/JS (simplificados pero efectivos)
TS_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*"
    r"\(([^)]*)\)",
    re.MULTILINE,
)
TS_ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
    re.MULTILINE,
)
TS_CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?",
    re.MULTILINE,
)
TS_INTERFACE_RE = re.compile(
    r"^\s*(?:export\s+)?interface\s+(\w+)",
    re.MULTILINE,
)
TS_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:\{([^}]+)\}|\*\s+as\s+(\w+)|(\w+))\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
TS_EXPORT_RE = re.compile(
    r"^\s*export\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)


def extract_ts_symbols(file_path: Path) -> Dict[str, Any]:
    """Extrae símbolos de TS/JS usando regex (no AST — fallback robusto)."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e), "functions": [], "classes": [], "imports": []}

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    interfaces: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []

    # Funciones
    for m in TS_FUNCTION_RE.finditer(content):
        name = m.group(1)
        args_str = m.group(2).strip()
        args = [a.strip().split(":")[0].split("?")[0].strip() for a in args_str.split(",") if a.strip()]
        is_exported = "export" in m.group(0)
        is_async = "async" in m.group(0)
        line = content[:m.start()].count("\n") + 1
        functions.append({
            "name": name,
            "line": line,
            "args": args,
            "is_async": is_async,
            "is_exported": is_exported,
        })

    # Arrow functions (const x = (args) =>)
    for m in TS_ARROW_RE.finditer(content):
        name = m.group(1)
        args_str = m.group(2).strip()
        args = [a.strip().split(":")[0].split("?")[0].strip() for a in args_str.split(",") if a.strip()]
        is_exported = "export" in m.group(0)
        is_async = "async" in m.group(0)
        line = content[:m.start()].count("\n") + 1
        functions.append({
            "name": name,
            "line": line,
            "args": args,
            "is_async": is_async,
            "is_exported": is_exported,
            "is_arrow": True,
        })

    # Classes
    for m in TS_CLASS_RE.finditer(content):
        name = m.group(1)
        extends = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        is_exported = "export" in m.group(0)
        line = content[:m.start()].count("\n") + 1
        classes.append({
            "name": name,
            "line": line,
            "extends": extends,
            "is_exported": is_exported,
        })

    # Interfaces
    for m in TS_INTERFACE_RE.finditer(content):
        name = m.group(1)
        is_exported = "export" in m.group(0)
        line = content[:m.start()].count("\n") + 1
        interfaces.append({
            "name": name,
            "line": line,
            "is_exported": is_exported,
        })

    # Imports
    for m in TS_IMPORT_RE.finditer(content):
        names_group = m.group(1)
        namespace = m.group(2)
        default = m.group(3)
        module = m.group(4)
        line = content[:m.start()].count("\n") + 1
        if names_group:
            names = [n.strip() for n in names_group.split(",") if n.strip()]
            for n in names:
                imports.append({
                    "module": module,
                    "name": n,
                    "kind": "named",
                    "line": line,
                })
        elif namespace:
            imports.append({
                "module": module,
                "name": namespace,
                "kind": "namespace",
                "line": line,
            })
        elif default:
            imports.append({
                "module": module,
                "name": default,
                "kind": "default",
                "line": line,
            })

    # Re-exports
    for m in TS_EXPORT_RE.finditer(content):
        names_group = m.group(1)
        module = m.group(2)
        line = content[:m.start()].count("\n") + 1
        names = [n.strip() for n in names_group.split(",") if n.strip()]
        for n in names:
            imports.append({
                "module": module,
                "name": n,
                "kind": "re-export",
                "line": line,
            })

    return {
        "functions": functions,
        "classes": classes,
        "interfaces": interfaces,
        "imports": imports,
    }


# Patrones Go
GO_FUNC_RE = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)\s*(?:\(([^)]*)\)|([^{\n]+))?",
    re.MULTILINE,
)
GO_TYPE_RE = re.compile(
    r"^type\s+(\w+)\s+(?:struct|interface)",
    re.MULTILINE,
)
GO_IMPORT_RE = re.compile(
    r'^import\s+(?:\(([^)]+)\)|"([^"]+)")',
    re.MULTILINE,
)


def extract_go_symbols(file_path: Path) -> Dict[str, Any]:
    """Extrae símbolos de Go usando regex."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e), "functions": [], "types": [], "imports": []}

    functions: List[Dict[str, Any]] = []
    types: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []

    for m in GO_FUNC_RE.finditer(content):
        name = m.group(1)
        args_str = m.group(2).strip() if m.group(2) else ""
        line = content[:m.start()].count("\n") + 1
        is_exported = name[0].isupper() if name else False
        functions.append({
            "name": name,
            "line": line,
            "args": [a.strip().split(" ")[0] for a in args_str.split(",") if a.strip()],
            "is_exported": is_exported,
            "receiver": "method" if "(" in m.group(0).split("func")[1].split(")")[0] else None,
        })

    for m in GO_TYPE_RE.finditer(content):
        name = m.group(1)
        line = content[:m.start()].count("\n") + 1
        types.append({
            "name": name,
            "line": line,
            "is_exported": name[0].isupper() if name else False,
        })

    for m in GO_IMPORT_RE.finditer(content):
        if m.group(1):  # bloque import (...)
            block = m.group(1)
            for line in block.split("\n"):
                line = line.strip()
                if line.startswith('"') and line.endswith('"'):
                    imports.append({"module": line[1:-1], "line": content[:m.start()].count("\n") + 1})
        elif m.group(2):
            imports.append({
                "module": m.group(2),
                "line": content[:m.start()].count("\n") + 1,
            })

    return {
        "functions": functions,
        "types": types,
        "imports": imports,
    }


# ============================================================================
# Summary generation (AST-based, deterministic, no LLM)
# ============================================================================

def generate_summary(symbols: Dict[str, Any], file_path: Path) -> str:
    """Genera un resumen determinista de 2 líneas basado en los símbolos extraídos."""
    parts: List[str] = []

    if "error" in symbols:
        return f"Error parseando: {symbols['error']}"

    # Línea 1: tipo de archivo + símbolos principales
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        n_funcs = len(symbols.get("functions", []))
        n_classes = len(symbols.get("classes", []))
        exported_funcs = sum(1 for f in symbols.get("functions", []) if f.get("is_exported"))
        parts.append(f"Python: {n_classes} clases, {n_funcs} funciones ({exported_funcs} exportadas)")
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        n_funcs = len(symbols.get("functions", []))
        n_classes = len(symbols.get("classes", []))
        n_ifaces = len(symbols.get("interfaces", []))
        exported = sum(1 for f in symbols.get("functions", []) if f.get("is_exported"))
        parts.append(
            f"TS/JS: {n_classes} clases, {n_ifaces} interfaces, {n_funcs} funciones ({exported} exportadas)"
        )
    elif suffix == ".go":
        n_funcs = len(symbols.get("functions", []))
        n_types = len(symbols.get("types", []))
        exported_funcs = sum(1 for f in symbols.get("functions", []) if f.get("is_exported"))
        parts.append(f"Go: {n_types} tipos, {n_funcs} funciones ({exported_funcs} exportadas)")
    else:
        parts.append(f"Archivo {suffix}")

    # Línea 2: nombres de los símbolos exportados principales
    exported_names: List[str] = []
    for f in symbols.get("functions", []):
        if f.get("is_exported"):
            exported_names.append(f["name"] + "()")
    for c in symbols.get("classes", []):
        if c.get("is_exported"):
            exported_names.append(c["name"])
    for i in symbols.get("interfaces", []):
        if i.get("is_exported"):
            exported_names.append(i["name"] + "<I>")
    for t in symbols.get("types", []):
        if t.get("is_exported"):
            exported_names.append(t["name"])

    if exported_names:
        parts.append("Exporta: " + ", ".join(exported_names[:8]) + ("..." if len(exported_names) > 8 else ""))
    else:
        parts.append("Sin símbolos exportados")

    return " | ".join(parts)


# ============================================================================
# File discovery
# ============================================================================

def discover_files(
    repo_root: Path,
    includes: List[str],
    excludes: List[str],
) -> List[Path]:
    """Descubre archivos que matchean includes y no matchean excludes."""
    from fnmatch import fnmatch

    all_files: List[Path] = []
    seen: set = set()

    for pattern in includes:
        for p in repo_root.glob(pattern):
            if p.is_file() and p not in seen:
                # Verificar excludes (relativo al repo root)
                rel = str(p.relative_to(repo_root))
                excluded = False
                for ex in excludes:
                    ex_clean = ex.replace("**/", "").replace("/**", "")
                    if fnmatch(rel, ex) or ex_clean in rel:
                        excluded = True
                        break
                if not excluded:
                    all_files.append(p)
                    seen.add(p)

    return sorted(all_files)


# ============================================================================
# Indexer
# ============================================================================

def index_file(repo_root: Path, file_path: Path) -> Dict[str, Any]:
    """Indexa un archivo: extrae símbolos, hash, git-mtime, summary."""
    rel = str(file_path.relative_to(repo_root))
    suffix = file_path.suffix.lower()

    # Hash + size
    h = hash_file(file_path) or ""
    size = file_path.stat().st_size

    # Git metadata
    git_mtime = git_last_modified(repo_root, file_path)
    git_tracked = git_is_tracked(repo_root, file_path)

    # Symbols por tipo
    if suffix == ".py":
        symbols = extract_python_symbols(file_path)
    elif suffix in (".ts", ".tsx", ".js", ".jsx"):
        symbols = extract_ts_symbols(file_path)
    elif suffix == ".go":
        symbols = extract_go_symbols(file_path)
    else:
        symbols = {"functions": [], "classes": [], "imports": []}

    # Summary
    summary = generate_summary(symbols, file_path)

    # Imports normalizados (para análisis de dependencias)
    imports_normalized = []
    for imp in symbols.get("imports", []):
        imports_normalized.append({
            "module": imp.get("module", ""),
            "name": imp.get("name", ""),
            "kind": imp.get("kind", ""),
            "line": imp.get("line", 0),
        })

    return {
        "path": rel,
        "language": suffix.lstrip(".") or "unknown",
        "size_bytes": size,
        "content_hash": h,
        "git_tracked": git_tracked,
        "git_last_modified": git_mtime,
        "summary": summary,
        "symbols": {
            "functions": symbols.get("functions", []),
            "classes": symbols.get("classes", []),
            "interfaces": symbols.get("interfaces", []),
            "types": symbols.get("types", []),
        },
        "imports": imports_normalized,
        "error": symbols.get("error"),
    }


def build_dependency_graph(files_index: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Construye grafo de dependencias: file -> [files it imports]."""
    by_module: Dict[str, str] = {}
    for f in files_index:
        # Mapear nombre base (sin extensión) al path relativo
        stem = Path(f["path"]).stem
        by_module[stem] = f["path"]

    graph: Dict[str, List[str]] = {}
    for f in files_index:
        deps: List[str] = []
        for imp in f.get("imports", []):
            module = imp.get("module", "")
            if not module:
                continue
            # Resolver imports relativos o por nombre
            stem = Path(module).stem
            if stem in by_module and by_module[stem] != f["path"]:
                dep = by_module[stem]
                if dep not in deps:
                    deps.append(dep)
        graph[f["path"]] = deps

    return graph


def build_reverse_dependency_graph(dep_graph: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Construye grafo reverso: file -> [files that import it]."""
    reverse: Dict[str, List[str]] = {f: [] for f in dep_graph}
    for f, deps in dep_graph.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].append(f)
    return reverse


# ============================================================================
# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))

    # Includes/excludes (coma-separated)
    includes_str = args.get("include", "")
    excludes_str = args.get("exclude", "")
    includes = [s.strip() for s in includes_str.split(",") if s.strip()] or DEFAULT_INCLUDES
    excludes = [s.strip() for s in excludes_str.split(",") if s.strip()] or DEFAULT_EXCLUDES

    log(f"Indexando codebase en {repo_root}...", "INFO")
    start = time.time()

    # 1. Descubrir archivos
    files = discover_files(repo_root, includes, excludes)
    log(f"Encontrados {len(files)} archivos para indexar", "INFO")

    # 2. Indexar cada archivo
    files_index: List[Dict[str, Any]] = []
    for i, f in enumerate(files):
        try:
            entry = index_file(repo_root, f)
            files_index.append(entry)
        except Exception as e:
            log(f"Error indexando {f}: {e}", "WARN")
        if (i + 1) % 50 == 0:
            log(f"  Progreso: {i+1}/{len(files)}", "INFO")

    # 3. Construir grafo de dependencias
    dep_graph = build_dependency_graph(files_index)
    reverse_graph = build_reverse_dependency_graph(dep_graph)

    # 4. Calcular estadísticas
    by_language: Dict[str, int] = {}
    total_functions = 0
    total_classes = 0
    total_imports = 0
    for f in files_index:
        lang = f["language"]
        by_language[lang] = by_language.get(lang, 0) + 1
        total_functions += len(f["symbols"]["functions"])
        total_classes += len(f["symbols"]["classes"])
        total_imports += len(f["imports"])

    duration_ms = int((time.time() - start) * 1000)

    # 5. Generar hash del índice (para detectar cambios)
    index_content = json.dumps(
        [{"path": f["path"], "hash": f["content_hash"]} for f in files_index],
        sort_keys=True,
    )
    index_hash = sha256(index_content)

    # 6. Construir documento final
    code_index = {
        "codeindex": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "generator": {
            "script": "scripts/python/index_codebase.py",
            "duration_ms": duration_ms,
            "files_indexed": len(files_index),
        },
        "repo_root": str(repo_root),
        "index_hash": index_hash,
        "stats": {
            "total_files": len(files_index),
            "by_language": by_language,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "total_imports": total_imports,
            "avg_functions_per_file": round(total_functions / max(len(files_index), 1), 2),
        },
        "files": files_index,
        "dependency_graph": dep_graph,
        "reverse_dependency_graph": reverse_graph,
    }

    # 7. Persistir
    write_yaml(output, code_index)

    log(
        f"Code index generado: {len(files_index)} archivos, "
        f"{total_functions} funciones, {total_classes} clases, "
        f"{duration_ms}ms",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "files_indexed": len(files_index),
        "total_functions": total_functions,
        "total_classes": total_classes,
        "duration_ms": duration_ms,
        "index_hash": index_hash,
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

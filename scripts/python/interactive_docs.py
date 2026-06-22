#!/usr/bin/env python3
"""
interactive_docs.py — Documentación interactiva con búsqueda + ejemplos contextuales (v2.8.1).

Cierra el GAP #11: "Documentación interactiva (búsqueda + ejemplos contextuales)".

Indexa TODA la documentación del repositorio:
  - README.md y *.md
  - Docstrings de scripts Python (scripts/python/*.py)
  - Comentarios de encabezado en TypeScript (plugin/*.ts)
  - Scripts bash con comentarios (scripts/bash/*.sh)
  - YAMLs de configuración con descripciones

Construye un índice TF-IDF minimalista (sin dependencias externas) que permite:
  - Búsqueda por keywords
  - Sugerencias contextuales basadas en la fase actual del flow
  - Ejemplos de uso extraídos de los docstrings

CLI:
  # Indexar docs (genera .opencode/apolo-dynamic/DOCS-INDEX.yaml)
  python3 interactive_docs.py index --repo-root .

  # Buscar
  python3 interactive_docs.py search --repo-root . --query "vulnerability scan"

  # Sugerencias contextuales para la fase actual
  python3 interactive_docs.py context --repo-root . --phase reanclaje --task "scaffold"

  # Ver ejemplos de un script específico
  python3 interactive_docs.py examples --repo-root . --script vulnerability_scanner

  # Estadísticas del índice
  python3 interactive_docs.py stats --repo-root .
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


DOCS_INDEX_FILE = "DOCS-INDEX.yaml"
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "up", "about", "into", "through", "during",
    "before", "after", "above", "below", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de",
    "del", "al", "en", "para", "por", "con", "sin", "sobre", "tras", "es",
    "son", "fue", "fueron", "ser", "estar", "tiene", "tienen", "hace",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
}

# Fases del state machine y keywords asociadas
PHASE_KEYWORDS: Dict[str, List[str]] = {
    "init": ["init", "initial", "setup", "start", "begin", "flow", "create"],
    "verdad": ["truth", "verdad", "evidence", "collect", "gather", "facts"],
    "plan-indice": ["plan", "index", "codebase", "impact", "predict"],
    "reanclaje": ["reanchor", "scaffold", "implement", "unit", "code"],
    "exec": ["execute", "run", "test", "verify"],
    "validar": ["validate", "check", "score", "evidence", "gate"],
    "merge": ["merge", "commit", "finalize"],
}


def tokenize(text: str) -> List[str]:
    """Tokeniza texto en palabras minúsculas, sin stop words."""
    text = text.lower()
    tokens = re.findall(r"[a-záéíóúñ_][a-záéíóúñ0-9_-]{1,}", text)
    return [t for t in tokens if t not in STOP_WORDS and len(t) > 2]


def extract_docstring_py(path: Path) -> Tuple[str, List[str]]:
    """Extrae el docstring principal y ejemplos de un archivo Python."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content)
    except Exception:
        return "", []

    docstring = ast.get_docstring(tree) or ""

    # Buscar bloques de ejemplo (líneas con "  >>> " o "  $ " o "Uso:")
    examples = []
    in_example = False
    current = []
    for line in content.split("\n"):
        if re.match(r"^\s*(>>>|\$)\s", line):
            current.append(line.strip())
            in_example = True
        elif in_example and line.strip() and not line.startswith(" "):
            if current:
                examples.append("\n".join(current))
                current = []
            in_example = False
        elif in_example:
            current.append(line.strip())
    if current:
        examples.append("\n".join(current))

    # Buscar sección "Uso:" o "Usage:"
    uso_match = re.search(r"(?:Uso|Usage):\s*\n((?:\s+\S.*\n?)+)", content)
    if uso_match:
        examples.append(uso_match.group(1).strip())

    return docstring, examples


def extract_header_ts(path: Path) -> Tuple[str, List[str]]:
    """Extrae el comentario de encabezado de un archivo TypeScript."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", []

    lines = content.split("\n")
    header = []
    for line in lines:
        if line.startswith("//") or line.startswith("/*") or line.startswith("*"):
            header.append(line.lstrip("/ *"))
        elif line.strip() == "":
            continue
        else:
            break
    return "\n".join(header).strip(), []


def extract_header_bash(path: Path) -> Tuple[str, List[str]]:
    """Extrae comentarios de encabezado de un script bash."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", []
    lines = content.split("\n")
    header = []
    for line in lines:
        if line.startswith("#") and not line.startswith("#!"):
            header.append(line.lstrip("# "))
        elif line.strip() == "":
            continue
        else:
            break
    return "\n".join(header).strip(), []


def index_markdown(path: Path, repo_root: Path) -> Dict[str, Any]:
    """Indexa un archivo Markdown."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    # Extraer headings como secciones
    sections = []
    current_heading = ""
    current_body: List[str] = []
    for line in content.split("\n"):
        if line.startswith("#"):
            if current_heading:
                sections.append({
                    "heading": current_heading,
                    "body": "\n".join(current_body)[:500],
                })
            current_heading = line.lstrip("# ").strip()
            current_body = []
        else:
            current_body.append(line)
    if current_heading:
        sections.append({
            "heading": current_heading,
            "body": "\n".join(current_body)[:500],
        })

    return {
        "type": "markdown",
        "path": str(path.relative_to(repo_root)),
        "title": path.stem,
        "docstring": content[:1000],
        "sections": sections[:50],  # cap
        "tokens": tokenize(content),
    }


def index_python(path: Path, repo_root: Path) -> Dict[str, Any]:
    """Indexa un script Python."""
    docstring, examples = extract_docstring_py(path)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    return {
        "type": "python",
        "path": str(path.relative_to(repo_root)),
        "title": path.stem,
        "docstring": docstring[:1000],
        "examples": examples[:10],
        "tokens": tokenize(docstring + " " + content[:5000]),
    }


def index_typescript(path: Path, repo_root: Path) -> Dict[str, Any]:
    """Indexa un archivo TypeScript."""
    header, _ = extract_header_ts(path)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    return {
        "type": "typescript",
        "path": str(path.relative_to(repo_root)),
        "title": path.stem,
        "docstring": header[:1000],
        "tokens": tokenize(header + " " + content[:5000]),
    }


def index_bash(path: Path, repo_root: Path) -> Dict[str, Any]:
    """Indexa un script bash."""
    header, _ = extract_header_bash(path)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    return {
        "type": "bash",
        "path": str(path.relative_to(repo_root)),
        "title": path.stem,
        "docstring": header[:1000],
        "tokens": tokenize(header + " " + content[:3000]),
    }


def build_index(repo_root: Path) -> Dict[str, Any]:
    """Construye el índice de documentación."""
    docs: List[Dict[str, Any]] = []

    # Markdown
    for md in repo_root.rglob("*.md"):
        if any(p in str(md) for p in ("node_modules", ".git", "dist/", ".opencode")):
            continue
        entry = index_markdown(md, repo_root)
        if entry:
            docs.append(entry)

    # Python scripts
    py_dir = repo_root / "scripts" / "python"
    if py_dir.exists():
        for py in py_dir.glob("*.py"):
            entry = index_python(py, repo_root)
            if entry:
                docs.append(entry)

    # TypeScript
    plugin_dir = repo_root / "plugin"
    if plugin_dir.exists():
        for ts in plugin_dir.rglob("*.ts"):
            if "node_modules" in str(ts) or "dist/" in str(ts):
                continue
            entry = index_typescript(ts, repo_root)
            if entry:
                docs.append(entry)

    # Bash
    bash_dir = repo_root / "scripts" / "bash"
    if bash_dir.exists():
        for sh in bash_dir.glob("*.sh"):
            entry = index_bash(sh, repo_root)
            if entry:
                docs.append(entry)

    # Build TF-IDF
    N = len(docs)
    df: Counter = Counter()
    for d in docs:
        for term in set(d["tokens"]):
            df[term] += 1

    tfidf_index: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
    for i, d in enumerate(docs):
        tf = Counter(d["tokens"])
        for term, count in tf.items():
            idf = math.log((N + 1) / (df[term] + 1)) + 1
            weight = count * idf
            tfidf_index[term].append((i, weight))

    # Compactar: top 50 docs por término
    for term in tfidf_index:
        tfidf_index[term] = sorted(tfidf_index[term], key=lambda x: -x[1])[:50]

    return {
        "docsindex": "V1",
        "version": 1,
        "schema_version": "2.8.1",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "total_docs": N,
        "total_terms": len(tfidf_index),
        "docs": docs,
        "tfidf": {k: [{"i": i, "w": round(w, 3)} for i, w in v] for k, v in tfidf_index.items()},
    }


def _safe_str(value: Any, max_len: int = 200) -> str:
    """Convierte cualquier valor a string de forma segura para previews."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:max_len]
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)[:max_len]
        except Exception:
            return str(value)[:max_len]
    return str(value)[:max_len]


def search_docs(index: Dict[str, Any], query: str, top: int = 10) -> List[Dict[str, Any]]:
    """Busca documentos por query usando TF-IDF."""
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scores: Dict[int, float] = defaultdict(float)
    tfidf = index.get("tfidf", {})
    for token in query_tokens:
        if token in tfidf:
            for entry in tfidf[token]:
                scores[entry["i"]] += entry["w"]

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:top]
    results = []
    for doc_idx, score in ranked:
        if doc_idx >= len(index["docs"]):
            continue
        doc = index["docs"][doc_idx]
        if not isinstance(doc, dict):
            continue
        results.append({
            "score": round(score, 3),
            "path": doc.get("path", "?"),
            "type": doc.get("type", "?"),
            "title": doc.get("title", "?"),
            "docstring_preview": _safe_str(doc.get("docstring", ""), 200),
        })
    return results


def contextual_suggestions(index: Dict[str, Any], phase: str, task: str = "") -> List[Dict[str, Any]]:
    """Retorna sugerencias contextuales basadas en la fase actual del flow."""
    keywords = PHASE_KEYWORDS.get(phase, [])
    if task:
        keywords = keywords + tokenize(task)

    query = " ".join(keywords)
    return search_docs(index, query, top=5)


def get_examples(index: Dict[str, Any], script_name: str) -> List[str]:
    """Obtiene ejemplos de uso de un script específico."""
    for doc in index["docs"]:
        if doc["type"] == "python" and doc["title"] == script_name:
            return doc.get("examples", [])
    return []


def docs_index_path(repo_root: Path) -> Path:
    return repo_root / ".opencode" / "apolo-dynamic" / DOCS_INDEX_FILE


def main() -> int:
    argv = sys.argv[1:]
    action = "search"
    if argv and not argv[0].startswith("--") and argv[0] in {"index", "search", "context", "examples", "stats"}:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    index_p = docs_index_path(repo_root)

    if action == "index":
        log("Indexando documentación...", "INFO")
        idx = build_index(repo_root)
        write_yaml(index_p, idx)
        log(f"Índice generado: {idx['total_docs']} docs, {idx['total_terms']} términos", "INFO")
        print(json.dumps({
            "success": True,
            "total_docs": idx["total_docs"],
            "total_terms": idx["total_terms"],
            "output": str(index_p),
        }, indent=2))
        return 0

    # Para los demás actions necesitamos el índice
    if not index_p.exists():
        log("Índice no existe. Ejecuta: python3 interactive_docs.py index --repo-root .", "INFO")
        # Auto-build para conveniencia
        idx = build_index(repo_root)
        write_yaml(index_p, idx)
        log(f"Índice auto-generado: {idx['total_docs']} docs", "INFO")
    else:
        idx = read_yaml(index_p) or {}

    if action == "search":
        query = args.get("query", "") or args.get("q", "")
        if not query:
            print(json.dumps({"success": False, "error": "Falta --query"}, indent=2))
            return 2
        top = int(args.get("top", "10") or 10)
        results = search_docs(idx, query, top)
        print(json.dumps({"success": True, "query": query, "results": results, "count": len(results)}, ensure_ascii=False, indent=2))
        return 0

    elif action == "context":
        phase = args.get("phase", "")
        task = args.get("task", "")
        if not phase:
            print(json.dumps({"success": False, "error": "Falta --phase"}, indent=2))
            return 2
        results = contextual_suggestions(idx, phase, task)
        print(json.dumps({"success": True, "phase": phase, "task": task, "suggestions": results, "count": len(results)}, ensure_ascii=False, indent=2))
        return 0

    elif action == "examples":
        script = args.get("script", "")
        if not script:
            print(json.dumps({"success": False, "error": "Falta --script"}, indent=2))
            return 2
        examples = get_examples(idx, script)
        print(json.dumps({"success": True, "script": script, "examples": examples, "count": len(examples)}, ensure_ascii=False, indent=2))
        return 0

    elif action == "stats":
        type_counts: Counter = Counter(d["type"] for d in idx.get("docs", []))
        print(json.dumps({
            "success": True,
            "total_docs": idx.get("total_docs", 0),
            "total_terms": idx.get("total_terms", 0),
            "by_type": dict(type_counts),
            "generated_at": idx.get("generated_at", ""),
        }, indent=2))
        return 0

    else:
        print(json.dumps({"success": False, "error": f"unknown action: {action}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

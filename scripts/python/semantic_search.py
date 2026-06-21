#!/usr/bin/env python3
"""
semantic_search.py — Búsqueda semántica de código (v2.6.0).

Si LLM disponible: usa embeddings reales de la API.
Si no: usa TF-IDF simplificado (100% determinista).

Uso:
  python3 semantic_search.py --repo-root . --query "inicializar flow" --top 5
  python3 semantic_search.py --repo-root . --build-index
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


def tokenize(text: str) -> List[str]:
    text = text.lower()
    return re.findall(r'[a-z_][a-z0-9_]*', text)


def tf_idf(docs: Dict[str, str], query: str) -> List[Tuple[str, float]]:
    """TF-IDF simplificado para búsqueda semántica sin LLM."""
    N = len(docs)
    if N == 0:
        return []
    
    # Document frequencies
    df = Counter()
    doc_tokens = {}
    for name, text in docs.items():
        tokens = tokenize(text)
        doc_tokens[name] = tokens
        for t in set(tokens):
            df[t] += 1
    
    # Query tokens
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    
    # IDF
    idf = {t: math.log((N + 1) / (df.get(t, 0) + 1)) + 1 for t in q_tokens}
    
    # Score each doc
    scores = []
    for name, tokens in doc_tokens.items():
        tf = Counter(tokens)
        score = sum(tf.get(t, 0) * idf.get(t, 0) for t in q_tokens)
        if score > 0:
            scores.append((name, score))
    
    scores.sort(key=lambda x: -x[1])
    return scores


def cosine_sim(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def build_embeddings(code_index: Dict, use_llm: bool = False) -> Dict[str, List[float]]:
    """Genera embeddings para cada función/clase."""
    embeddings = {}
    
    try:
        from llm_bridge import embed, is_available
        use_llm = use_llm and is_available()
    except ImportError:
        use_llm = False
    
    for f in code_index.get("files", []):
        path = f.get("path", "")
        summary = f.get("summary", path)
        
        for func in f.get("symbols", {}).get("functions", []):
            name = func.get("name", "")
            if not name:
                continue
            text = f"{name} {summary} {' '.join(func.get('args', []))}"
            
            if use_llm:
                emb = embed(text)
                if emb:
                    embeddings[f"{path}::{name}"] = emb
            else:
                embeddings[f"{path}::{name}"] = _hash_embed(text)
    
    return embeddings


def _hash_embed(text: str, dims: int = 64) -> List[float]:
    """Pseudo-embedding determinista para fallback."""
    tokens = tokenize(text)
    vec = [0.0] * dims
    for t in tokens:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        vec[h % dims] += 1.0
    # Normalize
    mag = math.sqrt(sum(v * v for v in vec))
    if mag > 0:
        vec = [v / mag for v in vec]
    return vec


def search(query: str, embeddings: Dict, top_k: int = 5) -> List[Dict]:
    """Busca funciones semánticamente similares al query."""
    try:
        from llm_bridge import embed, is_available
        if is_available():
            q_emb = embed(query)
        else:
            q_emb = _hash_embed(query)
    except ImportError:
        q_emb = _hash_embed(query)
    
    results = []
    for key, emb in embeddings.items():
        sim = cosine_sim(q_emb, emb)
        if sim > 0.01:
            path, _, name = key.partition("::")
            results.append({"path": path, "symbol": name, "similarity": round(sim, 4)})
    
    results.sort(key=lambda x: -x["similarity"])
    return results[:top_k]


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    query = args.get("query", "")
    top_k = int(args.get("top", "5"))
    build = args.get("build", "") == "true"
    
    code_index = read_yaml(ci_path) or {}
    if not code_index.get("files"):
        log("CODE-INDEX vacío", "ERROR")
        return 2
    
    cache_path = repo_root / ".opencode" / "apolo-dynamic" / "EMBEDDINGS-CACHE.json"
    
    if build or not cache_path.exists():
        embeddings = build_embeddings(code_index)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(embeddings), encoding="utf-8")
        log(f"Embeddings construidos: {len(embeddings)} funciones", "INFO")
    else:
        embeddings = json.loads(cache_path.read_text(encoding="utf-8"))
    
    if query:
        results = search(query, embeddings, top_k)
        print(json.dumps({"query": query, "results": results, "total": len(results)}, indent=2))
    else:
        print(json.dumps({"embeddings": len(embeddings), "cache": str(cache_path)}))
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
llm_bridge.py — Interface universal para LLM (v2.6.0).

Lee OPENAI_API_BASE y MINIMAX_API_KEY (o OPENAI_API_KEY) del entorno.
Usa curl para llamadas (sin dependencias Python externas).

Si no hay API key, todas las funciones retornan None y el caller usa
fallback determinista. El sistema es 100% funcional sin LLM.

Uso:
  from llm_bridge import chat, embed, is_available, analyze_code, suggest_fix
  
  if is_available():
      response = chat([{"role": "user", "content": "Analyze this code"}])
  else:
      response = None  # usar fallback determinista
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, run_cmd, cmd_available


# ============================================================================
# Configuration
# ============================================================================

def get_api_base() -> str:
    return os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")


def get_api_key() -> str:
    return os.environ.get("MINIMAX_API_KEY", os.environ.get("OPENAI_API_KEY", ""))


def get_model() -> str:
    return os.environ.get("APOLO_LLM_MODEL", "MiniMax-M3")


def is_available() -> bool:
    """Retorna True si hay API key configurada."""
    return bool(get_api_key())


# ============================================================================
# Cache
# ============================================================================

CACHE_PATH = Path("/tmp/apolo-llm-cache.json")


def _load_cache() -> Dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def _cache_key(messages: List[Dict], prefix: str = "chat") -> str:
    raw = json.dumps({"p": prefix, "m": messages}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# ============================================================================
# API calls via curl
# ============================================================================

def _api_call(endpoint: str, payload: Dict, timeout: int = 30) -> Optional[Dict]:
    """Hace una llamada a la API via curl. Retorna None si falla."""
    if not is_available():
        return None
    if not cmd_available("curl"):
        log("curl no disponible para LLM bridge", "WARN")
        return None

    url = f"{get_api_base()}/{endpoint}"
    api_key = get_api_key()

    cmd = [
        "curl", "-sS", "--fail", "--max-time", str(timeout),
        "-X", "POST",
        "-H", f"Authorization: Bearer {api_key}",
        "-H", "Content-Type: application/json",
        "-d", json.dumps(payload),
        url,
    ]

    code, out, err = run_cmd(cmd, timeout=timeout + 5)
    if code != 0:
        log(f"LLM API call failed: {err[:200]}", "WARN")
        return None

    try:
        return json.loads(out)
    except Exception as e:
        log(f"LLM API response parse error: {e}", "WARN")
        return None


# ============================================================================
# Public API
# ============================================================================

def chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 2000,
    use_cache: bool = True,
) -> Optional[str]:
    """Llama al endpoint /chat/completions.
    
    Args:
        messages: lista de {"role": "user|system|assistant", "content": "..."}
        temperature: 0.0 = determinista, 1.0 = creativo
        max_tokens: máximo tokens de respuesta
        use_cache: si True, cachea la respuesta
    
    Returns:
        Texto de respuesta, o None si no hay API/disponible/falla
    """
    if not is_available():
        return None

    # Check cache
    if use_cache:
        cache = _load_cache()
        key = _cache_key(messages, f"chat_{temperature}_{max_tokens}")
        if key in cache:
            log("LLM cache hit", "INFO")
            return cache[key]

    payload = {
        "model": get_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    result = _api_call("chat/completions", payload)
    if result is None:
        return None

    try:
        content = result["choices"][0]["message"]["content"]
        
        # Save to cache
        if use_cache:
            cache = _load_cache()
            cache[key] = content
            _save_cache(cache)
        
        return content
    except (KeyError, IndexError) as e:
        log(f"LLM response format error: {e}", "WARN")
        return None


def embed(text: str, use_cache: bool = True) -> Optional[List[float]]:
    """Genera embedding para un texto.
    
    Returns:
        Lista de floats (embedding vector), o None si no disponible.
        Si no hay API de embeddings, retorna hash-based pseudo-embedding (384 dims).
    """
    if not is_available():
        return _hash_embedding(text)

    # Check cache
    if use_cache:
        cache = _load_cache()
        key = _cache_key([{"text": text}], "embed")
        if key in cache:
            return cache[key]

    payload = {
        "model": os.environ.get("APOLO_EMBED_MODEL", "text-embedding-ada-002"),
        "input": text,
    }

    result = _api_call("embeddings", payload)
    if result is None:
        # Fallback to hash embedding
        emb = _hash_embedding(text)
        if use_cache:
            cache = _load_cache()
            cache[key] = emb
            _save_cache(cache)
        return emb

    try:
        emb = result["data"][0]["embedding"]
        if use_cache:
            cache = _load_cache()
            cache[key] = emb
            _save_cache(cache)
        return emb
    except (KeyError, IndexError):
        return _hash_embedding(text)


def _hash_embedding(text: str, dims: int = 384) -> List[float]:
    """Genera pseudo-embedding determinista basado en hash (fallback sin API)."""
    h = hashlib.sha256(text.encode()).hexdigest()
    # Expandir hash a dims dimensiones
    result = []
    for i in range(0, dims, 8):
        chunk = h[i % 64:i % 64 + 8]
        result.append(int(chunk, 16) / 0xFFFFFFFF)
    return result[:dims]


def analyze_code(code: str, question: str) -> Optional[str]:
    """Usa LLM para analizar código."""
    messages = [
        {"role": "system", "content": "You are a code analysis expert. Analyze code and answer questions concisely."},
        {"role": "user", "content": f"Code:\n```\n{code[:3000]}\n```\n\nQuestion: {question}"},
    ]
    return chat(messages, temperature=0.1, max_tokens=1000)


def suggest_fix(error: str, context: str = "") -> Optional[str]:
    """Usa LLM para sugerir un fix para un error."""
    messages = [
        {"role": "system", "content": "You are a debugging expert. Suggest concise fixes for errors."},
        {"role": "user", "content": f"Error: {error[:500]}\n\nContext: {context[:1000]}\n\nSuggest a fix:"},
    ]
    return chat(messages, temperature=0.2, max_tokens=1000)


def generate_test(function_name: str, function_code: str, language: str) -> Optional[str]:
    """Usa LLM para generar un test significativo."""
    messages = [
        {"role": "system", "content": f"You are a test engineering expert for {language}. Generate concise, meaningful tests."},
        {"role": "user", "content": f"Generate a test for this {language} function:\n```{language}\n{function_code[:2000]}\n```\n\nFunction name: {function_name}\nGenerate only the test code, no explanations."},
    ]
    return chat(messages, temperature=0.3, max_tokens=1500)


def suggest_refactor(code: str, smell: str, language: str) -> Optional[str]:
    """Usa LLM para sugerir código refactorizado."""
    messages = [
        {"role": "system", "content": f"You are a refactoring expert for {language}. Provide only refactored code."},
        {"role": "user", "content": f"Refactor this {language} code. Issue: {smell}\n```{language}\n{code[:2000]}\n```\n\nProvide only the refactored code:"},
    ]
    return chat(messages, temperature=0.2, max_tokens=2000)


# ============================================================================
# Main (for CLI usage)
# ============================================================================

def main() -> int:
    from common import parse_args
    args = parse_args(sys.argv[1:])
    
    prompt = args.get("prompt", "")
    if not prompt:
        print(json.dumps({"available": is_available(), "model": get_model(), "api_base": get_api_base()}))
        return 0
    
    if not is_available():
        print(json.dumps({"error": "LLM no disponible. Configurar MINIMAX_API_KEY o OPENAI_API_KEY."}))
        return 1
    
    response = chat([{"role": "user", "content": prompt}])
    if response:
        print(response)
        return 0
    else:
        print(json.dumps({"error": "LLM call failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

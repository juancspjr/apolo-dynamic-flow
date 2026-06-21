#!/usr/bin/env python3
"""
generate_tests.py — Generación automática de tests (v2.6.0).

Encuentra funciones sin test y genera tests automáticamente.
Si LLM disponible, genera tests significativos. Si no, genera stubs deterministas.

Agnóstico al lenguaje: Python, TS/JS, Go, Java, Rust, PHP, C++.

Uso:
  python3 generate_tests.py --repo-root . --code-index CODE-INDEX.yaml --output /tmp/gen-tests/
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

LANG_CONFIG = {
    "py": {"test_prefix": "test_", "test_suffix": ".py", "import_fmt": "from {module} import {symbol}"},
    "ts": {"test_prefix": "", "test_suffix": ".test.ts", "import_fmt": "import {{ {symbol} }} from '{module}'"},
    "js": {"test_prefix": "", "test_suffix": ".test.js", "import_fmt": "const {{ {symbol} }} = require('{module}')"},
    "go": {"test_prefix": "", "test_suffix": "_test.go", "import_fmt": ""},
    "java": {"test_prefix": "", "test_suffix": "Test.java", "import_fmt": "import {module}.{symbol}"},
    "rs": {"test_prefix": "", "test_suffix": "_test.rs", "import_fmt": "use {module}::{symbol}"},
    "php": {"test_prefix": "", "test_suffix": "Test.php", "import_fmt": "use {module}\\{symbol}"},
}


def find_untested_symbols(code_index: Dict) -> List[Dict]:
    """Encuentra funciones exportadas sin test."""
    files = code_index.get("files", [])
    all_symbols = []
    
    for f in files:
        lang = f.get("language", "")
        if lang not in LANG_CONFIG:
            continue
        
        path = f.get("path", "")
        cfg = LANG_CONFIG[lang]
        stem = Path(path).stem
        
        # Buscar archivo de test correspondiente
        test_filename = f"{cfg['test_prefix']}{stem}{cfg['test_suffix']}"
        has_test = any(tf.get("path", "").endswith(test_filename) for tf in files)
        
        if has_test:
            continue
        
        for func in f.get("symbols", {}).get("functions", []):
            if func.get("is_exported"):
                all_symbols.append({
                    "file": path,
                    "language": lang,
                    "symbol": func.get("name", ""),
                    "args": func.get("args", []),
                    "line": func.get("line", 0),
                    "is_async": func.get("is_async", False),
                })
    
    return all_symbols


def generate_stub(symbol: Dict) -> str:
    """Genera test stub determinista."""
    lang = symbol["language"]
    name = symbol["symbol"]
    args = symbol.get("args", [])
    cfg = LANG_CONFIG.get(lang, LANG_CONFIG["py"])
    
    if lang == "py":
        return f"""# Auto-generated test stub (apolo-dynamic-flow v2.6.0)
# Source: {symbol['file']}:{symbol['line']}

import pytest


def test_{name}_exists():
    \"\"\"Verify {name} is callable.\"\"\"
    # TODO: import and test {name}({', '.join(args)})
    # from {Path(symbol['file']).stem} import {name}
    # result = {name}({', '.join(['None'] * len(args))})
    # assert result is not None
    pass


def test_{name}_with_none_args():
    \"\"\"Test {name} with None arguments.\"\"\"
    # TODO: implement
    pass
"""
    elif lang in ("ts", "js"):
        return f"""// Auto-generated test stub (apolo-dynamic-flow v2.6.0)
// Source: {symbol['file']}:{symbol['line']}

describe('{name}', () => {{
  it('should be defined', () => {{
    // TODO: import and test {name}
    // expect({name}).toBeDefined();
  }});

  it('should handle edge cases', () => {{
    // TODO: test with edge case inputs
  }});
}});
"""
    elif lang == "go":
        return f"""// Auto-generated test stub (apolo-dynamic-flow v2.6.0)
// Source: {symbol['file']}:{symbol['line']}

package main

import "testing"

func Test{name[0].upper() + name[1:]}(t *testing.T) {{
    // TODO: test {name}({', '.join(args)})
    // t.Skip("not implemented")
}}
"""
    else:
        return f"// Auto-generated test stub for {name} ({lang})\n// TODO: implement\n"


def generate_with_llm(symbol: Dict, code_snippet: str) -> Optional[str]:
    """Usa LLM para generar test significativo."""
    try:
        from llm_bridge import generate_test, is_available
        if not is_available():
            return None
        return generate_test(symbol["symbol"], code_snippet, symbol["language"])
    except ImportError:
        return None


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    output_dir = Path(args.get("output", "/tmp/gen-tests"))
    
    code_index = read_yaml(ci_path) or {}
    if not code_index.get("files"):
        log("CODE-INDEX vacío o no encontrado", "ERROR")
        return 2
    
    untested = find_untested_symbols(code_index)
    log(f"Encontrados {len(untested)} símbolos sin test", "INFO")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = 0
    
    for sym in untested[:20]:  # Limit to 20 to avoid explosion
        stub = generate_stub(sym)
        
        # Try LLM
        source_path = repo_root / sym["file"]
        code_snippet = ""
        if source_path.exists():
            try:
                lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(0, sym["line"] - 1)
                code_snippet = "\n".join(lines[start:start + 30])
            except Exception:
                pass
        
        llm_test = generate_with_llm(sym, code_snippet)
        if llm_test:
            stub = llm_test
        
        # Write test file
        lang = sym["language"]
        cfg = LANG_CONFIG.get(lang, LANG_CONFIG["py"])
        test_name = f"{cfg['test_prefix']}{sym['symbol']}{cfg['test_suffix']}"
        test_path = output_dir / test_name
        test_path.write_text(stub, encoding="utf-8")
        generated += 1
    
    log(f"Generados {generated} archivos de test", "INFO")
    print(json.dumps({"success": True, "untested": len(untested), "generated": generated, "output": str(output_dir)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

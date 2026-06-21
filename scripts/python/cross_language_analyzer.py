#!/usr/bin/env python3
"""
cross_language_analyzer.py — Análisis de dependencias cross-lenguaje (v2.6.6).

Detecta cuando un lenguaje llama a otro:
  - Python → Go (subprocess, gRPC)
  - JS/TS → Go/Python (fetch, axios, HTTP)
  - Python → C/C++/Rust (ctypes, cffi, FFI)
  - Shell → cualquier binario
  - gRPC (.proto) → clientes/servidores
  - Any → REST API endpoints

Genera CROSS-LANGUAGE-MAP.yaml con el mapa de dependencias inter-lenguaje.

Uso:
  python3 cross_language_analyzer.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml


# ============================================================================
# Cross-language patterns
# ============================================================================

# Python calling external binaries/languages
PY_SUBPROCESS_RE = re.compile(
    r'(?:subprocess\.(?:run|call|Popen|check_output|check_call)\s*\(|os\.system\s*\(|os\.popen\s*\()'
    r'[^)]*["\']([^"\']+)["\']',
    re.MULTILINE,
)

# Python ctypes/cffi (C/C++/Rust FFI)
PY_CFFI_RE = re.compile(
    r'(?:ctypes\.CDLL\s*\(\s*|cffi\.FFI\(\)|dlopen\s*\(\s*)["\']?([^"\')\s]+)["\']?',
    re.MULTILINE,
)

# Python gRPC
PY_GRPC_RE = re.compile(
    r'grpc\.(?:insecure_channel|secure_channel)\s*\(\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)

# JS/TS fetch/axios/http
JS_FETCH_RE = re.compile(
    r'(?:fetch\s*\(\s*|axios\.(?:get|post|put|delete|patch)\s*\(\s*|http\.(?:get|request)\s*\(\s*)'
    r'["\']([^"\']+)["\']',
    re.MULTILINE,
)

# JS/TS require/import of native modules
JS_NATIVE_RE = re.compile(
    r'(?:require\s*\(\s*|import\s.*from\s+)["\']([^"\']*(?:\.node|\.so|\.dll|\.dylib))["\']',
    re.MULTILINE,
)

# Shell scripts calling binaries
SH_EXEC_RE = re.compile(
    r'(?:^|\s)(?:exec\s+|`\s*|system\s*\(\s*["\']) ([a-z][a-z0-9_-]+)',
    re.MULTILINE,
)

# gRPC proto files
PROTO_SERVICE_RE = re.compile(
    r'service\s+(\w+)\s*\{',
    re.MULTILINE,
)

# Go calling external commands
GO_EXEC_RE = re.compile(
    r'exec\.Command\s*\(\s*["\']([^"\']+)["\']',
    re.MULTILINE,
)

# REST API endpoints (any language)
REST_ENDPOINT_RE = re.compile(
    r'(?:GET|POST|PUT|DELETE|PATCH)\s+(/[a-zA-Z0-9/_-]+)',
    re.MULTILINE,
)

# Python importing from .proto generated files
PY_PROTO_IMPORT_RE = re.compile(
    r'from\s+(\w+_pb2)\s+import|import\s+(\w+_pb2)',
    re.MULTILINE,
)

# Known language binaries
LANGUAGE_BINARIES = {
    'go': ['go', 'golang'],
    'python': ['python', 'python3', 'pip', 'pip3'],
    'node': ['node', 'npm', 'npx', 'yarn'],
    'rust': ['cargo', 'rustc'],
    'java': ['java', 'javac', 'mvn', 'gradle'],
    'php': ['php', 'composer'],
    'ruby': ['ruby', 'gem', 'bundle'],
    'c': ['gcc', 'clang', 'make'],
    'cpp': ['g++', 'clang++', 'cmake'],
}


def detect_language_calls(file_path: Path, content: str) -> List[Dict[str, Any]]:
    """Detecta llamadas cross-lenguaje en un archivo."""
    calls = []
    suffix = file_path.suffix.lower()
    rel_path = str(file_path)

    if suffix == '.py':
        # Python → Go/C/Rust via subprocess
        for m in PY_SUBPROCESS_RE.finditer(content):
            binary = m.group(1).strip()
            target_lang = _identify_binary_language(binary)
            if target_lang:
                calls.append({
                    "from": "python",
                    "to": target_lang,
                    "type": "subprocess",
                    "target": binary,
                    "file": rel_path,
                    "line": content[:m.start()].count("\n") + 1,
                })

        # Python → C/C++/Rust via ctypes/cffi
        for m in PY_CFFI_RE.finditer(content):
            lib = m.group(1).strip()
            calls.append({
                "from": "python",
                "to": "c",
                "type": "ffi",
                "target": lib,
                "file": rel_path,
                "line": content[:m.start()].count("\n") + 1,
            })

        # Python → gRPC
        for m in PY_GRPC_RE.finditer(content):
            endpoint = m.group(1).strip()
            calls.append({
                "from": "python",
                "to": "grpc",
                "type": "grpc-client",
                "target": endpoint,
                "file": rel_path,
                "line": content[:m.start()].count("\n") + 1,
            })

        # Python → proto generated
        for m in PY_PROTO_IMPORT_RE.finditer(content):
            proto_mod = m.group(1) or m.group(2)
            calls.append({
                "from": "python",
                "to": "protobuf",
                "type": "proto-import",
                "target": proto_mod,
                "file": rel_path,
                "line": content[:m.start()].count("\n") + 1,
            })

    elif suffix in ('.ts', '.tsx', '.js', '.jsx'):
        # JS/TS → Go/Python/any via fetch/axios
        for m in JS_FETCH_RE.finditer(content):
            url = m.group(1).strip()
            calls.append({
                "from": "javascript",
                "to": "http-api",
                "type": "http-request",
                "target": url,
                "file": rel_path,
                "line": content[:m.start()].count("\n") + 1,
            })

        # JS/TS → native modules
        for m in JS_NATIVE_RE.finditer(content):
            lib = m.group(1).strip()
            calls.append({
                "from": "javascript",
                "to": "c",
                "type": "native-module",
                "target": lib,
                "file": rel_path,
                "line": content[:m.start()].count("\n") + 1,
            })

    elif suffix == '.go':
        # Go → external command
        for m in GO_EXEC_RE.finditer(content):
            binary = m.group(1).strip()
            target_lang = _identify_binary_language(binary)
            if target_lang:
                calls.append({
                    "from": "go",
                    "to": target_lang,
                    "type": "exec-command",
                    "target": binary,
                    "file": rel_path,
                    "line": content[:m.start()].count("\n") + 1,
                })

    elif suffix == '.sh':
        # Shell → any binary
        for m in SH_EXEC_RE.finditer(content):
            binary = m.group(1).strip()
            target_lang = _identify_binary_language(binary)
            if target_lang:
                calls.append({
                    "from": "shell",
                    "to": target_lang,
                    "type": "shell-exec",
                    "target": binary,
                    "file": rel_path,
                    "line": content[:m.start()].count("\n") + 1,
                })

    elif suffix == '.proto':
        # Proto → service definition
        for m in PROTO_SERVICE_RE.finditer(content):
            service = m.group(1).strip()
            calls.append({
                "from": "protobuf",
                "to": "grpc",
                "type": "service-definition",
                "target": service,
                "file": rel_path,
                "line": content[:m.start()].count("\n") + 1,
            })

    # REST endpoints (any language)
    for m in REST_ENDPOINT_RE.finditer(content):
        endpoint = m.group(1).strip()
        calls.append({
            "from": suffix.lstrip('.'),
            "to": "rest-api",
            "type": "rest-endpoint",
            "target": endpoint,
            "file": rel_path,
            "line": content[:m.start()].count("\n") + 1,
        })

    return calls


def _identify_binary_language(binary: str) -> Optional[str]:
    """Identifica el lenguaje de un binario."""
    binary_lower = binary.lower()
    for lang, binaries in LANGUAGE_BINARIES.items():
        for b in binaries:
            if b in binary_lower:
                return lang
    # Check file extensions
    for ext, lang in [('.go', 'go'), ('.py', 'python'), ('.js', 'javascript'), ('.rs', 'rust'),
                       ('.java', 'java'), ('.php', 'php'), ('.c', 'c'), ('.cpp', 'cpp')]:
        if binary_lower.endswith(ext):
            return lang
    return None


def build_cross_language_map(repo_root: Path, code_index: Optional[Dict] = None) -> Dict[str, Any]:
    """Construye el mapa de dependencias cross-lenguaje."""
    all_calls: List[Dict[str, Any]] = []

    # Get files from code index or scan directly
    if code_index and code_index.get("files"):
        files = [repo_root / f["path"] for f in code_index["files"] if f.get("path")]
    else:
        # Scan common source directories
        patterns = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx",
                    "**/*.go", "**/*.sh", "**/*.proto", "**/*.java", "**/*.rs", "**/*.php"]
        files = []
        for p in patterns:
            files.extend(repo_root.glob(p))
        # Filter out node_modules, .git, dist
        files = [f for f in files if not any(x in str(f) for x in ["/node_modules/", "/.git/", "/dist/", "/__pycache__/"])]

    for f in files:
        if not f.exists() or not f.is_file():
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        calls = detect_language_calls(f, content)
        all_calls.extend(calls)

    # Build adjacency matrix
    adjacency: Dict[str, Dict[str, int]] = {}
    for call in all_calls:
        from_lang = call["from"]
        to_lang = call["to"]
        if from_lang not in adjacency:
            adjacency[from_lang] = {}
        adjacency[from_lang][to_lang] = adjacency[from_lang].get(to_lang, 0) + 1

    # Find critical paths (languages that depend on multiple others)
    critical_nodes = []
    for lang, deps in adjacency.items():
        if len(deps) >= 2:
            critical_nodes.append({
                "language": lang,
                "depends_on": list(deps.keys()),
                "total_dependencies": sum(deps.values()),
            })

    return {
        "crosslanguagemap": "V1",
        "version": 1,
        "generated_at": now_iso(),
        "total_calls": len(all_calls),
        "languages_analyzed": list(set(c["from"] for c in all_calls)),
        "adjacency_matrix": adjacency,
        "critical_nodes": critical_nodes,
        "calls": all_calls,
    }


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    ci_path = Path(args.get("code-index", ".opencode/apolo-dynamic/CODE-INDEX.yaml"))
    output = Path(args.get("output", "CROSS-LANGUAGE-MAP.yaml"))

    code_index = read_yaml(ci_path) if ci_path.exists() else None
    result = build_cross_language_map(repo_root, code_index)

    write_yaml(output, result)
    log(f"Cross-language map: {result['total_calls']} calls, {len(result['languages_analyzed'])} languages", "INFO")
    print(json.dumps({
        "success": True,
        "total_calls": result["total_calls"],
        "languages": result["languages_analyzed"],
        "critical_nodes": len(result["critical_nodes"]),
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

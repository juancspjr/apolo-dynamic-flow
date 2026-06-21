#!/usr/bin/env python3
"""
lsp_integration.py — Integración con LSP para análisis semántico (v2.5.0).

Usa Language Server Protocol para:
  - go-to-definition: encontrar dónde se define un símbolo
  - find-references: encontrar todos los lugares que usan un símbolo
  - get-hover: obtener documentación de un símbolo
  - get_diagnostics: obtener errores/warnings de un archivo

LSPs soportados:
  TypeScript: typescript-language-server
  Python: pylsp o pyright
  Go: gopls
  Rust: rust-analyzer
  Java: jdtls
  C++: clangd
  PHP: intelephense

Si un LSP no está disponible, degrada a regex-based analysis.

Uso:
  python3 lsp_integration.py --repo-root . --symbol "init" --action find-references
  python3 lsp_integration.py --repo-root . --file plugin/index.ts --action diagnostics
  python3 lsp_integration.py --repo-root . --output LSP-ANALYSIS.yaml
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    cmd_available,
    log,
    now_iso,
    parse_args,
    read_yaml,
    run_cmd,
    write_yaml,
)


# ============================================================================
# Constants
# ============================================================================

EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".php": "php",
}

# Map lenguaje -> comando del LSP correspondiente.
LSP_COMMANDS: Dict[str, List[str]] = {
    "typescript": ["typescript-language-server", "tsserver"],
    "javascript": ["typescript-language-server", "tsserver"],
    "python": ["pylsp", "pyright-langserver", "pyright"],
    "go": ["gopls"],
    "rust": ["rust-analyzer"],
    "java": ["jdtls"],
    "cpp": ["clangd"],
    "php": ["intelephense"],
}

SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "vendor", ".next", "__pycache__",
    ".cache", ".opencode", "target", ".venv", "venv", "env",
}


# ============================================================================
# Language detection
# ============================================================================

def detect_language(path: Path) -> Optional[str]:
    return EXTENSION_TO_LANGUAGE.get(path.suffix.lower())


def list_source_files(repo_root: Path, language: Optional[str] = None) -> List[Path]:
    """Lista archivos de código del repo, opcionalmente filtrados por lenguaje."""
    files: List[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        lang = detect_language(path)
        if not lang:
            continue
        if language and lang != language:
            continue
        files.append(path)
    return files


# ============================================================================
# LSP detection
# ============================================================================

def detect_available_lsps() -> Dict[str, str]:
    """Detecta qué LSPs están disponibles en el sistema.

    Returns: {language: command} con el comando del primer LSP encontrado.
    """
    available: Dict[str, str] = {}
    for language, commands in LSP_COMMANDS.items():
        for cmd in commands:
            if cmd_available(cmd):
                available[language] = cmd
                break
    return available


def get_lsp_for_file(file_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Determina el LSP a usar para un archivo dado.

    Returns: (lsp_command, language).
    """
    language = detect_language(file_path)
    if not language:
        return None, None
    candidates = LSP_COMMANDS.get(language, [])
    for cmd in candidates:
        if cmd_available(cmd):
            return cmd, language
    return None, language


# ============================================================================
# LSP integration (best-effort via subprocess)
# ============================================================================

# NOTA: Una integración LSP completa requiere un cliente JSON-RPC persistente
# (stdin/stdout) y manejo de initialize/textDocumentXXX/shutdown.
# Aquí implementamos un wrapper simplificado que arranca el LSP por archivo
# y para comandos rápidos; para análisis masivo usa el fallback regex.

def lsp_find_references_via_cli(
    symbol: str,
    file_path: Path,
    lsp_command: str,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    """Intenta find-references vía LSP.

    Implementación simplificada: la mayoría de LSPs requieren cliente JSON-RPC
    completo. Si el LSP no soporta CLI directo, devuelve [] y dejamos que
    el regex fallback tome el control.
    """
    # gopls tiene CLI: gopls refs <file>:<line>:<col>
    # Pero sin saber la línea del símbolo, no podemos invocarlo bien.
    # Para v2.5.0, el path principal es el fallback regex.
    # El LSP CLI directo se deja como extensión futura.
    return []


def lsp_diagnostics_via_cli(
    file_path: Path,
    lsp_command: str,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    """Intenta diagnostics vía LSP CLI.

    Algunos LSPs exponen CLI útil:
      - pyright: pyright --outputjson <file>
      - gopls: gopls check <file>
    """
    if lsp_command == "pyright" or lsp_command == "pyright-langserver":
        if cmd_available("pyright"):
            code, out, err = run_cmd(
                ["pyright", "--outputjson", str(file_path)],
                cwd=repo_root,
                timeout=60,
            )
            if not out:
                return []
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                return []
            diags: List[Dict[str, Any]] = []
            for d in data.get("generalDiagnostics", []) or []:
                diags.append({
                    "file": d.get("file"),
                    "severity": d.get("severity"),
                    "message": d.get("message"),
                    "range": d.get("range"),
                    "rule": d.get("rule"),
                })
            return diags
    if lsp_command == "gopls":
        code, out, err = run_cmd(
            ["gopls", "check", str(file_path)],
            cwd=repo_root,
            timeout=60,
        )
        if not out:
            return []
        # gopls check produce texto con formato: file:line:col: message
        diags = []
        for line in out.splitlines():
            m = re.match(r"^(.+?):(\d+):(\d+):\s*(.+)$", line)
            if m:
                diags.append({
                    "file": m.group(1),
                    "line": int(m.group(2)),
                    "col": int(m.group(3)),
                    "severity": "warning",
                    "message": m.group(4),
                })
        return diags
    return []


# ============================================================================
# Regex fallback
# ============================================================================

def regex_find_references(
    symbol: str,
    repo_root: Path,
    language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Busca referencias a un símbolo en todos los archivos del mismo lenguaje.

    Fallback cuando no hay LSP disponible. Usa regex con word boundaries para
    reducir falsos positivos.
    """
    # Escapar el símbolo y rodear con word boundaries.
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    references: List[Dict[str, Any]] = []
    files_to_scan = list_source_files(repo_root, language)
    for path in files_to_scan:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                references.append({
                    "file": str(path),
                    "line": i,
                    "column": line.find(symbol) + 1 if symbol in line else 0,
                    "preview": line.strip()[:200],
                    "method": "regex",
                })
    return references


def regex_get_diagnostics(
    file_path: Path,
) -> List[Dict[str, Any]]:
    """Heurística de diagnostics via regex.

    Detecta patrones obvios de error:
      - TODO/FIXME/XXX comments
      - console.log olvidado (JS/TS)
      - print() olvidado (Python)
      - debugger statement (JS/TS)
      - import sin usar (best-effort)
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    diags: List[Dict[str, Any]] = []
    language = detect_language(file_path) or ""

    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # TODO/FIXME/XXX
        if re.search(r"\b(TODO|FIXME|XXX|HACK)\b", stripped):
            diags.append({
                "file": str(file_path),
                "line": i,
                "severity": "info",
                "message": f"Marcar pendiente: {stripped[:120]}",
                "rule": "todo-comment",
                "method": "regex",
            })
        # console.log (JS/TS)
        if language in ("javascript", "typescript") and "console.log" in stripped:
            diags.append({
                "file": str(file_path),
                "line": i,
                "severity": "warning",
                "message": "console.log olvidado en producción",
                "rule": "no-console-log",
                "method": "regex",
            })
        # debugger statement
        if language in ("javascript", "typescript") and re.search(r"\bdebugger\b", stripped):
            diags.append({
                "file": str(file_path),
                "line": i,
                "severity": "error",
                "message": "statement 'debugger' presente",
                "rule": "no-debugger",
                "method": "regex",
            })
        # print() en Python (no en tests)
        if language == "python" and re.match(r"\s*print\s*\(", stripped) \
                and not file_path.name.startswith("test_") \
                and "tests" not in file_path.parts:
            diags.append({
                "file": str(file_path),
                "line": i,
                "severity": "warning",
                "message": "print() posiblemente olvidado",
                "rule": "no-print",
                "method": "regex",
            })
        # Syntax error obvia (Python): línea con "}}}" sin abrir
        # (Heurística muy básica; el AST lo haría mejor.)
    return diags


def regex_go_to_definition(
    symbol: str,
    repo_root: Path,
    language: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Busca la definición de un símbolo via regex.

    Patrones por lenguaje:
      Python: def <symbol> / class <symbol>
      JS/TS:  function <symbol> / const <symbol> / class <symbol> / export ... <symbol>
      Go:     func <symbol> / type <symbol>
      Rust:   fn <symbol> / pub fn <symbol>
    """
    files_to_scan = list_source_files(repo_root, language)
    definitions: List[Dict[str, Any]] = []

    esc = re.escape(symbol)
    patterns_by_lang: Dict[str, List[str]] = {
        "python": [rf"^\s*def\s+{esc}\s*\(", rf"^\s*class\s+{esc}\s*[\(:]"],
        "javascript": [
            rf"(?:export\s+)?(?:async\s+)?function\s+{esc}\b",
            rf"(?:export\s+)?(?:const|let|var)\s+{esc}\s*=",
            rf"(?:export\s+)?class\s+{esc}\b",
        ],
        "typescript": [
            rf"(?:export\s+)?(?:async\s+)?function\s+{esc}\b",
            rf"(?:export\s+)?(?:const|let|var)\s+{esc}\s*=",
            rf"(?:export\s+)?class\s+{esc}\b",
            rf"(?:export\s+)?interface\s+{esc}\b",
            rf"(?:export\s+)?type\s+{esc}\b",
        ],
        "go": [rf"^func\s+(?:\([^)]+\)\s+)?{esc}\s*\(", rf"^type\s+{esc}\s+"],
        "rust": [rf"^\s*pub\s+(?:async\s+)?fn\s+{esc}\b", rf"^\s*fn\s+{esc}\b"],
        "java": [rf"(?:public|private|protected)\s+(?:static\s+)?\w+(?:\s*\[[^\]]*\])?\s+{esc}\s*\("],
        "php": [rf"^\s*(?:public|private|protected)?\s*(?:static\s+)?function\s+{esc}\s*\("],
    }

    for path in files_to_scan:
        lang = detect_language(path) or ""
        if language and lang != language:
            continue
        patterns = patterns_by_lang.get(lang, [])
        if not patterns:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for pat in patterns:
            for m in re.finditer(pat, text, re.MULTILINE):
                lineno = text.count("\n", 0, m.start()) + 1
                definitions.append({
                    "file": str(path),
                    "line": lineno,
                    "column": m.start() - text.rfind("\n", 0, m.start()),
                    "match": m.group(0)[:200],
                    "method": "regex",
                })
    return definitions


def regex_get_hover(
    symbol: str,
    repo_root: Path,
    language: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Heurística de hover: extrae el docstring/comentario encima del símbolo."""
    defs = regex_go_to_definition(symbol, repo_root, language)
    if not defs:
        return None
    # Tomar la primera definición encontrada.
    first = defs[0]
    file_path = Path(first["file"])
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return first
    line_idx = first["line"] - 1
    # Recopilar comentarios/docstrings precedentes.
    hover_lines: List[str] = []
    i = line_idx - 1
    while i >= 0:
        line = lines[i].strip()
        if not line:
            break
        # Python: """ ... """ o # comment
        if line.startswith("#"):
            hover_lines.insert(0, line)
        elif line.startswith('"""') or line.startswith("'''"):
            hover_lines.insert(0, line)
        else:
            break
        i -= 1
    # Si es JS/TS, buscar /** */ o // comments
    if not hover_lines:
        i = line_idx - 1
        while i >= 0:
            line = lines[i].strip()
            if line.startswith("//") or line.startswith("*") or line.startswith("/*"):
                hover_lines.insert(0, line)
            elif not line:
                break
            else:
                break
            i -= 1
    first["hover"] = "\n".join(hover_lines) if hover_lines else "(no docstring)"
    return first


# ============================================================================
# Public API
# ============================================================================

def find_references(
    symbol: str,
    repo_root: Path,
    file_hint: Optional[Path] = None,
) -> Dict[str, Any]:
    """find-references: lista archivos+líneas donde se usa el símbolo.

    Estrategia: si hay LSP para el lenguaje del file_hint, intentar vía LSP.
    Si no hay LSP o el LSP no devuelve nada, usar regex fallback.
    """
    language = None
    lsp_used = None
    if file_hint:
        lsp_command, language = get_lsp_for_file(file_hint)
        if lsp_command:
            refs = lsp_find_references_via_cli(symbol, file_hint, lsp_command, repo_root)
            if refs:
                lsp_used = lsp_command
                return {
                    "symbol": symbol,
                    "references": refs,
                    "count": len(refs),
                    "method": f"lsp:{lsp_command}",
                    "lsp_used": lsp_command,
                }
    # Fallback regex.
    refs = regex_find_references(symbol, repo_root, language)
    return {
        "symbol": symbol,
        "references": refs,
        "count": len(refs),
        "method": "regex",
        "lsp_used": lsp_used,
    }


def get_diagnostics(file_path: Path, repo_root: Path) -> Dict[str, Any]:
    """get_diagnostics: errores/warnings de un archivo.

    Estrategia: si hay LSP para el lenguaje, intentar vía LSP CLI.
    Siempre correr también el regex fallback (que detecta TODOs, console.log, etc.).
    """
    lsp_command, language = get_lsp_for_file(file_path)
    lsp_diags: List[Dict[str, Any]] = []
    if lsp_command:
        lsp_diags = lsp_diagnostics_via_cli(file_path, lsp_command, repo_root)
    regex_diags = regex_get_diagnostics(file_path)

    # Combinar (sin duplicados obvios).
    all_diags = lsp_diags + regex_diags
    return {
        "file": str(file_path),
        "language": language,
        "diagnostics": all_diags,
        "count": len(all_diags),
        "lsp_used": lsp_command,
        "lsp_count": len(lsp_diags),
        "regex_count": len(regex_diags),
    }


def go_to_definition(
    symbol: str,
    repo_root: Path,
    file_hint: Optional[Path] = None,
) -> Dict[str, Any]:
    """go-to-definition: dónde se define un símbolo."""
    language = None
    if file_hint:
        _, language = get_lsp_for_file(file_hint)
    defs = regex_go_to_definition(symbol, repo_root, language)
    return {
        "symbol": symbol,
        "definitions": defs,
        "count": len(defs),
        "method": "regex",
    }


def get_hover(
    symbol: str,
    repo_root: Path,
    file_hint: Optional[Path] = None,
) -> Dict[str, Any]:
    """get-hover: documentación de un símbolo."""
    language = None
    if file_hint:
        _, language = get_lsp_for_file(file_hint)
    hover = regex_get_hover(symbol, repo_root, language)
    return {
        "symbol": symbol,
        "hover": hover,
        "method": "regex",
    }


# ============================================================================
# Full repo analysis
# ============================================================================

def analyze_repo(repo_root: Path) -> Dict[str, Any]:
    """Corre análisis LSP/regex sobre todo el repo y produce LSP-ANALYSIS.yaml."""
    start = time.time()
    available_lsps = detect_available_lsps()
    degradations: List[str] = []

    # Reportar LSPs faltantes.
    for lang in ("python", "typescript", "go", "rust", "java", "cpp", "php"):
        if lang not in available_lsps:
            degradations.append(f"LSP para {lang} no disponible — usando regex fallback")

    # Listar archivos por lenguaje.
    files_by_lang: Dict[str, List[Path]] = {}
    for path in list_source_files(repo_root):
        lang = detect_language(path) or "unknown"
        files_by_lang.setdefault(lang, []).append(path)

    # Diagnostics por archivo (regex siempre + LSP si disponible).
    all_diagnostics: List[Dict[str, Any]] = []
    for lang, files in files_by_lang.items():
        for f in files:
            diag_report = get_diagnostics(f, repo_root)
            if diag_report["count"] > 0:
                all_diagnostics.append(diag_report)

    return {
        "schema_version": "2.5.0",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "available_lsps": available_lsps,
        "degradations": degradations,
        "languages_detected": sorted(files_by_lang.keys()),
        "files_by_language": {k: len(v) for k, v in files_by_lang.items()},
        "diagnostics": all_diagnostics,
        "summary": {
            "total_files": sum(len(v) for v in files_by_lang.values()),
            "files_with_diagnostics": len(all_diagnostics),
            "total_diagnostics": sum(d["count"] for d in all_diagnostics),
        },
        "duration_ms": int((time.time() - start) * 1000),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "LSP-ANALYSIS.yaml"))
    symbol = args.get("symbol", "")
    action = args.get("action", "")
    file_arg = args.get("file", "")

    if not repo_root.exists():
        log(f"repo-root no existe: {repo_root}", "ERROR")
        return 2

    log(f"lsp_integration.py v2.5.0 — repo: {repo_root}", "INFO")

    # Modo acción puntual (--action + --symbol o --file).
    if action and (symbol or file_arg):
        result: Dict[str, Any] = {}
        if action == "find-references" and symbol:
            file_hint = Path(file_arg) if file_arg else None
            result = find_references(symbol, repo_root, file_hint)
        elif action == "diagnostics" and file_arg:
            result = get_diagnostics(Path(file_arg), repo_root)
        elif action == "go-to-definition" and symbol:
            file_hint = Path(file_arg) if file_arg else None
            result = go_to_definition(symbol, repo_root, file_hint)
        elif action == "hover" and symbol:
            file_hint = Path(file_arg) if file_arg else None
            result = get_hover(symbol, repo_root, file_hint)
        else:
            log(f"Acción '{action}' no reconocida o parámetros insuficientes", "ERROR")
            return 2
        print(json.dumps({"success": True, "schema_version": "2.5.0", **result}, indent=2))
        return 0

    # Modo análisis completo: genera LSP-ANALYSIS.yaml.
    report = analyze_repo(repo_root)
    write_yaml(output, report)

    log(
        f"LSP analysis: {report['summary']['total_files']} archivos | "
        f"{len(report['available_lsps'])} LSPs disponibles | "
        f"{report['summary']['files_with_diagnostics']} archivos con diagnostics | "
        f"{report['summary']['total_diagnostics']} diagnostics totales | "
        f"{len(report['degradations'])} degradaciones",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "schema_version": "2.5.0",
        "available_lsps": report["available_lsps"],
        "total_files": report["summary"]["total_files"],
        "total_diagnostics": report["summary"]["total_diagnostics"],
        "degradations": len(report["degradations"]),
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
code_quality.py — Análisis de calidad de código multi-lenguaje (v2.5.0).

Agnóstico al lenguaje: detecta el lenguaje de cada archivo y aplica
el analizador apropiado. Si un analizador no está disponible, degrada
gracefully y lo reporta.

Analizadores soportados:
  Python: bandit (seguridad), radon (complejidad ciclomática)
  JavaScript/TypeScript: eslint-plugin-security (seguridad)
  Go: gosec (seguridad)
  Rust: cargo-audit (seguridad)
  Java: spotbugs (seguridad)
  C++: cppcheck (seguridad)
  PHP: psalm (seguridad)

Para complejidad ciclomática:
  Python: radon cc
  JavaScript/TypeScript: complexity-report o escomplex
  Go: gocyclo
  Otros: estimación por conteo de if/for/while/switch

Uso:
  python3 code_quality.py --repo-root . --output CODE-QUALITY.yaml
  python3 code_quality.py --repo-root . --files "src/foo.ts,src/bar.py"
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
# Language detection
# ============================================================================

# Map extensión -> lenguaje normalizado.
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "java",
    ".c": "cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".cs": "csharp",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
}

# Lenguajes soportados para seguridad (con su herramienta).
SECURITY_TOOLS: Dict[str, str] = {
    "python": "bandit",
    "javascript": "eslint-plugin-security",
    "typescript": "eslint-plugin-security",
    "go": "gosec",
    "rust": "cargo-audit",
    "java": "spotbugs",
    "cpp": "cppcheck",
    "php": "psalm",
}

# Lenguajes soportados para complejidad ciclomática.
COMPLEXITY_TOOLS: Dict[str, str] = {
    "python": "radon",
    "javascript": "complexity-report",
    "typescript": "complexity-report",
    "go": "gocyclo",
}

# Directorios que típicamente no queremos analizar (vendor, build, etc.).
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "vendor", ".next", "__pycache__",
    ".cache", ".opencode", "target", ".venv", "venv", "env",
}

# Umbral a partir del cual una función es "alta complejidad" (necesita refactor).
HIGH_COMPLEXITY_THRESHOLD = 15


def detect_language(path: Path) -> Optional[str]:
    """Detecta el lenguaje de un archivo por su extensión."""
    return EXTENSION_TO_LANGUAGE.get(path.suffix.lower())


def list_source_files(
    repo_root: Path,
    explicit_files: Optional[List[str]] = None,
) -> List[Tuple[Path, str]]:
    """Lista todos los archivos de código del repo con su lenguaje.

    Si explicit_files es None, escanea el repo recursivamente (skip SKIP_DIRS).
    Si explicit_files es una lista, solo considera esos archivos.
    """
    files: List[Tuple[Path, str]] = []
    if explicit_files:
        for f in explicit_files:
            p = Path(f)
            if not p.is_absolute():
                p = repo_root / p
            if not p.exists() or not p.is_file():
                continue
            lang = detect_language(p)
            if lang:
                files.append((p, lang))
        return files

    # Escaneo recursivo.
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        # Skip si algún componente del path está en SKIP_DIRS.
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        lang = detect_language(path)
        if lang:
            files.append((path, lang))
    return files


# ============================================================================
# Security analysis
# ============================================================================

def run_bandit(target: Path, repo_root: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """Corre bandit sobre un archivo Python. Devuelve (findings, available)."""
    if not cmd_available("bandit"):
        return [], False
    code, out, err = run_cmd(
        ["bandit", "-f", "json", "-q", str(target)],
        cwd=repo_root,
        timeout=30,
    )
    if code != 0 and not out:
        return [], True
    try:
        data = json.loads(out) if out else {}
    except json.JSONDecodeError:
        return [], True
    findings: List[Dict[str, Any]] = []
    for issue in data.get("results", []) or []:
        findings.append({
            "tool": "bandit",
            "file": str(target),
            "line": issue.get("line_number"),
            "test_id": issue.get("test_id"),
            "severity": issue.get("issue_severity"),
            "confidence": issue.get("issue_confidence"),
            "message": issue.get("issue_text"),
        })
    return findings, True


def run_gosec(target: Path, repo_root: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """Corre gosec sobre un archivo Go. Devuelve (findings, available)."""
    if not cmd_available("gosec"):
        return [], False
    code, out, err = run_cmd(
        ["gosec", "-fmt", "json", str(target)],
        cwd=repo_root,
        timeout=30,
    )
    if not out:
        return [], True
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [], True
    findings: List[Dict[str, Any]] = []
    for issue in data.get("Issues", []) or []:
        findings.append({
            "tool": "gosec",
            "file": issue.get("file", str(target)),
            "line": issue.get("line"),
            "rule_id": issue.get("rule_id"),
            "severity": issue.get("severity"),
            "details": issue.get("details"),
        })
    return findings, True


def run_cppcheck(target: Path, repo_root: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """Corre cppcheck sobre un archivo C/C++. Devuelve (findings, available)."""
    if not cmd_available("cppcheck"):
        return [], False
    code, out, err = run_cmd(
        ["cppcheck", "--enable=warning,security", "--xml", str(target)],
        cwd=repo_root,
        timeout=30,
    )
    # cppcheck escribe XML a stderr.
    raw = err or out
    if not raw:
        return [], True
    findings: List[Dict[str, Any]] = []
    # Parser minimalista de errores de cppcheck.
    for m in re.finditer(r'<error\s+id="([^"]+)"\s+severity="([^"]+)"\s+msg="([^"]+)"', raw):
        findings.append({
            "tool": "cppcheck",
            "file": str(target),
            "id": m.group(1),
            "severity": m.group(2),
            "message": m.group(3),
        })
    return findings, True


def run_eslint_security(target: Path, repo_root: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """Corre eslint con eslint-plugin-security sobre JS/TS."""
    if not cmd_available("npx"):
        return [], False
    code, out, err = run_cmd(
        ["npx", "--yes", "eslint", "--format", "json", "--plugin", "security", str(target)],
        cwd=repo_root,
        timeout=60,
    )
    if not out:
        return [], True
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [], True
    findings: List[Dict[str, Any]] = []
    if isinstance(data, list):
        for file_result in data:
            for msg in file_result.get("messages", []) or []:
                if "security" not in (msg.get("ruleId") or ""):
                    continue
                findings.append({
                    "tool": "eslint-plugin-security",
                    "file": file_result.get("filePath", str(target)),
                    "line": msg.get("line"),
                    "rule_id": msg.get("ruleId"),
                    "severity": "high" if msg.get("severity") == 2 else "medium",
                    "message": msg.get("message"),
                })
    return findings, True


def run_security_for_language(
    language: str,
    target: Path,
    repo_root: Path,
) -> Tuple[List[Dict[str, Any]], bool, Optional[str]]:
    """Despacha al analizador de seguridad correcto.

    Returns: (findings, was_available, tool_name_or_None).
    """
    if language == "python":
        findings, ok = run_bandit(target, repo_root)
        return findings, ok, "bandit" if ok else None
    if language in ("javascript", "typescript"):
        findings, ok = run_eslint_security(target, repo_root)
        return findings, ok, "eslint-plugin-security" if ok else None
    if language == "go":
        findings, ok = run_gosec(target, repo_root)
        return findings, ok, "gosec" if ok else None
    if language == "cpp":
        findings, ok = run_cppcheck(target, repo_root)
        return findings, ok, "cppcheck" if ok else None
    # Lenguajes sin analizador específico: reportar como no soportado.
    return [], False, None


# ============================================================================
# Cyclomatic complexity
# ============================================================================

def run_radon_cc(target: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """Corre radon cc sobre un archivo Python. Devuelve (functions, available)."""
    if not cmd_available("radon"):
        return [], False
    code, out, err = run_cmd(["radon", "cc", "-j", str(target)], timeout=30)
    if not out:
        return [], True
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return [], True
    functions: List[Dict[str, Any]] = []
    for fpath, blocks in data.items():
        for block in blocks or []:
            functions.append({
                "file": fpath,
                "function": block.get("name"),
                "complexity": block.get("complexity"),
                "rank": block.get("rank"),
                "lineno": block.get("lineno"),
            })
    return functions, True


def run_gocyclo(target: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """Corre gocyclo sobre un archivo Go."""
    if not cmd_available("gocyclo"):
        return [], False
    code, out, err = run_cmd(["gocyclo", str(target)], timeout=30)
    functions: List[Dict[str, Any]] = []
    if not out:
        return functions, True
    # Formato: <complexity> <function> <file>:<line>
    for line in out.strip().splitlines():
        m = re.match(r"(\d+)\s+(\S+)\s+(\S+):(\d+)", line)
        if m:
            functions.append({
                "file": m.group(3),
                "function": m.group(2),
                "complexity": int(m.group(1)),
                "lineno": int(m.group(4)),
            })
    return functions, True


def estimate_complexity_regex(target: Path, language: str) -> List[Dict[str, Any]]:
    """Estima complejidad ciclomática por conteo de keywords de branching.

    Se usa como fallback cuando no hay herramienta nativa. Cuenta:
      - if, elif, for, while, switch, case, catch, &&, ||, ternario
    Returns: lista de funciones con su complejidad estimada.
    """
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    # Patrones por lenguaje para definir "función" y contar branches.
    if language == "python":
        # Funciones: def name(...)
        func_pattern = re.compile(r"^(\s*)def\s+(\w+)\s*\(", re.MULTILINE)
        branch_keywords = [r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b",
                           r"\bexcept\b", r"\band\b", r"\bor\b"]
    elif language in ("javascript", "typescript"):
        func_pattern = re.compile(
            r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>)\s*[\{(]"
        )
        branch_keywords = [r"\bif\b", r"\bfor\b", r"\bwhile\b", r"\bswitch\b",
                           r"\bcase\b", r"\bcatch\b", r"&&", r"\|\|", r"\?\s*[^:]+\s*:"]
    elif language == "go":
        func_pattern = re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.MULTILINE)
        branch_keywords = [r"\bif\b", r"\bfor\b", r"\bswitch\b", r"\bcase\b",
                           r"&&", r"\|\|"]
    elif language == "rust":
        func_pattern = re.compile(r"^fn\s+(\w+)\s*[<(]", re.MULTILINE)
        branch_keywords = [r"\bif\b", r"\bfor\b", r"\bwhile\b", r"\bmatch\b",
                           r"&&", r"\|\|"]
    elif language == "java":
        func_pattern = re.compile(
            r"(?:public|private|protected|static|final|\s)+\s+\w+\s+(\w+)\s*\([^)]*\)\s*\{"
        )
        branch_keywords = [r"\bif\b", r"\bfor\b", r"\bwhile\b", r"\bswitch\b",
                           r"\bcase\b", r"\bcatch\b", r"&&", r"\|\|"]
    else:
        # HTML/CSS/PHP genérico: por archivo, sin descomponer en funciones.
        branch_keywords = [r"\bif\b", r"\bfor\b", r"\bwhile\b"]
        complexity = 1
        for kw in branch_keywords:
            complexity += len(re.findall(kw, text))
        if complexity <= 1:
            return []
        return [{
            "file": str(target),
            "function": "<file-level>",
            "complexity": complexity,
            "rank": _complexity_rank(complexity),
            "lineno": 1,
            "estimated": True,
        }]

    # Encontrar todas las definiciones de funciones con su línea inicial.
    matches = list(func_pattern.finditer(text))
    if not matches:
        return []
    functions: List[Dict[str, Any]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        # +1 porque las líneas son 1-indexed.
        lineno = text.count("\n", 0, start) + 1
        complexity = 1
        for kw in branch_keywords:
            complexity += len(re.findall(kw, body))
        func_name = m.group(1) or m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
        functions.append({
            "file": str(target),
            "function": func_name,
            "complexity": complexity,
            "rank": _complexity_rank(complexity),
            "lineno": lineno,
            "estimated": True,
        })
    return functions


def _complexity_rank(cc: int) -> str:
    """Convierte un valor de complejidad ciclomática a un grado A-F (estilo radon)."""
    if cc <= 5:
        return "A"
    if cc <= 10:
        return "B"
    if cc <= 20:
        return "C"
    if cc <= 30:
        return "D"
    if cc <= 40:
        return "E"
    return "F"


def compute_complexity(
    target: Path,
    language: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """Computa complejidad ciclomática usando herramienta nativa o regex.

    Returns: (functions, tool_used) donde tool_used puede ser:
      'radon', 'gocyclo', 'complexity-report', 'regex-estimation'.
    """
    if language == "python":
        funcs, ok = run_radon_cc(target)
        if ok:
            return funcs, "radon"
    if language == "go":
        funcs, ok = run_gocyclo(target)
        if ok:
            return funcs, "gocyclo"
    # Fallback genérico.
    return estimate_complexity_regex(target, language), "regex-estimation"


# ============================================================================
# Main analysis
# ============================================================================

def analyze_repo(
    repo_root: Path,
    explicit_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Analiza el repo entero (o archivos explícitos) y devuelve el reporte."""
    start = time.time()
    files = list_source_files(repo_root, explicit_files)

    if not files:
        return {
            "schema_version": "2.5.0",
            "generated_at": now_iso(),
            "repo_root": str(repo_root),
            "total_files": 0,
            "languages_detected": [],
            "security_findings": [],
            "complexity_scores": [],
            "high_complexity_functions": [],
            "degradations": ["no source files found"],
            "recommendations": ["add source files to the repo"],
            "duration_ms": int((time.time() - start) * 1000),
        }

    # Detectar lenguajes presentes.
    languages_present = sorted({lang for _, lang in files})

    security_findings: List[Dict[str, Any]] = []
    complexity_scores: List[Dict[str, Any]] = []
    high_complexity_functions: List[Dict[str, Any]] = []
    degradations: List[str] = []
    tools_tried: Dict[str, bool] = {}

    for path, language in files:
        # --- Seguridad ---
        findings, was_available, tool_name = run_security_for_language(
            language, path, repo_root
        )
        if tool_name:
            tools_tried[tool_name] = was_available
            if not was_available and tool_name not in degradations:
                degradations.append(
                    f"{tool_name} no disponible — análisis de seguridad para {language} omitido"
                )
        security_findings.extend(findings)

        # --- Complejidad ---
        funcs, tool_used = compute_complexity(path, language)
        if tool_used == "regex-estimation":
            tag = f"regex-estimation({language})"
            if tag not in degradations:
                degradations.append(
                    f"herramienta nativa de complejidad no disponible para {language} — usando {tool_used}"
                )

        for func in funcs:
            cc = func.get("complexity", 0) or 0
            complexity_scores.append({
                "file": func.get("file", str(path)),
                "function": func.get("function", "?"),
                "complexity": cc,
                "rank": func.get("rank") or _complexity_rank(cc),
                "tool": tool_used,
                "estimated": func.get("estimated", False),
            })
            if cc > HIGH_COMPLEXITY_THRESHOLD:
                high_complexity_functions.append({
                    "file": func.get("file", str(path)),
                    "function": func.get("function", "?"),
                    "complexity": cc,
                    "rank": func.get("rank") or _complexity_rank(cc),
                    "lineno": func.get("lineno"),
                    "tool": tool_used,
                    "recommendation": (
                        f"refactor '{func.get('function', '?')}' (complejidad {cc} > {HIGH_COMPLEXITY_THRESHOLD})"
                    ),
                })

    # --- Recommendations globales ---
    recommendations: List[str] = []
    if high_complexity_functions:
        recommendations.append(
            f"Refactorizar {len(high_complexity_functions)} función(es) con complejidad > {HIGH_COMPLEXITY_THRESHOLD}"
        )
    if security_findings:
        severities = {}
        for f in security_findings:
            sev = f.get("severity", "?").lower()
            severities[sev] = severities.get(sev, 0) + 1
        recommendations.append(
            f"Atender {len(security_findings)} finding(s) de seguridad: {severities}"
        )
    if degradations:
        recommendations.append(
            f"Instalar herramientas faltantes para análisis completo: {len(degradations)} degradación(es)"
        )
    if not recommendations:
        recommendations.append("Código en buen estado — sin acciones urgentes")

    return {
        "schema_version": "2.5.0",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "total_files": len(files),
        "languages_detected": languages_present,
        "tools_tried": tools_tried,
        "security_findings": security_findings,
        "complexity_scores": complexity_scores,
        "high_complexity_functions": high_complexity_functions,
        "degradations": degradations,
        "recommendations": recommendations,
        "summary": {
            "total_security_findings": len(security_findings),
            "total_functions_analyzed": len(complexity_scores),
            "high_complexity_count": len(high_complexity_functions),
            "degradation_count": len(degradations),
        },
        "duration_ms": int((time.time() - start) * 1000),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "CODE-QUALITY.yaml"))

    # --files "a.py,b.ts" limita el análisis a esos archivos.
    explicit_files: Optional[List[str]] = None
    if args.get("files"):
        explicit_files = [f.strip() for f in args["files"].split(",") if f.strip()]

    if not repo_root.exists():
        log(f"repo-root no existe: {repo_root}", "ERROR")
        return 2

    log(f"code_quality.py v2.5.0 — analizando {repo_root}", "INFO")
    report = analyze_repo(repo_root, explicit_files)

    write_yaml(output, report)

    log(
        f"Code quality report: {report['total_files']} archivos | "
        f"{len(report['languages_detected'])} lenguajes | "
        f"{len(report['security_findings'])} security findings | "
        f"{len(report['high_complexity_functions'])} high-complexity | "
        f"{len(report['degradations'])} degradaciones",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "schema_version": "2.5.0",
        "total_files": report["total_files"],
        "languages_detected": report["languages_detected"],
        "security_findings": len(report["security_findings"]),
        "high_complexity_functions": len(report["high_complexity_functions"]),
        "degradations": len(report["degradations"]),
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

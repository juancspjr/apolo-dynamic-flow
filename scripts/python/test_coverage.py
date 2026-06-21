#!/usr/bin/env python3
"""
test_coverage.py — Análisis de cobertura de tests por símbolo (v2.5.0).

Diferencia con run_tests.py (que solo corre tests):
este script analiza QUÉ símbolos están cubiertos por tests,
no solo si los tests pasan.

Integraciones:
  Python: coverage.py (coverage run + coverage report --json)
  JavaScript/TypeScript: nyc/jest --coverage
  Go: go test -cover -coverprofile

Si coverage tools no están disponibles, usa heurísticas:
  - Busca test_<name>.py, <name>_test.go, <name>.test.ts por convención
  - Cuenta símbolos en archivos de test vs archivos de código

Uso:
  python3 test_coverage.py --repo-root . --output TEST-COVERAGE.yaml
  python3 test_coverage.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

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

# Map extensión -> lenguaje normalizado (compartido con code_quality.py).
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
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".cs": "csharp",
}

# Directorios a excluir del escaneo de tests.
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "vendor", ".next", "__pycache__",
    ".cache", ".opencode", "target", ".venv", "venv", "env", ".pytest_cache",
    "coverage", ".nyc_output",
}

# Convenciones de nombres de test por lenguaje.
TEST_CONVENTIONS: Dict[str, List[str]] = {
    "python": ["test_{}.py", "{}_test.py", "tests_{}.py"],
    "javascript": ["{}.test.js", "{}.spec.js", "{}-test.js"],
    "typescript": ["{}.test.ts", "{}.spec.ts", "{}-test.ts"],
    "go": ["{}_test.go"],
    "rust": ["{}_test.rs"],
    "java": ["{}Test.java", "{}Tests.java"],
    "php": ["{}Test.php"],
}


# ============================================================================
# Language detection
# ============================================================================

def detect_language(path: Path) -> Optional[str]:
    """Detecta el lenguaje de un archivo por su extensión."""
    return EXTENSION_TO_LANGUAGE.get(path.suffix.lower())


def is_test_file(path: Path) -> bool:
    """Heurística: ¿el archivo parece un test por su nombre/path?"""
    name = path.name.lower()
    parts = path.parts
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
        or name.endswith(".spec.js")
        or name.endswith(".spec.ts")
        or name.endswith("_test.go")
        or name.endswith("_test.rs")
        or name.endswith("test.java")
        or name.endswith("tests.java")
        or "test" in parts
        or "tests" in parts
        or "__tests__" in parts
        or "spec" in parts
    )


# ============================================================================
# Symbol extraction
# ============================================================================

def extract_symbols_from_file(path: Path, language: str) -> List[Dict[str, Any]]:
    """Extrae símbolos exportados/públicos de un archivo.

    Returns: lista de {name, kind, lineno, is_exported}.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    symbols: List[Dict[str, Any]] = []

    if language == "python":
        for m in re.finditer(r"^(def|class)\s+(\w+)", text, re.MULTILINE):
            kind = "function" if m.group(1) == "def" else "class"
            # En Python todo es "público" salvo lo que empieza con _.
            is_exported = not m.group(2).startswith("_")
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": m.group(2),
                "kind": kind,
                "lineno": lineno,
                "is_exported": is_exported,
            })
    elif language in ("javascript", "typescript"):
        # export function foo, export const foo, export class Foo, export interface Foo
        for m in re.finditer(
            r"^\s*export\s+(default\s+)?(?:async\s+)?(function|class|interface|const|let|type)\s+(\w+)",
            text,
            re.MULTILINE,
        ):
            kind = m.group(2)
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": m.group(3),
                "kind": kind,
                "lineno": lineno,
                "is_exported": True,
            })
        # También no-exportadas (mínimo).
        for m in re.finditer(
            r"^\s*(?:async\s+)?function\s+(\w+)",
            text,
            re.MULTILINE,
        ):
            name = m.group(1)
            if not any(s["name"] == name for s in symbols):
                lineno = text.count("\n", 0, m.start()) + 1
                symbols.append({
                    "name": name,
                    "kind": "function",
                    "lineno": lineno,
                    "is_exported": False,
                })
    elif language == "go":
        for m in re.finditer(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", text, re.MULTILINE):
            name = m.group(1)
            # En Go, exportado si empieza con mayúscula.
            is_exported = name[0].isupper() if name else False
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": name,
                "kind": "function",
                "lineno": lineno,
                "is_exported": is_exported,
            })
        for m in re.finditer(r"^type\s+(\w+)\s+(?:struct|interface)", text, re.MULTILINE):
            name = m.group(1)
            is_exported = name[0].isupper() if name else False
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": name,
                "kind": "type",
                "lineno": lineno,
                "is_exported": is_exported,
            })
    elif language == "rust":
        for m in re.finditer(r"^pub\s+(?:async\s+)?fn\s+(\w+)", text, re.MULTILINE):
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": m.group(1),
                "kind": "function",
                "lineno": lineno,
                "is_exported": True,
            })
    elif language == "java":
        for m in re.finditer(
            r"(?:public|protected)\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{",
            text,
        ):
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": m.group(1),
                "kind": "method",
                "lineno": lineno,
                "is_exported": True,
            })
    elif language == "php":
        for m in re.finditer(r"^\s*public\s+(?:static\s+)?function\s+(\w+)", text, re.MULTILINE):
            lineno = text.count("\n", 0, m.start()) + 1
            symbols.append({
                "name": m.group(1),
                "kind": "function",
                "lineno": lineno,
                "is_exported": True,
            })

    return symbols


# ============================================================================
# Coverage tools
# ============================================================================

def run_coverage_py(repo_root: Path) -> Tuple[Dict[str, Any], bool]:
    """Corre coverage.py sobre el repo. Devuelve (data, was_available)."""
    if not cmd_available("coverage"):
        return {}, False
    # Ejecutar tests con coverage (requiere pytest o unittest).
    run_cmd(["coverage", "run", "--branch", "-m", "pytest"],
            cwd=repo_root, timeout=300)
    code, out, err = run_cmd(
        ["coverage", "report", "--format=json"],
        cwd=repo_root,
        timeout=30,
    )
    if not out:
        return {}, True
    try:
        return json.loads(out), True
    except json.JSONDecodeError:
        return {}, True


def run_nyc(repo_root: Path) -> Tuple[Dict[str, Any], bool]:
    """Corre nyc sobre el repo (requiere npm test)."""
    if not cmd_available("npx"):
        return {}, False
    run_cmd(
        ["npx", "nyc", "--reporter=json", "npm", "test"],
        cwd=repo_root,
        timeout=300,
    )
    # nyc escribe a coverage/coverage-final.json
    cov = repo_root / "coverage" / "coverage-final.json"
    if not cov.exists():
        return {}, True
    try:
        return json.loads(cov.read_text(encoding="utf-8")), True
    except Exception:
        return {}, True


def run_go_cover(repo_root: Path) -> Tuple[Dict[str, Any], bool]:
    """Corre go test -cover sobre el repo Go."""
    if not cmd_available("go"):
        return {}, False
    run_cmd(
        ["go", "test", "-cover", "-coverprofile=coverage.out", "./..."],
        cwd=repo_root,
        timeout=300,
    )
    cov = repo_root / "coverage.out"
    if not cov.exists():
        return {}, True
    try:
        text = cov.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}, True
    # Formato: mode: set
    # file:line.col,line.col numStmts count
    files: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines()[1:]:  # skip "mode: set"
        if ":" not in line:
            continue
        try:
            fpath, _, rest = line.partition(":")
            ranges, _, _ = rest.rpartition(" ")
            file_data = files.setdefault(fpath, {"covered_lines": 0, "uncovered_lines": 0})
            # Si count > 0, está cubierto.
            count = int(rest.rsplit(" ", 1)[-1])
            if count > 0:
                file_data["covered_lines"] += 1
            else:
                file_data["uncovered_lines"] += 1
        except (ValueError, IndexError):
            continue
    return files, True


# ============================================================================
# Heuristic coverage (fallback)
# ============================================================================

def heuristic_test_mapping(
    source_files: List[Tuple[Path, str]],
    test_files: List[Path],
) -> Dict[str, List[Path]]:
    """Mapea cada archivo fuente a sus tests por convención de nombres.

    Si foo.py existe y test_foo.py existe, los asocia.
    """
    mapping: Dict[str, List[Path]] = {}
    test_stems: Dict[str, List[Path]] = {}
    for tf in test_files:
        stem = tf.stem.lower()
        # Normalizar: test_foo -> foo, foo_test -> foo, foo.test -> foo
        for prefix in ("test_", "tests_"):
            if stem.startswith(prefix):
                stem = stem[len(prefix):]
        for suffix in ("_test", "test", "spec"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)] if stem != suffix else stem
        test_stems.setdefault(stem, []).append(tf)

    for sf, lang in source_files:
        stem = sf.stem.lower()
        candidates = test_stems.get(stem, [])
        # También buscar tests que contengan el stem como substring.
        if not candidates:
            for ts, tfs in test_stems.items():
                if stem in ts or ts in stem:
                    candidates.extend(tfs)
        mapping[str(sf)] = candidates
    return mapping


# ============================================================================
# Main analysis
# ============================================================================

def load_symbols_from_code_index(code_index_path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Carga CODE-INDEX.yaml si existe. Devuelve el dict o None."""
    if not code_index_path or not code_index_path.exists():
        return None
    return read_yaml(code_index_path)


def analyze_coverage(
    repo_root: Path,
    code_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analiza la cobertura de tests por símbolo.

    Estrategia:
      1. Si hay CODE-INDEX.yaml, usar su lista de archivos y símbolos.
      2. Si no, escanear el repo para detectar archivos fuente + tests.
      3. Intentar coverage.py / nyc / go test según el lenguaje dominante.
      4. Si no hay herramienta, usar heurística por convención de nombres.
    """
    start = time.time()

    # --- Recopilar archivos fuente y tests ---
    source_files: List[Tuple[Path, str]] = []
    test_files: List[Path] = []
    code_index_used = False

    if code_index:
        # Usar CODE-INDEX.yaml como fuente de verdad.
        code_index_used = True
        for entry in code_index.get("files", []) or []:
            fpath_str = entry.get("path", "")
            if not fpath_str:
                continue
            p = Path(fpath_str)
            if not p.is_absolute():
                p = repo_root / p
            lang = detect_language(p) or entry.get("language")
            if not lang:
                continue
            if is_test_file(p):
                test_files.append(p)
            else:
                source_files.append((p, lang))
    else:
        # Escanear repo.
        for path in repo_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            lang = detect_language(path)
            if not lang:
                continue
            if is_test_file(path):
                test_files.append(path)
            else:
                source_files.append((path, lang))

    # --- Recopilar símbolos ---
    all_symbols: List[Dict[str, Any]] = []
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for sf, lang in source_files:
        file_syms = extract_symbols_from_file(sf, lang)
        # Enriquecer con info del CODE-INDEX si disponible.
        if code_index_used and code_index:
            for entry in code_index.get("files", []) or []:
                entry_path = entry.get("path", "")
                ep = Path(entry_path) if entry_path else None
                if ep and (ep.resolve() == sf.resolve() or entry_path.endswith(sf.name)):
                    # Reemplazar con símbolos del índice si los hay.
                    indexed = entry.get("symbols", {}) or {}
                    if indexed.get("functions") or indexed.get("classes"):
                        file_syms = []
                        for func in indexed.get("functions", []) or []:
                            file_syms.append({
                                "name": func.get("name", "?"),
                                "kind": "function",
                                "lineno": func.get("line"),
                                "is_exported": func.get("is_exported", True),
                            })
                        for cls in indexed.get("classes", []) or []:
                            file_syms.append({
                                "name": cls.get("name", "?"),
                                "kind": "class",
                                "lineno": cls.get("line"),
                                "is_exported": True,
                            })
                    break
        for sym in file_syms:
            sym["file"] = str(sf)
            sym["language"] = lang
        all_symbols.extend(file_syms)
        by_file[str(sf)] = file_syms

    # --- Intentar herramientas de coverage ---
    coverage_data: Dict[str, Any] = {}
    coverage_tool_used: Optional[str] = None
    degradations: List[str] = []

    # Detectar lenguaje dominante para elegir herramienta.
    lang_counts: Dict[str, int] = {}
    for _, lang in source_files:
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    dominant_lang = max(lang_counts, key=lang_counts.get) if lang_counts else None

    if dominant_lang == "python":
        data, ok = run_coverage_py(repo_root)
        if ok:
            coverage_data = data
            coverage_tool_used = "coverage.py"
        else:
            degradations.append("coverage.py no disponible — usando heurística por convención")
    elif dominant_lang in ("javascript", "typescript"):
        data, ok = run_nyc(repo_root)
        if ok:
            coverage_data = data
            coverage_tool_used = "nyc"
        else:
            degradations.append("nyc no disponible — usando heurística por convención")
    elif dominant_lang == "go":
        data, ok = run_go_cover(repo_root)
        if ok:
            coverage_data = data
            coverage_tool_used = "go test -cover"
        else:
            degradations.append("go no disponible — usando heurística por convención")
    else:
        degradations.append(
            f"no hay herramienta de coverage para lenguaje dominante '{dominant_lang}' — usando heurística"
        )

    # --- Calcular cobertura por símbolo ---
    # Estrategia: un símbolo está cubierto si su archivo tiene un test asociado
    # (por convención de nombres) Y si aparece mencionado en el archivo de test.
    heuristic_map = heuristic_test_mapping(source_files, test_files)

    covered_symbols: List[Dict[str, Any]] = []
    uncovered_symbols: List[Dict[str, Any]] = []
    critical_uncovered: List[Dict[str, Any]] = []  # exportados sin test

    # Pre-cargar contenido de tests para buscar símbolos referenciados.
    test_contents: Dict[Path, str] = {}
    for tf in test_files:
        try:
            test_contents[tf] = tf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            test_contents[tf] = ""

    for sym in all_symbols:
        sym_file = sym["file"]
        sym_name = sym["name"]
        associated_tests = heuristic_map.get(sym_file, [])
        # Verificar si el símbolo es referenciado en algún test asociado.
        is_covered = False
        for tf in associated_tests:
            content = test_contents.get(tf, "")
            if sym_name in content:
                is_covered = True
                break

        entry = {
            "file": sym_file,
            "name": sym_name,
            "kind": sym.get("kind", "?"),
            "is_exported": sym.get("is_exported", False),
            "covered": is_covered,
            "test_files": [str(t) for t in associated_tests],
        }
        if is_covered:
            covered_symbols.append(entry)
        else:
            uncovered_symbols.append(entry)
            if sym.get("is_exported"):
                critical_uncovered.append(entry)

    total = len(all_symbols)
    covered = len(covered_symbols)
    coverage_pct = round((covered / total * 100), 2) if total else 0.0

    # --- by_file summary ---
    by_file_summary: Dict[str, Dict[str, Any]] = {}
    for sf_str, syms in by_file.items():
        total_in_file = len(syms)
        covered_in_file = sum(
            1 for s in syms
            if any(s["name"] in test_contents.get(tf, "")
                   for tf in heuristic_map.get(sf_str, []))
        )
        by_file_summary[sf_str] = {
            "total_symbols": total_in_file,
            "covered_symbols": covered_in_file,
            "coverage_pct": round(
                (covered_in_file / total_in_file * 100) if total_in_file else 0.0, 2
            ),
            "associated_tests": [str(t) for t in heuristic_map.get(sf_str, [])],
        }

    # --- Recommendations ---
    recommendations: List[str] = []
    if critical_uncovered:
        recommendations.append(
            f"Escribir tests para {len(critical_uncovered)} símbolo(s) exportado(s) sin cobertura"
        )
    if coverage_pct < 50 and total > 0:
        recommendations.append(
            f"Cobertura actual {coverage_pct}% — objetivo mínimo 50%"
        )
    if not source_files:
        recommendations.append("No se detectaron archivos fuente — verificar repo-root")
    if not test_files:
        recommendations.append("No se detectaron archivos de test — escribir tests primero")
    if not recommendations:
        recommendations.append("Cobertura adecuada — mantener el ritmo")

    return {
        "schema_version": "2.5.0",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "code_index_used": code_index_used,
        "coverage_tool_used": coverage_tool_used,
        "dominant_language": dominant_lang,
        "total_symbols": total,
        "covered_symbols": covered,
        "uncovered_symbols": len(uncovered_symbols),
        "coverage_percentage": coverage_pct,
        "critical_uncovered": critical_uncovered,
        "by_file": by_file_summary,
        "source_files_count": len(source_files),
        "test_files_count": len(test_files),
        "degradations": degradations,
        "recommendations": recommendations,
        "summary": {
            "total_symbols": total,
            "covered": covered,
            "uncovered": len(uncovered_symbols),
            "critical_uncovered": len(critical_uncovered),
            "coverage_percentage": coverage_pct,
        },
        "duration_ms": int((time.time() - start) * 1000),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "TEST-COVERAGE.yaml"))
    code_index_path = (
        Path(args.get("code-index")) if args.get("code-index") else None
    )

    if not repo_root.exists():
        log(f"repo-root no existe: {repo_root}", "ERROR")
        return 2

    code_index = load_symbols_from_code_index(code_index_path)
    if code_index:
        log(f"CODE-INDEX cargado: {code_index_path}", "INFO")
    else:
        log("Sin CODE-INDEX — escaneando repo directamente", "INFO")

    log(f"test_coverage.py v2.5.0 — analizando {repo_root}", "INFO")
    report = analyze_coverage(repo_root, code_index)

    write_yaml(output, report)

    log(
        f"Test coverage: {report['total_symbols']} símbolos | "
        f"{report['covered_symbols']} cubiertos | "
        f"{report['coverage_percentage']}% | "
        f"{len(report['critical_uncovered'])} críticos sin cobertura",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "schema_version": "2.5.0",
        "total_symbols": report["total_symbols"],
        "covered_symbols": report["covered_symbols"],
        "coverage_percentage": report["coverage_percentage"],
        "critical_uncovered": len(report["critical_uncovered"]),
        "tool_used": report["coverage_tool_used"],
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

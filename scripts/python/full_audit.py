#!/usr/bin/env python3
"""
full_audit.py — Revisión completa del sistema (v2.8.1).

FIX v2.8.1: TypeError cuando `security_findings` o `smell_count` son listas
  (algunos analizadores retornan lista de findings, no un int).
  Ahora se normaliza con `_as_count()` antes de cualquier operación aritmética.

Ejecuta TODOS los analizadores en orden y genera un reporte consolidado:
  1. Code index (AST)
  2. Code quality (bandit, radon, eslint-security, gosec, cppcheck)
  3. Vulnerability scan (safety, npm audit, pip-audit, govulncheck, cargo audit)
  4. Code smells (long methods, god classes, deep nesting, duplication)
  5. Dead code analysis
  6. Cyclomatic complexity (radon, gocyclo, regex fallback)
  7. Test coverage
  8. LSP diagnostics (if available)
  9. Cross-language analysis
  10. Function summaries
  11. Refactoring suggestions

Genera FULL-AUDIT-REPORT.yaml con todo consolidado + score final.

Uso:
  python3 full_audit.py --repo-root .
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, cmd_available


def _as_count(value: Any) -> int:
    """Normaliza un valor a entero count.

    Algunos analizadores retornan:
      - int (count directo)         → usar tal cual
      - list of dicts (findings)    → len()
      - dict con 'count' o 'total'  → extraer
      - None / missing              → 0
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for k in ("count", "total", "total_findings", "total_smells", "n"):
            if k in value:
                return _as_count(value[k])
        return len(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def run_script(script_name: str, args: List[str], repo_root: Path, timeout: int = 60) -> Dict[str, Any]:
    """Ejecuta un script Python y captura resultado."""
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        return {"status": "skipped", "reason": f"{script_name} not found"}

    cmd = ["python3", str(script_path)] + args
    start = time.time()
    code, out, err = run_cmd(cmd, cwd=repo_root, timeout=timeout)
    duration_ms = int((time.time() - start) * 1000)

    result = {
        "script": script_name,
        "exit_code": code,
        "duration_ms": duration_ms,
        "stdout": out[:2000] if out else "",
        "stderr": err[:500] if err else "",
    }

    # Try to parse JSON from stdout
    try:
        json_start = out.find("{")
        if json_start >= 0:
            result["parsed"] = json.loads(out[json_start:])
            result["status"] = "success" if code == 0 else "warnings"
        else:
            result["status"] = "success" if code == 0 else "error"
    except Exception:
        result["status"] = "success" if code == 0 else "error"

    return result


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "FULL-AUDIT-REPORT.yaml"))
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"

    start_time = time.time()
    log("=== FULL AUDIT START ===", "INFO")

    audit = {
        "fullaudit": "V1",
        "version": 1,
        "schema_version": "2.8.1",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "steps": [],
    }

    # Step 1: Code Index
    log("Step 1/11: Code Index", "INFO")
    r = run_script("index_codebase.py", [
        "--repo-root", str(repo_root),
        "--output", str(ci_path),
    ], repo_root)
    audit["steps"].append({"step": 1, "name": "code_index", **r})

    # Step 2: Code Quality
    log("Step 2/11: Code Quality", "INFO")
    r = run_script("code_quality.py", [
        "--repo-root", str(repo_root),
        "--output", str(repo_root / "CODE-QUALITY.yaml"),
    ], repo_root, timeout=120)
    audit["steps"].append({"step": 2, "name": "code_quality", **r})

    # Step 3: Vulnerability Scan
    log("Step 3/11: Vulnerability Scan", "INFO")
    r = run_script("vulnerability_scanner.py", [
        "--repo-root", str(repo_root),
        "--output", str(repo_root / "VULNERABILITY-REPORT.yaml"),
    ], repo_root, timeout=120)
    audit["steps"].append({"step": 3, "name": "vulnerability_scan", **r})

    # Step 4: Code Smells
    log("Step 4/11: Code Smells", "INFO")
    r = run_script("code_smells.py", [
        "--repo-root", str(repo_root),
        "--code-index", str(ci_path),
        "--output", str(repo_root / "CODE-SMELLS.yaml"),
    ], repo_root, timeout=60)
    audit["steps"].append({"step": 4, "name": "code_smells", **r})

    # Step 5: Dead Code (part of code_smells)
    audit["steps"].append({"step": 5, "name": "dead_code", "status": "included_in_code_smells"})

    # Step 6: Cyclomatic Complexity (part of code_smells)
    audit["steps"].append({"step": 6, "name": "complexity", "status": "included_in_code_smells"})

    # Step 7: Test Coverage
    log("Step 7/11: Test Coverage", "INFO")
    r = run_script("test_coverage.py", [
        "--repo-root", str(repo_root),
        "--code-index", str(ci_path),
        "--output", str(repo_root / "TEST-COVERAGE.yaml"),
    ], repo_root, timeout=120)
    audit["steps"].append({"step": 7, "name": "test_coverage", **r})

    # Step 8: LSP Diagnostics
    log("Step 8/11: LSP Diagnostics", "INFO")
    r = run_script("lsp_integration.py", [
        "--repo-root", str(repo_root),
        "--output", str(repo_root / "LSP-ANALYSIS.yaml"),
    ], repo_root, timeout=60)
    audit["steps"].append({"step": 8, "name": "lsp_diagnostics", **r})

    # Step 9: Cross-Language Analysis
    log("Step 9/11: Cross-Language Analysis", "INFO")
    r = run_script("cross_language_analyzer.py", [
        "--repo-root", str(repo_root),
        "--code-index", str(ci_path),
        "--output", str(repo_root / "CROSS-LANGUAGE-MAP.yaml"),
    ], repo_root, timeout=60)
    audit["steps"].append({"step": 9, "name": "cross_language", **r})

    # Step 10: Function Summaries
    log("Step 10/11: Function Summaries", "INFO")
    r = run_script("summarize_functions.py", [
        "--repo-root", str(repo_root),
        "--code-index", str(ci_path),
        "--output", str(repo_root / "FUNCTION-SUMMARIES.yaml"),
    ], repo_root, timeout=60)
    audit["steps"].append({"step": 10, "name": "function_summaries", **r})

    # Step 11: Refactoring Suggestions
    log("Step 11/11: Refactoring", "INFO")
    r = run_script("refactor_engine.py", [
        "--repo-root", str(repo_root),
        "--code-index", str(ci_path),
        "--output", str(repo_root / "REFACTOR-SUGGESTIONS.yaml"),
    ], repo_root, timeout=60)
    audit["steps"].append({"step": 11, "name": "refactoring", **r})

    # Compute final score — FIX v2.8.1: usar _as_count para evitar TypeError
    total_ms = int((time.time() - start_time) * 1000)
    steps_ok = sum(1 for s in audit["steps"] if s.get("status") in ("success", "warnings", "included_in_code_smells"))
    steps_total = len(audit["steps"])

    score = 100

    vuln_report = read_yaml(repo_root / "VULNERABILITY-REPORT.yaml") or {}
    vuln_count = _as_count(vuln_report.get("total_findings", 0))
    score -= min(vuln_count * 5, 30)  # -5 per vuln, max -30

    smells_report = read_yaml(repo_root / "CODE-SMELLS.yaml") or {}
    # smells_report puede tener summary.total_smells o total_smells directo
    smells_summary = smells_report.get("summary", {})
    smell_count = _as_count(smells_summary.get("total_smells", 0)) if smells_summary else _as_count(smells_report.get("total_smells", 0))
    score -= min(smell_count * 2, 20)  # -2 per smell, max -20

    coverage_report = read_yaml(repo_root / "TEST-COVERAGE.yaml") or {}
    coverage_pct = coverage_report.get("coverage_percentage", 0)
    coverage_pct = _as_count(coverage_pct) if not isinstance(coverage_pct, (int, float)) else coverage_pct
    if coverage_pct < 50:
        score -= 20
    elif coverage_pct < 80:
        score -= 10

    quality_report = read_yaml(repo_root / "CODE-QUALITY.yaml") or {}
    # FIX v2.8.1: security_findings puede ser int O list[dict]
    security_findings_raw = quality_report.get("security_findings", 0)
    security_findings = _as_count(security_findings_raw)
    score -= min(security_findings * 1, 15)

    score = max(score, 0)

    audit["summary"] = {
        "total_duration_ms": total_ms,
        "steps_completed": steps_ok,
        "steps_total": steps_total,
        "vulnerabilities_found": vuln_count,
        "code_smells_found": smell_count,
        "test_coverage_pct": coverage_pct,
        "security_findings": security_findings,
        "final_score": score,
        "grade": "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F",
    }

    write_yaml(output, audit)

    log(f"=== FULL AUDIT COMPLETE === Score: {score} ({audit['summary']['grade']}) — {total_ms}ms", "INFO")

    print(json.dumps({
        "success": True,
        "final_score": score,
        "grade": audit["summary"]["grade"],
        "vulnerabilities": vuln_count,
        "code_smells": smell_count,
        "coverage_pct": coverage_pct,
        "security_findings": security_findings,
        "duration_ms": total_ms,
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

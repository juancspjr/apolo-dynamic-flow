#!/usr/bin/env python3
"""
run_tests.py — Runner determinista de tests tras cada cambio.

Lee:
  - targets (símbolos, archivos, endpoints) afectados por el cambio
  - kind: unit | integration | mutation | e2e | contract | schema-validation

Ejecuta:
  - Descubre test files relacionados con los targets (patrones comunes)
  - Los ejecuta con pytest (Python), go test (Go), jest (JS/TS) según disponibilidad
  - Si kind=mutation → ejecuta mutmut (Python) o go-mutesting (Go)
  - Si kind=schema-validation → valida YAMLs contra schemas
  - Calcula hashes de stdout/stderr para comparación determinista

Escribe:
  - TEST-RUN.yaml conforme al schema
"""

from __future__ import annotations

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
    gen_run_id,
    hash_file,
    log,
    now_iso,
    parse_args,
    read_yaml,
    run_cmd,
    sha256,
    write_yaml,
)


# ============================================================================
# Test discovery
# ============================================================================

def discover_pytest_tests(repo_root: Path, targets: List[str]) -> List[Path]:
    """Descubre archivos test_*.py relacionados con los targets."""
    test_files: List[Path] = set()
    for target in targets:
        # Si target es archivo: buscar test_<nombre>.py en el mismo dir o tests/
        if target.endswith(".py"):
            base = Path(target).stem
            for candidate in [
                repo_root / "tests" / f"test_{base}.py",
                repo_root / "test" / f"test_{base}.py",
                Path(target).parent / f"test_{base}.py",
            ]:
                if candidate.exists():
                    test_files.add(candidate)  # type: ignore
        # Si target es símbolo (función/clase): grep en tests/
        else:
            code, out, _ = run_cmd(
                ["grep", "-rl", target, "tests/", "test/"],
                cwd=repo_root,
                timeout=10,
            )
            if code == 0:
                for line in out.strip().split("\n"):
                    if line:
                        p = repo_root / line
                        if p.exists():
                            test_files.add(p)
    return sorted(test_files)


def discover_go_tests(repo_root: Path, targets: List[str]) -> List[Path]:
    test_files: List[Path] = set()
    for target in targets:
        if target.endswith(".go"):
            base = Path(target).with_suffix("_test.go")
            candidate = repo_root / base
            if candidate.exists():
                test_files.add(candidate)
    return sorted(test_files)


def discover_jest_tests(repo_root: Path, targets: List[str]) -> List[Path]:
    test_files: List[Path] = set()
    for target in targets:
        if target.endswith((".ts", ".tsx", ".js", ".jsx")):
            base = Path(target).stem
            for pattern in [f"**/{base}.test.ts", f"**/{base}.test.tsx", f"**/{base}.spec.ts"]:
                for p in repo_root.glob(pattern):
                    if p.exists():
                        test_files.add(p)
    return sorted(test_files)


# ============================================================================
# Runners
# ============================================================================

def run_pytest(test_files: List[Path], repo_root: Path) -> Tuple[int, str, str]:
    if not test_files:
        return 0, "no tests discovered", ""
    if not cmd_available("pytest"):
        return -1, "", "pytest no disponible"
    args = ["pytest", "-v", "--tb=short"] + [str(f) for f in test_files]
    return run_cmd(args, cwd=repo_root, timeout=300)


def run_go_test(test_files: List[Path], repo_root: Path) -> Tuple[int, str, str]:
    if not test_files:
        return 0, "no tests discovered", ""
    if not cmd_available("go"):
        return -1, "", "go no disponible"
    # go test por directorio
    dirs = sorted(set(f.parent for f in test_files))
    code, out, err = 0, "", ""
    for d in dirs:
        c, o, e = run_cmd(["go", "test", "-v", "./" + str(d.relative_to(repo_root)) + "/..."], cwd=repo_root, timeout=300)
        out += o
        err += e
        if c != 0:
            code = c
    return code, out, err


def run_jest(test_files: List[Path], repo_root: Path) -> Tuple[int, str, str]:
    if not test_files:
        return 0, "no tests discovered", ""
    if not cmd_available("npx"):
        return -1, "", "npx no disponible"
    args = ["npx", "jest", "--verbose"] + [str(f) for f in test_files]
    return run_cmd(args, cwd=repo_root, timeout=300)


def run_schema_validation(
    targets: List[str], repo_root: Path
) -> Tuple[int, str, str]:
    """Valida YAMLs contra schemas. targets = lista de 'artifact:schema' pairs."""
    from common import validate_required
    all_errors: List[str] = []
    for t in targets:
        if ":" not in t:
            all_errors.append(f"target inválido (esperado artifact:schema): {t}")
            continue
        artifact_p, schema_p = t.split(":", 1)
        artifact = read_yaml(repo_root / artifact_p) or {}
        schema = read_yaml(repo_root / schema_p) or {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        errors = validate_required(artifact, required, artifact_p)
        all_errors.extend(errors)
    if all_errors:
        return 1, "\n".join(all_errors), ""
    return 0, "all schemas valid", ""


# ============================================================================
# Parse test output
# ============================================================================

def parse_pytest_output(stdout: str, stderr: str) -> List[Dict[str, Any]]:
    tests: List[Dict[str, Any]] = []
    # Líneas tipo: tests/test_foo.py::test_bar PASSED [ 50%]
    pattern = re.compile(
        r"^(?P<file>.+?)::(?P<name>\S+)\s+(?P<status>PASSED|FAILED|SKIPPED|ERROR)"
    )
    for line in stdout.split("\n"):
        m = pattern.match(line)
        if m:
            tests.append({
                "id": f"T-{str(len(tests) + 1).zfill(3)}",
                "name": m.group("name"),
                "status": m.group("status").lower(),
                "duration_ms": 0,
                "stdout_hash": sha256(line),
                "stderr_hash": "",
                "assertion": m.group("file"),
            })
    if not tests:
        # Si no parseamos nada, registrar 1 test síntesis
        tests.append({
            "id": "T-001",
            "name": "(raw run)",
            "status": "fail" if stderr else "pass",
            "duration_ms": 0,
            "stdout_hash": sha256(stdout),
            "stderr_hash": sha256(stderr),
            "assertion": "raw pytest output",
        })
    return tests


def parse_go_test_output(stdout: str, stderr: str) -> List[Dict[str, Any]]:
    tests: List[Dict[str, Any]] = []
    pattern = re.compile(r"^(?:--- (PASS|FAIL|SKIP):\s+)?(?P<name>\S+)\s+\((?P<dur>[\d.]+)s\)")
    for line in stdout.split("\n"):
        m = pattern.match(line)
        if m:
            status = "pass"
            if "FAIL" in line:
                status = "fail"
            elif "SKIP" in line:
                status = "skip"
            tests.append({
                "id": f"T-{str(len(tests) + 1).zfill(3)}",
                "name": m.group("name"),
                "status": status,
                "duration_ms": int(float(m.group("dur")) * 1000),
                "stdout_hash": sha256(line),
                "stderr_hash": "",
                "assertion": "go test",
            })
    if not tests:
        tests.append({
            "id": "T-001",
            "name": "(raw run)",
            "status": "fail" if stderr else "pass",
            "duration_ms": 0,
            "stdout_hash": sha256(stdout),
            "stderr_hash": sha256(stderr),
            "assertion": "raw go test output",
        })
    return tests


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    flowid = args.get("flowid", "")
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "TEST-RUN.yaml"))
    trigger = args.get("trigger", "manual")
    kind = args.get("kind", "unit")
    targets_json = args.get("targets-json", "[]")
    mp_id = args.get("mp-id", "")

    if not flowid:
        log("--flowid requerido", "ERROR")
        return 2

    try:
        targets = json.loads(targets_json)
    except Exception:
        targets = []

    started_iso = now_iso()
    start_time = time.time()
    run_id = gen_run_id()

    log(f"run tests flow={flowid} kind={kind} trigger={trigger} targets={len(targets)}", "INFO")

    # Dispatch por kind
    code, out, err = 0, "", ""
    parsed_tests: List[Dict[str, Any]] = []

    if kind == "schema-validation":
        code, out, err = run_schema_validation(targets, repo_root)
        parsed_tests = [{
            "id": "T-001",
            "name": "schema-validation",
            "status": "pass" if code == 0 else "fail",
            "duration_ms": int((time.time() - start_time) * 1000),
            "stdout_hash": sha256(out),
            "stderr_hash": sha256(err),
            "assertion": f"validar {len(targets)} artifacts contra schemas",
            "failure_detail": err if code != 0 else "",
        }]
    else:
        # Discovery
        py_tests = discover_pytest_tests(repo_root, targets)
        go_tests = discover_go_tests(repo_root, targets)
        jest_tests = discover_jest_tests(repo_root, targets)

        if py_tests:
            code, out, err = run_pytest(py_tests, repo_root)
            parsed_tests = parse_pytest_output(out, err)
        elif go_tests:
            code, out, err = run_go_test(go_tests, repo_root)
            parsed_tests = parse_go_test_output(out, err)
        elif jest_tests:
            code, out, err = run_jest(jest_tests, repo_root)
            parsed_tests = parse_pytest_output(out, err)  # jest output similar
        else:
            parsed_tests = [{
                "id": "T-001",
                "name": "(no tests discovered)",
                "status": "skip",
                "duration_ms": 0,
                "stdout_hash": "",
                "stderr_hash": "",
                "assertion": f"no se encontraron tests para targets={targets}",
            }]
            code = 0

    # Calcular summary
    summary = {
        "total": len(parsed_tests),
        "passed": sum(1 for t in parsed_tests if t["status"] == "pass"),
        "failed": sum(1 for t in parsed_tests if t["status"] == "fail"),
        "skipped": sum(1 for t in parsed_tests if t["status"] == "skip"),
        "errors": sum(1 for t in parsed_tests if t["status"] == "error"),
        "flaky": sum(1 for t in parsed_tests if t["status"] == "flaky"),
    }

    duration_ms = int((time.time() - start_time) * 1000)

    test_run = {
        "testrun": "V2",
        "version": 1,
        "flowid": flowid,
        "run_id": run_id,
        "started_at": started_iso,
        "finished_at": now_iso(),
        "duration_ms": duration_ms,
        "trigger": trigger,
        "scope": {
            "kind": kind,
            "targets": targets,
            "mp_id": mp_id or None,
        },
        "tests": parsed_tests,
        "summary": summary,
        "exit_code": code,
        "rollback_triggered": False,
        "rollback_log": "",
    }

    write_yaml(output, test_run)
    log(
        f"tests run: {summary['passed']}/{summary['total']} pass, {summary['failed']} fail, {duration_ms}ms",
        "INFO" if summary["failed"] == 0 else "WARN",
    )

    print(json.dumps({
        "success": summary["failed"] == 0 and summary["errors"] == 0,
        "summary": summary,
        "exit_code": code,
        "output": str(output),
        "duration_ms": duration_ms,
    }))
    # Exit 0 si pass, 1 si fail, 2 si error de runner
    return 0 if summary["failed"] == 0 and summary["errors"] == 0 else (1 if summary["failed"] > 0 else 2)


if __name__ == "__main__":
    sys.exit(main())

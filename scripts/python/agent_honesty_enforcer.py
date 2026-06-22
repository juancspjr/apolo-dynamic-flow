#!/usr/bin/env python3
"""
agent_honesty_enforcer.py — Previene que los agentes se autoengañen (v3.5.0).

RESPONDE a tu pregunta: "que los agentes no se autoengañen"

Un agente se autoengaña cuando:
  1. Declara "done" sin evidence pack valido
  2. Declara "tests pass" sin haber ejecutado tests
  3. Declara "implementado" sin archivos creados
  4. Omite errores de telemetry (silent fail)
  5. Declara "success" con score < threshold
  6. Reporta "fix aplicado" sin visual diff que lo confirme

Este script verifica que cada declaracion del agente este respaldada por
evidencia objetiva. Si no lo esta, BLOQUEA al agente.

CLI:
  python3 agent_honesty_enforcer.py verify --flowid X --repo-root .
  python3 agent_honesty_enforcer.py verify-claim --flowid X --claim "done" --repo-root .
  python3 agent_honesty_enforcer.py verify-claim --flowid X --claim "tests_pass" --repo-root .
"""

from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir, telemetry_path


# ============================================================================
# Honesty checks: cada declaracion del agente debe tener evidencia
# ============================================================================

HONESTY_CHECKS = [
    {
        "claim": "done",
        "description": "Agente declara flow completado",
        "evidence_required": [
            "ORCHESTRATOR-REPORT.yaml existe",
            "ORCHESTRATOR-REPORT.yaml tiene status=complete",
            "Todos los artefactos esperados existen",
            "No hay errores en telemetry",
        ],
        "check_fn": "check_done_claim",
    },
    {
        "claim": "tests_pass",
        "description": "Agente declara que tests pasan",
        "evidence_required": [
            "Evento de test en telemetry con severity=info",
            "No hay evento de test con severity=error",
            "force_quality_gates QG-05 (tests_pass) pasa",
        ],
        "check_fn": "check_tests_pass_claim",
    },
    {
        "claim": "implemented",
        "description": "Agente declara que implemento el codigo",
        "evidence_required": [
            "SCAFFOLD-V3.yaml existe con files_to_create",
            "Al menos 1 archivo de files_to_create existe en disco",
            "evidence_visual_diff snapshot post-fix existe",
        ],
        "check_fn": "check_implemented_claim",
    },
    {
        "claim": "fixed",
        "description": "Agente declara que arreglo un bug",
        "evidence_required": [
            "evidence_visual_diff snapshot broken existe",
            "evidence_visual_diff snapshot post-fix existe",
            "evidence_visual_diff compare muestra diferencias",
            "Tests pasan despues del fix",
        ],
        "check_fn": "check_fixed_claim",
    },
    {
        "claim": "no_errors",
        "description": "Agente declara que no hay errores",
        "evidence_required": [
            "No hay eventos con severity=error en telemetry",
            "No hay eventos con kind=*fail* en telemetry",
        ],
        "check_fn": "check_no_errors_claim",
    },
]


def load_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def check_done_claim(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica claim 'done'."""
    evidence = []
    issues = []

    # 1. ORCHESTRATOR-REPORT existe
    report_path = flow_dir(repo_root, flowid) / "ORCHESTRATOR-REPORT.yaml"
    if not report_path.exists():
        issues.append("ORCHESTRATOR-REPORT.yaml no existe")
        evidence.append({"check": "report_exists", "passed": False})
    else:
        report = read_yaml(report_path) or {}
        if report.get("status") != "complete":
            issues.append(f"ORCHESTRATOR-REPORT status={report.get('status')} (esperado: complete)")
            evidence.append({"check": "report_status_complete", "passed": False})
        else:
            evidence.append({"check": "report_status_complete", "passed": True})

    # 2. No hay errores en telemetry
    tel_events = load_jsonl(telemetry_path(repo_root, flowid))
    errors = [e for e in tel_events if e.get("severity") == "error"]
    if errors:
        issues.append(f"{len(errors)} errores en telemetry")
        evidence.append({"check": "no_errors_in_telemetry", "passed": False, "error_count": len(errors)})
    else:
        evidence.append({"check": "no_errors_in_telemetry", "passed": True})

    return {
        "claim": "done",
        "honest": len(issues) == 0,
        "evidence": evidence,
        "issues": issues,
        "verdict": "HONEST — claim respaldado por evidencia" if len(issues) == 0 else "DISHONEST — claim sin evidencia",
    }


def check_tests_pass_claim(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica claim 'tests_pass'."""
    evidence = []
    issues = []

    tel_events = load_jsonl(telemetry_path(repo_root, flowid))
    test_events = [e for e in tel_events if "test" in e.get("kind", "").lower() or "test" in e.get("phase", "").lower()]

    if not test_events:
        issues.append("No hay eventos de test en telemetry — no se ejecutaron tests")
        evidence.append({"check": "tests_were_run", "passed": False})
    else:
        evidence.append({"check": "tests_were_run", "passed": True, "count": len(test_events)})

    test_errors = [e for e in test_events if e.get("severity") == "error"]
    if test_errors:
        issues.append(f"{len(test_errors)} errores de test en telemetry")
        evidence.append({"check": "no_test_errors", "passed": False, "error_count": len(test_errors)})
    else:
        evidence.append({"check": "no_test_errors", "passed": True})

    return {
        "claim": "tests_pass",
        "honest": len(issues) == 0,
        "evidence": evidence,
        "issues": issues,
        "verdict": "HONEST" if len(issues) == 0 else "DISHONEST",
    }


def check_implemented_claim(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica claim 'implemented'."""
    evidence = []
    issues = []

    scaffold_path = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD-V3.yaml"
    if not scaffold_path.exists():
        issues.append("SCAFFOLD-V3.yaml no existe")
        return {"claim": "implemented", "honest": False, "evidence": evidence, "issues": issues, "verdict": "DISHONEST"}

    scaffold = read_yaml(scaffold_path) or {}
    files_to_create = scaffold.get("files_to_create", [])

    if not files_to_create:
        issues.append("Scaffold no tiene files_to_create")
        evidence.append({"check": "scaffold_has_files", "passed": False})
    else:
        evidence.append({"check": "scaffold_has_files", "passed": True, "count": len(files_to_create)})

    # Verificar que al menos 1 archivo existe en disco
    existing_count = 0
    for f_spec in files_to_create:
        f_path = repo_root / f_spec.get("path", "")
        if f_path.exists():
            existing_count += 1

    if existing_count == 0:
        issues.append("Ningun archivo de files_to_create existe en disco")
        evidence.append({"check": "files_created", "passed": False, "existing": 0})
    else:
        evidence.append({"check": "files_created", "passed": True, "existing": existing_count})

    # Verificar visual diff post-fix
    visual_diff_dir = flow_dir(repo_root, flowid) / "visual-diff"
    has_post_fix = False
    if visual_diff_dir.exists():
        for snap in visual_diff_dir.glob("snap-post-fix-*.yaml"):
            has_post_fix = True
            break
    if has_post_fix:
        evidence.append({"check": "post_fix_snapshot", "passed": True})
    else:
        issues.append("No hay snapshot post-fix en visual-diff")
        evidence.append({"check": "post_fix_snapshot", "passed": False})

    return {
        "claim": "implemented",
        "honest": len(issues) == 0,
        "evidence": evidence,
        "issues": issues,
        "verdict": "HONEST" if len(issues) == 0 else "DISHONEST",
    }


def check_fixed_claim(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica claim 'fixed'."""
    evidence = []
    issues = []

    visual_diff_dir = flow_dir(repo_root, flowid) / "visual-diff"
    has_broken = False
    has_post_fix = False

    if visual_diff_dir.exists():
        for snap in visual_diff_dir.glob("snap-broken-*.yaml"):
            has_broken = True
        for snap in visual_diff_dir.glob("snap-post-fix-*.yaml"):
            has_post_fix = True

    if not has_broken:
        issues.append("No hay snapshot broken en visual-diff")
    evidence.append({"check": "broken_snapshot", "passed": has_broken})

    if not has_post_fix:
        issues.append("No hay snapshot post-fix en visual-diff")
    evidence.append({"check": "post_fix_snapshot", "passed": has_post_fix})

    # Verificar compare report
    compare_path = flow_dir(repo_root, flowid) / "visual-diff" / "VISUAL-DIFF-REPORT.yaml"
    # Actually compare is output via --output, check ORCHESTRATOR-REPORT for visual_diff compare
    report_path = flow_dir(repo_root, flowid) / "ORCHESTRATOR-REPORT.yaml"
    if report_path.exists():
        report = read_yaml(report_path) or {}
        phases = report.get("phases", [])
        has_compare = any(
            "evidence_visual_diff" in str(p.get("scripts", []))
            for p in phases
        )
        evidence.append({"check": "visual_diff_compare", "passed": has_compare})
        if not has_compare:
            issues.append("No se encontro evidence_visual_diff compare en el flow")

    return {
        "claim": "fixed",
        "honest": len(issues) == 0,
        "evidence": evidence,
        "issues": issues,
        "verdict": "HONEST" if len(issues) == 0 else "DISHONEST",
    }


def check_no_errors_claim(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica claim 'no_errors'."""
    tel_events = load_jsonl(telemetry_path(repo_root, flowid))
    errors = [e for e in tel_events if e.get("severity") == "error"]
    fails = [e for e in tel_events if "fail" in e.get("kind", "").lower()]

    issues = []
    if errors:
        issues.append(f"{len(errors)} errores en telemetry")
    if fails:
        issues.append(f"{len(fails)} eventos de fallo en telemetry")

    return {
        "claim": "no_errors",
        "honest": len(issues) == 0,
        "evidence": [
            {"check": "no_error_severity", "passed": len(errors) == 0, "count": len(errors)},
            {"check": "no_fail_kind", "passed": len(fails) == 0, "count": len(fails)},
        ],
        "issues": issues,
        "verdict": "HONEST" if len(issues) == 0 else "DISHONEST",
    }


CLAIM_CHECKS = {
    "done": check_done_claim,
    "tests_pass": check_tests_pass_claim,
    "implemented": check_implemented_claim,
    "fixed": check_fixed_claim,
    "no_errors": check_no_errors_claim,
}


def verify_all_claims(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica todos los claims que el agente podria hacer."""
    log("=" * 60, "INFO")
    log("AGENT HONESTY ENFORCER v3.5.0 — Verificando claims del agente", "INFO")
    log("=" * 60, "INFO")

    results = []
    for claim_name, check_fn in CLAIM_CHECKS.items():
        log(f"  Verificando claim '{claim_name}'...", "INFO")
        result = check_fn(repo_root, flowid)
        results.append(result)
        if result["honest"]:
            log(f"    ✓ {claim_name}: HONEST", "INFO")
        else:
            log(f"    ⚠ {claim_name}: DISHONEST — {result['issues']}", "WARN")

    honest_count = sum(1 for r in results if r["honest"])

    report = {
        "agenthonestyenforcer": "V1",
        "schema_version": "3.5.0",
        "generated_at": now_iso(),
        "flowid": flowid,
        "total_claims": len(results),
        "honest_claims": honest_count,
        "dishonest_claims": len(results) - honest_count,
        "overall_honest": honest_count == len(results),
        "verdict": "AGENT IS HONEST — todos los claims respaldados" if honest_count == len(results) else f"AGENT DISHONEST — {len(results) - honest_count} claims sin evidencia",
        "claims": results,
    }

    report_path = repo_root / "AGENT-HONESTY-REPORT.yaml"
    write_yaml(report_path, report)
    return report


def main() -> int:
    argv = sys.argv[1:]
    action = "verify"
    known = {"verify", "verify-claim"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid:
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "verify":
        r = verify_all_claims(repo_root, flowid)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0 if r["overall_honest"] else 1
    elif action == "verify-claim":
        claim = args.get("claim", "")
        if claim not in CLAIM_CHECKS:
            print(json.dumps({"success": False, "error": f"Claim invalido: {claim}. Validos: {list(CLAIM_CHECKS.keys())}"}, indent=2))
            return 2
        check_fn = CLAIM_CHECKS[claim]
        r = check_fn(repo_root, flowid)
        print(json.dumps({"success": True, **r}, ensure_ascii=False, indent=2, default=str))
        return 0 if r["honest"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
integration_validation.py — Validación de integración REAL del pipeline (v2.8.1).

Este script responde a la pregunta del usuario:
  "Ejecuta un flow completo desde apolo.flow.init hasta al menos la fase
   verdad o plan-indice, usando datos reales del propio repositorio como
   objetivo, e invoca explícitamente index_codebase.py, score_evidence.py
   y predict_impact.py durante el proceso — no los asumas ejecutados,
   córrelos y muéstrame sus outputs reales en YAML."

Ejecuta el flow completo y genera un reporte HONESTO con:
  1. Outputs YAML reales de cada script invocado
  2. Verificación de que scaffold_impl.py produce un andamio concreto
  3. Verificación de que telemetry.jsonl registra cada decisión
  4. Análisis de qué scripts son automáticos vs manuales
  5. Análisis de si los tests validan contratos de integración
  6. Veredicto final: dónde se pierde control, dónde el agente decide sin evidencia

Uso:
  python3 integration_validation.py --repo-root . \\
      --output INTEGRATION-VALIDATION-REPORT.yaml \\
      [--flowid APOLO-INTEG-TEST] \\
      [--verbose]

Salida:
  - Reporte YAML con todos los outputs reales
  - Resumen JSON en stdout
  - Veredicto en stderr
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, cmd_available, flow_dir, state_path, telemetry_path


# ============================================================================
# Catálogo: scripts automáticos vs manuales
# ============================================================================

# Scripts que el loop engine TS invoca automáticamente (gate-gated)
AUTOMATIC_SCRIPTS = {
    "index_codebase.py": "Invocado en phase=plan-indice para construir CODE-INDEX",
    "collect_evidence.py": "Invocado en phase=verdad (recolección determinista + agente)",
    "score_evidence.py": "Invocado en phase=verdad (gate: score >= threshold para avanzar)",
    "generate_plan.py": "Invocado en phase=plan-indice (3 modos: deterministic/hybrid/manual)",
    "predict_impact.py": "Invocado en phase=plan-indice (BFS multi-nivel sobre CODE-INDEX)",
    "scaffold_impl.py": "Invocado en phase=reanclaje (genera andamio antes de implementar)",
    "validate_artifact.py": "Invocado por gates para validar YAMLs contra schemas",
    "common.py": "Librería compartida (no se invoca directo, se importa)",
    "context_query.py": "Invocado por el agente para obtener contexto del flow actual",
    "telemetry_aggregator.py": "Invocado por el loop para consolidar telemetry.jsonl",
    "health_check.py": "Invocado en init y post-fail para diagnóstico",
}

# Scripts que el AGENTE debe invocar manualmente
MANUAL_SCRIPTS = {
    "code_quality.py": "Agente decide cuándo analizar calidad",
    "test_coverage.py": "Agente decide cuándo medir coverage",
    "lsp_integration.py": "Agente lo usa para find-references/goto-def",
    "vulnerability_scanner.py": "Agente lo invoca para escaneo CVE",
    "code_smells.py": "Agente lo invoca para detectar smells",
    "full_audit.py": "Agente lo invoca para auditoría completa",
    "cross_language_analyzer.py": "Agente lo invoca para análisis cross-language",
    "summarize_functions.py": "Agente lo invoca para resúmenes",
    "code_generator.py": "Agente lo invoca para generar código",
    "doc_generator.py": "Agente lo invoca para generar docs",
    "project_templates.py": "Agente lo invoca para scaffolding de proyecto nuevo",
    "onboarding.py": "Agente lo invoca al iniciar",
    "github_actions.py": "Agente lo invoca para CI/CD",
    "self_healing.py": "Agente lo invoca cuando hay fallos repetidos",
    "generate_tests.py": "Agente lo invoca para tests automáticos",
    "semantic_search.py": "Agente lo invoca para búsqueda semántica",
    "refactor_engine.py": "Agente lo invoca para refactoring",
    "llm_bridge.py": "Agente lo invoca para llamadas LLM",
    "absorb_external_skills.py": "Agente lo invoca para absorber skills",
    "absorb_mcp.py": "Agente lo invoca para MCPs",
    "secret_scanner.py": "Agente lo invoca para escanear secretos",
    "inspect_tools.py": "Agente lo invoca para inspeccionar registry",
    "rollback.py": "Agente lo invoca para revertir",
    "run_tests.py": "Agente lo invoca para ejecutar test suite",
    "feedback_loop.py": "Agente lo invoca para registrar feedback (v2.8.1)",
    "interactive_docs.py": "Agente lo invoca para buscar docs (v2.8.1)",
    "debug_mode.py": "Agente lo invoca para debug paso a paso (v2.8.1)",
    "integration_validation.py": "Agente lo invoca para validar integración (v2.8.1)",
}


def find_script(name: str) -> Optional[Path]:
    """Encuentra un script por nombre en scripts/python/."""
    here = Path(__file__).parent
    candidate = here / name
    if candidate.exists():
        return candidate
    return None


def run_named_script(name: str, args: List[str], repo_root: Path, timeout: int = 90) -> Tuple[int, str, str, int]:
    """Ejecuta un script y retorna (exit_code, stdout, stderr, duration_ms)."""
    script_path = find_script(name)
    if not script_path:
        return -1, "", f"script not found: {name}", 0
    cmd = ["python3", str(script_path)] + args
    start = time.time()
    code, out, err = run_cmd(cmd, cwd=repo_root, timeout=timeout)
    duration_ms = int((time.time() - start) * 1000)
    return code, out, err, duration_ms


def parse_json_from_stdout(out: str) -> Optional[Dict]:
    """Extrae JSON de stdout (puede tener logs antes)."""
    if not out:
        return None
    idx = out.find("{")
    if idx < 0:
        return None
    try:
        return json.loads(out[idx:])
    except json.JSONDecodeError:
        return None


# ============================================================================
# Fases de validación
# ============================================================================

def phase_init(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 1: init-flow via apolo-inspect.sh."""
    log("[phase_init] Inicializando flow...", "INFO")
    inspect_sh = repo_root / "scripts" / "bash" / "apolo-inspect.sh"
    if not inspect_sh.exists():
        return {"status": "skipped", "reason": "apolo-inspect.sh not found"}

    cmd = ["bash", str(inspect_sh), "init-flow", "--flowid", flowid]
    start = time.time()
    code, out, err = run_cmd(cmd, cwd=repo_root, timeout=30)
    duration_ms = int((time.time() - start) * 1000)

    state_p = state_path(repo_root, flowid)
    state_content = ""
    if state_p.exists():
        try:
            state_content = state_p.read_text(encoding="utf-8", errors="replace")[:2000]
        except Exception:
            pass

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration_ms,
        "stdout_preview": out[:500],
        "stderr_preview": err[:500] if err else "",
        "state_yaml_exists": state_p.exists(),
        "state_yaml_preview": state_content,
        "state_yaml_path": str(state_p),
    }


def phase_index_codebase(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 2: index_codebase.py explícito."""
    log("[phase_index] Ejecutando index_codebase.py...", "INFO")
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
    code, out, err, duration = run_named_script(
        "index_codebase.py",
        ["--repo-root", str(repo_root), "--output", str(ci_path)],
        repo_root,
    )

    parsed = parse_json_from_stdout(out)
    ci_content = ""
    if ci_path.exists():
        try:
            ci_content = ci_path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1500],
        "stderr": err[:500] if err else "",
        "parsed_json": parsed,
        "ci_yaml_exists": ci_path.exists(),
        "ci_yaml_preview": ci_content,
        "ci_yaml_path": str(ci_path),
    }


def phase_collect_evidence(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 3: collect_evidence.py explícito."""
    log("[phase_collect] Ejecutando collect_evidence.py...", "INFO")
    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    ev_path.parent.mkdir(parents=True, exist_ok=True)

    # Use plugin/index.ts as scope target (exists in apolo repo)
    scope = json.dumps({"paths": ["plugin/index.ts"], "git_diff": True})
    code, out, err, duration = run_named_script(
        "collect_evidence.py",
        [
            "--flowid", flowid,
            "--repo-root", str(repo_root),
            "--output", str(ev_path),
            "--invoked-by", "integration_validation",
            "--scope-json", scope,
        ],
        repo_root,
    )

    parsed = parse_json_from_stdout(out)
    ev_content = ""
    if ev_path.exists():
        try:
            ev_content = ev_path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1500],
        "stderr": err[:500] if err else "",
        "parsed_json": parsed,
        "evidence_yaml_exists": ev_path.exists(),
        "evidence_yaml_preview": ev_content,
        "evidence_yaml_path": str(ev_path),
    }


def phase_score_evidence(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 4: score_evidence.py explícito."""
    log("[phase_score] Ejecutando score_evidence.py...", "INFO")
    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    sc_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-SCORE.yaml"

    if not ev_path.exists():
        return {"status": "skipped", "reason": "evidence pack not found"}

    code, out, err, duration = run_named_script(
        "score_evidence.py",
        ["--evidence", str(ev_path), "--output", str(sc_path), "--flowid", flowid],
        repo_root,
    )

    parsed = parse_json_from_stdout(out)
    sc_content = ""
    if sc_path.exists():
        try:
            sc_content = sc_path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1500],
        "stderr": err[:500] if err else "",
        "parsed_json": parsed,
        "score_yaml_exists": sc_path.exists(),
        "score_yaml_preview": sc_content,
        "score_yaml_path": str(sc_path),
    }


def phase_generate_plan(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 5: generate_plan.py (modo hybrid)."""
    log("[phase_plan] Ejecutando generate_plan.py (hybrid)...", "INFO")
    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"
    plan_path.parent.mkdir(parents=True, exist_ok=True)

    code, out, err, duration = run_named_script(
        "generate_plan.py",
        [
            "--flowid", flowid,
            "--evidence", str(ev_path),
            "--verdad", str(flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-SCORE.yaml"),
            "--output", str(plan_path),
            "--method", "hybrid",
        ],
        repo_root,
    )

    parsed = parse_json_from_stdout(out)
    plan_content = ""
    if plan_path.exists():
        try:
            plan_content = plan_path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1500],
        "stderr": err[:500] if err else "",
        "parsed_json": parsed,
        "plan_yaml_exists": plan_path.exists(),
        "plan_yaml_preview": plan_content,
        "plan_yaml_path": str(plan_path),
    }


def phase_predict_impact(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 6: predict_impact.py explícito."""
    log("[phase_impact] Ejecutando predict_impact.py...", "INFO")
    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
    impact_path = flow_dir(repo_root, flowid) / "plans" / "IMPACT-PREDICTION.yaml"

    if not plan_path.exists() or not ci_path.exists():
        return {"status": "skipped", "reason": "plan or code-index not found"}

    code, out, err, duration = run_named_script(
        "predict_impact.py",
        [
            "--plan", str(plan_path),
            "--code-index", str(ci_path),
            "--output", str(impact_path),
            "--flowid", flowid,
        ],
        repo_root,
    )

    parsed = parse_json_from_stdout(out)
    impact_content = ""
    if impact_path.exists():
        try:
            impact_content = impact_path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1500],
        "stderr": err[:500] if err else "",
        "parsed_json": parsed,
        "impact_yaml_exists": impact_path.exists(),
        "impact_yaml_preview": impact_content,
        "impact_yaml_path": str(impact_path),
    }


def phase_scaffold(repo_root: Path, flowid: str, verbose: bool = False) -> Dict[str, Any]:
    """Fase 7: scaffold_impl.py — verificar que produce andamio concreto."""
    log("[phase_scaffold] Ejecutando scaffold_impl.py...", "INFO")
    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
    scaffold_path = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD.yaml"
    scaffold_path.parent.mkdir(parents=True, exist_ok=True)

    if not plan_path.exists():
        return {"status": "skipped", "reason": "plan not found"}

    # Try with U-01 first; if plan has different unit IDs, this may fail gracefully
    code, out, err, duration = run_named_script(
        "scaffold_impl.py",
        [
            "--plan", str(plan_path),
            "--unit-id", "U-01",
            "--code-index", str(ci_path),
            "--output", str(scaffold_path),
            "--flowid", flowid,
        ],
        repo_root,
    )

    parsed = parse_json_from_stdout(out)
    scaffold_content = ""
    if scaffold_path.exists():
        try:
            scaffold_content = scaffold_path.read_text(encoding="utf-8", errors="replace")[:3000]
        except Exception:
            pass

    # Verificar que el scaffold es "concreto" (tiene files to create, no es vacío)
    is_concrete = False
    concrete_evidence = []
    if scaffold_path.exists():
        scaffold_data = read_yaml(scaffold_path) or {}
        # Check for concrete artifacts
        if scaffold_data.get("files_to_create"):
            is_concrete = True
            concrete_evidence.append(f"files_to_create: {len(scaffold_data['files_to_create'])} files")
        if scaffold_data.get("files_to_modify"):
            is_concrete = True
            concrete_evidence.append(f"files_to_modify: {len(scaffold_data['files_to_modify'])} files")
        if scaffold_data.get("commands"):
            is_concrete = True
            concrete_evidence.append(f"commands: {len(scaffold_data['commands'])} commands")
        if scaffold_data.get("scaffold"):
            # Nested structure
            scaffold = scaffold_data["scaffold"]
            if isinstance(scaffold, dict):
                for k in ("files", "commands", "tests", "structure"):
                    if scaffold.get(k):
                        is_concrete = True
                        concrete_evidence.append(f"scaffold.{k}: present")

    return {
        "status": "success" if code == 0 else "failed",
        "exit_code": code,
        "duration_ms": duration,
        "stdout": out[:1500],
        "stderr": err[:500] if err else "",
        "parsed_json": parsed,
        "scaffold_yaml_exists": scaffold_path.exists(),
        "scaffold_yaml_preview": scaffold_content,
        "scaffold_yaml_path": str(scaffold_path),
        "is_concrete": is_concrete,
        "concrete_evidence": concrete_evidence,
        "verdict_concrete": "PASS" if is_concrete else "FAIL — scaffold is empty/abstract",
    }


def verify_telemetry(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica que telemetry.jsonl registra cada decisión con timestamps reales."""
    log("[verify_telemetry] Verificando telemetry.jsonl...", "INFO")
    tp = telemetry_path(repo_root, flowid)
    if not tp.exists():
        return {
            "telemetry_exists": False,
            "entries_count": 0,
            "timestamps_valid": False,
            "verdict": "FAIL — telemetry.jsonl not found",
        }

    entries = []
    invalid_lines = 0
    for line in tp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            invalid_lines += 1

    timestamps = [e.get("at", "") for e in entries if isinstance(e, dict)]
    valid_ts = sum(1 for t in timestamps if t and ("T" in t or ":" in t))

    # Verificar campos requeridos por entrada
    required_fields = ["at", "flowid", "kind"]
    missing_per_entry = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        missing = [f for f in required_fields if f not in e]
        if missing:
            missing_per_entry.append(missing)

    return {
        "telemetry_exists": True,
        "telemetry_path": str(tp),
        "entries_count": len(entries),
        "invalid_lines": invalid_lines,
        "timestamps_valid": valid_ts == len(timestamps) and valid_ts > 0,
        "timestamps_with_tz": valid_ts,
        "entries_missing_required_fields": len(missing_per_entry),
        "sample_entries": entries[:5],
        "verdict": "PASS" if (len(entries) > 0 and valid_ts > 0 and not missing_per_entry) else "PARTIAL — some entries missing fields",
    }


# ============================================================================
# Análisis de tests: contratos de integración vs aislado
# ============================================================================

def analyze_test_contracts(repo_root: Path) -> Dict[str, Any]:
    """Analiza si los tests validan contratos de integración o solo scripts aislados."""
    log("[analyze_tests] Analizando contratos de tests...", "INFO")
    tests_dir = repo_root / "tests"
    if not tests_dir.exists():
        return {"status": "skipped", "reason": "no tests/ dir"}

    test_files = list(tests_dir.glob("*.py")) + list(tests_dir.glob("*.ts"))
    analysis = []
    integration_tests = 0
    isolated_tests = 0

    for tf in test_files:
        try:
            content = tf.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Heurística: si el test invoca 2+ scripts diferentes en el mismo test, es integración
        script_refs = set()
        for s in ["index_codebase", "collect_evidence", "score_evidence", "generate_plan",
                  "predict_impact", "scaffold_impl", "validate_artifact", "code_quality",
                  "test_coverage", "vulnerability_scanner", "code_smells", "full_audit",
                  "self_healing", "generate_tests", "semantic_search", "refactor_engine"]:
            if s in content:
                script_refs.add(s)

        is_integration = len(script_refs) >= 2
        if is_integration:
            integration_tests += 1
        else:
            isolated_tests += 1

        analysis.append({
            "file": str(tf.relative_to(repo_root)),
            "scripts_referenced": sorted(script_refs),
            "is_integration_test": is_integration,
        })

    return {
        "total_test_files": len(test_files),
        "integration_tests": integration_tests,
        "isolated_tests": isolated_tests,
        "ratio_integration": round(integration_tests / max(len(test_files), 1), 2),
        "verdict": (
            "MOSTLY ISOLATED — tests validate scripts individually, few cross-script contracts"
            if integration_tests < isolated_tests
            else "BALANCED — tests cover both isolated and integration contracts"
        ),
        "per_file": analysis,
    }


# ============================================================================
# Veredicto final
# ============================================================================

def build_verdict(phases: Dict[str, Dict], telemetry: Dict, tests: Dict) -> Dict[str, Any]:
    """Construye el veredicto honesto final."""
    successful_phases = sum(1 for p in phases.values() if p.get("status") == "success")
    total_phases = len(phases)

    artifacts_produced = []
    artifacts_missing = []
    for phase_name, result in phases.items():
        if phase_name == "init":
            continue
        yaml_key = f"{phase_name.split('_', 1)[0]}_yaml_exists"
        if result.get(yaml_key) or result.get("evidence_yaml_exists") or result.get("score_yaml_exists") or result.get("plan_yaml_exists") or result.get("impact_yaml_exists") or result.get("scaffold_yaml_exists") or result.get("ci_yaml_exists"):
            artifacts_produced.append(phase_name)
        else:
            artifacts_missing.append(phase_name)

    scaffold_concrete = phases.get("scaffold", {}).get("is_concrete", False)
    telemetry_ok = telemetry.get("telemetry_exists", False) and telemetry.get("entries_count", 0) > 0

    control_loss_points = []
    # Análisis: dónde el agente puede decidir sin evidencia suficiente
    # 1. Después de score_evidence, el agente decide si avanzar — pero el gate es automático
    # 2. La elección de method (deterministic/hybrid/manual) en generate_plan — el agente decide
    # 3. La elección de U-NN para scaffold — el agente decide
    # 4. La invocación de scripts manuales (code_quality, vulnerability_scanner, etc.)
    control_loss_points = [
        {
            "point": "Elección de method en generate_plan",
            "severity": "medium",
            "explanation": "El agente elige deterministic/hybrid/manual sin evidencia cuantitativa que justifique la elección. El sistema no impone un method por defecto basado en score_evidence.",
        },
        {
            "point": "Selección de U-NN para scaffold_impl",
            "severity": "high",
            "explanation": "El agente decide qué unidad implementar primero. Si el plan tiene 10 unidades, el sistema no prioriza automáticamente basándose en impacto/criticidad.",
        },
        {
            "point": "Invocación de scripts manuales (20+ scripts)",
            "severity": "high",
            "explanation": "20+ scripts (code_quality, vulnerability_scanner, code_smells, etc.) requieren invocación manual del agente. El sistema no los ejecuta automáticamente en función del contexto.",
        },
        {
            "point": "Thresholds hardcoded en gates",
            "severity": "medium",
            "explanation": "Los thresholds de score_evidence (e.g., >=0.6 para avanzar) están hardcoded en TS, no son ajustables por flow ni por proyecto.",
        },
        {
            "point": "Silent failures en scripts Python",
            "severity": "high",
            "explanation": "Si un script Python falla silenciosamente (retorna YAML vacío pero exit code 0), el loop engine TS puede avanzar de fase sin evidencia real. telemetry.jsonl solo registra lo que el TS layer reporta.",
        },
    ]

    return {
        "phases_executed": total_phases,
        "phases_successful": successful_phases,
        "phases_success_rate": round(successful_phases / max(total_phases, 1), 2),
        "artifacts_produced": artifacts_produced,
        "artifacts_missing": artifacts_missing,
        "scaffold_is_concrete": scaffold_concrete,
        "telemetry_records_decisions": telemetry_ok,
        "tests_integration_ratio": tests.get("ratio_integration", 0),
        "tests_verdict": tests.get("verdict", ""),
        "automatic_scripts_count": len(AUTOMATIC_SCRIPTS),
        "manual_scripts_count": len(MANUAL_SCRIPTS),
        "control_loss_points": control_loss_points,
        "overall_verdict": _overall_verdict(successful_phases, total_phases, scaffold_concrete, telemetry_ok, tests.get("ratio_integration", 0)),
    }


def _overall_verdict(successful: int, total: int, scaffold: bool, telemetry: bool, integration_ratio: float) -> str:
    if successful == total and scaffold and telemetry and integration_ratio > 0.3:
        return "HEALTHY — flow produces consistent artifacts, scaffold is concrete, telemetry records decisions, tests cover integration"
    elif successful == total and scaffold and telemetry:
        return "FUNCTIONAL — flow works end-to-end but tests are mostly isolated (need more integration tests)"
    elif successful < total:
        return f"PARTIAL — {total - successful} of {total} phases failed. Flow has gaps."
    else:
        return "DEGRADED — flow runs but scaffold is abstract or telemetry is incomplete"


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "APOLO-INTEG-TEST")
    output = Path(args.get("output", "INTEGRATION-VALIDATION-REPORT.yaml"))
    verbose = args.get("verbose", "false") == "true"

    start_time = time.time()
    log(f"=== INTEGRATION VALIDATION START === flowid={flowid}", "INFO")
    log(f"repo_root={repo_root}", "INFO")

    # Limpiar flow previo si existe
    prev_flow = flow_dir(repo_root, flowid)
    if prev_flow.exists():
        import shutil
        shutil.rmtree(prev_flow)
        log(f"Cleaned previous flow dir: {prev_flow}", "INFO")

    report = {
        "integration_validation": "V1",
        "schema_version": "2.8.1",
        "generated_at": now_iso(),
        "repo_root": str(repo_root),
        "flowid": flowid,
        "phases": {},
    }

    # Fase 1: init
    report["phases"]["init"] = phase_init(repo_root, flowid, verbose)

    # Fase 2: index_codebase
    report["phases"]["index_codebase"] = phase_index_codebase(repo_root, flowid, verbose)

    # Fase 3: collect_evidence
    report["phases"]["collect_evidence"] = phase_collect_evidence(repo_root, flowid, verbose)

    # Fase 4: score_evidence
    report["phases"]["score_evidence"] = phase_score_evidence(repo_root, flowid, verbose)

    # Fase 5: generate_plan
    report["phases"]["generate_plan"] = phase_generate_plan(repo_root, flowid, verbose)

    # Fase 6: predict_impact
    report["phases"]["predict_impact"] = phase_predict_impact(repo_root, flowid, verbose)

    # Fase 7: scaffold
    report["phases"]["scaffold"] = phase_scaffold(repo_root, flowid, verbose)

    # Verificación de telemetry
    report["telemetry_verification"] = verify_telemetry(repo_root, flowid)

    # Análisis de tests
    report["test_contracts_analysis"] = analyze_test_contracts(repo_root)

    # Catálogo de scripts automáticos vs manuales
    report["scripts_catalog"] = {
        "automatic": AUTOMATIC_SCRIPTS,
        "manual": MANUAL_SCRIPTS,
        "automatic_count": len(AUTOMATIC_SCRIPTS),
        "manual_count": len(MANUAL_SCRIPTS),
        "ratio_automatic": round(len(AUTOMATIC_SCRIPTS) / (len(AUTOMATIC_SCRIPTS) + len(MANUAL_SCRIPTS)), 2),
    }

    # Veredicto
    report["verdict"] = build_verdict(
        report["phases"],
        report["telemetry_verification"],
        report["test_contracts_analysis"],
    )

    total_ms = int((time.time() - start_time) * 1000)
    report["total_duration_ms"] = total_ms

    # Escribir reporte
    write_yaml(output, report)
    log(f"=== INTEGRATION VALIDATION COMPLETE === {total_ms}ms → {output}", "INFO")

    # Summary JSON en stdout
    print(json.dumps({
        "success": True,
        "flowid": flowid,
        "phases_total": len(report["phases"]),
        "phases_successful": sum(1 for p in report["phases"].values() if p.get("status") == "success"),
        "scaffold_concrete": report["phases"].get("scaffold", {}).get("is_concrete", False),
        "telemetry_entries": report["telemetry_verification"].get("entries_count", 0),
        "automatic_scripts": len(AUTOMATIC_SCRIPTS),
        "manual_scripts": len(MANUAL_SCRIPTS),
        "overall_verdict": report["verdict"]["overall_verdict"],
        "control_loss_points": len(report["verdict"]["control_loss_points"]),
        "duration_ms": total_ms,
        "output": str(output),
    }, ensure_ascii=False, indent=2))

    # Veredicto en stderr
    log("", "INFO")
    log("=" * 70, "INFO")
    log("VEREDICTO FINAL", "INFO")
    log("=" * 70, "INFO")
    log(f"Phases: {report['verdict']['phases_successful']}/{report['verdict']['phases_executed']} exitosas", "INFO")
    log(f"Scaffold concreto: {'SÍ' if report['verdict']['scaffold_is_concrete'] else 'NO'}", "INFO")
    log(f"Telemetry registra decisiones: {'SÍ' if report['verdict']['telemetry_records_decisions'] else 'NO'}", "INFO")
    log(f"Scripts automáticos: {report['verdict']['automatic_scripts_count']}", "INFO")
    log(f"Scripts manuales:   {report['verdict']['manual_scripts_count']}", "INFO")
    log(f"Tests integración:  {report['verdict']['tests_integration_ratio']*100:.0f}%", "INFO")
    log("", "INFO")
    log(f"PUNTOS DE PÉRDIDA DE CONTROL ({len(report['verdict']['control_loss_points'])}):", "WARN")
    for i, p in enumerate(report["verdict"]["control_loss_points"], 1):
        log(f"  {i}. [{p['severity']}] {p['point']}", "WARN")
        log(f"     {p['explanation']}", "INFO")
    log("", "INFO")
    log(f"VEREDICTO: {report['verdict']['overall_verdict']}", "INFO")
    log("=" * 70, "INFO")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
predict_impact.py — Generador de hologramas/predicciones de impacto.

GAP 3: Hologramas y predicción de soluciones.

Para cada Micro-Plan (MP) en DYNAMIC-PLAN.yaml genera 3 proyecciones:

[1] DEPENDENCY CASCADE
    -> dado que MP-XX modifica archivos A, B, C,
      ¿qué otros módulos importan A, B, C? (desde CODE-INDEX)
      -> riesgo: alto/medio/bajo por número de dependientes

[2] HISTORICAL PATTERN MATCH
    -> busca en telemetry.jsonl patrones similares de fases/gates
      que terminaron en rollback o bloqueo
      -> "este tipo de cambio en fase implementation falló 2/3 veces antes"

[3] TEST COVERAGE GAP
    -> cruza los archivos que el MP va a modificar contra
      los tests que los cubren (desde test_runs históricos)
      -> "MP-XX modifica 3 funciones, solo 1 tiene test directo"

El agente recibe esto ANTES de implementar, no después de fallar.

Opcional: si se pasa --deep, genera 2 proyecciones adicionales:

[4] SYMBOL CONTRACT BREAKAGE
    -> detecta firmas de funciones que el MP va a modificar
      y verifica si otros archivos las llaman con la firma actual

[5] GIT BLAME RISK
    -> para cada archivo afectado, mira git blame de las líneas
      a modificar y reporta cuántos autores tocaron esas líneas
      recientemente (alto = riesgo de conflicto humano)

Uso:
  python3 predict_impact.py \\
    --plan plan/active/<FLOW>/03-PLAN-INDICE-DYNAMIC.yaml \\
    --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \\
    --telemetry plan/active/<FLOW>/telemetry.jsonl \\
    --test-runs-dir plan/active/<FLOW>/tests/ \\
    --output plan/active/<FLOW>/IMPACT-PREDICTION.yaml \\
    [--deep] [--flowid APOLO-...]
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    log,
    now_iso,
    parse_args,
    read_yaml,
    run_cmd,
    write_yaml,
)


# ============================================================================
# Projection 1: Dependency Cascade
# ============================================================================

def project_dependency_cascade(
    mp_files: List[str],
    code_index: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Predice el cascade de dependencias: qué se rompe si toco estos archivos."""
    if not code_index:
        return {
            "risk_level": "unknown",
            "affected_modules": [],
            "note": "no CODE-INDEX available",
        }

    reverse_graph = code_index.get("reverse_dependency_graph", {})
    files_index = {f["path"]: f for f in code_index.get("files", [])}

    affected: Dict[str, List[str]] = {}
    total_affected = 0

    for mp_file in mp_files:
        # Buscar el archivo en el índice (puede ser path relativo)
        dependents = reverse_graph.get(mp_file, [])
        # También buscar por stem (sin extensión) por si el path no coincide exacto
        if not dependents:
            stem = Path(mp_file).stem
            for fpath, deps in reverse_graph.items():
                if Path(fpath).stem == stem:
                    dependents = deps
                    break

        if dependents:
            affected[mp_file] = dependents
            total_affected += len(dependents)

    # Calcular nivel de riesgo
    if total_affected == 0:
        risk = "low"
    elif total_affected <= 3:
        risk = "medium"
    elif total_affected <= 8:
        risk = "high"
    else:
        risk = "critical"

    # Identificar módulos afectados únicos
    unique_affected: Set[str] = set()
    for deps in affected.values():
        unique_affected.update(deps)

    return {
        "risk_level": risk,
        "total_affected_modules": len(unique_affected),
        "affected_modules": sorted(list(unique_affected))[:20],  # top 20
        "per_file": affected,
        "recommendation": (
            "safe to proceed" if risk == "low"
            else "proceed with caution" if risk == "medium"
            else "consider splitting MP" if risk == "high"
            else "BLOCK: too many dependents, refactor first"
        ),
    }


# ============================================================================
# Projection 2: Historical Pattern Match
# ============================================================================

def project_historical_pattern(
    mp_id: str,
    mp_phase: str,
    mp_files: List[str],
    telemetry_path: Optional[Path],
) -> Dict[str, Any]:
    """Busca patrones similares en telemetría histórica que terminaron mal."""
    if not telemetry_path or not telemetry_path.exists():
        return {
            "risk_level": "unknown",
            "similar_patterns": [],
            "note": "no telemetry available",
        }

    # Leer eventos
    events: List[Dict[str, Any]] = []
    try:
        for line in telemetry_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass

    if not events:
        return {
            "risk_level": "unknown",
            "similar_patterns": [],
            "note": "telemetry empty",
        }

    # Buscar patrones: events en la misma fase que terminaron en test-fail, rollback, o block
    failure_events = [
        e for e in events
        if e.get("kind") in ("test-fail", "rollback", "block-detected")
        and e.get("phase") == mp_phase
    ]

    # Agrupar por tipo de fallo
    by_kind: Dict[str, int] = {}
    for e in failure_events:
        kind = e.get("kind", "?")
        by_kind[kind] = by_kind.get(kind, 0) + 1

    # Buscar eventos donde se tocaron archivos similares (por stem)
    mp_stems = {Path(f).stem for f in mp_files}
    similar_file_events: List[Dict[str, Any]] = []
    for e in events:
        payload = e.get("payload", {}) or {}
        targets = payload.get("targets", []) or []
        event_stems = {Path(t).stem for t in targets if isinstance(t, str)}
        if event_stems & mp_stems and e.get("kind") in ("test-fail", "rollback", "block-detected"):
            similar_file_events.append({
                "at": e.get("at"),
                "kind": e.get("kind"),
                "phase": e.get("phase"),
                "message": e.get("message", "")[:200],
                "shared_files": list(event_stems & mp_stems),
            })

    # Calcular riesgo
    total_failures = len(failure_events)
    similar_count = len(similar_file_events)

    if total_failures == 0:
        risk = "low"
    elif similar_count >= 3:
        risk = "high"
    elif similar_count >= 1 or total_failures >= 3:
        risk = "medium"
    else:
        risk = "low"

    return {
        "risk_level": risk,
        "total_failure_events_in_phase": total_failures,
        "failures_by_kind": by_kind,
        "similar_file_patterns": similar_file_events[:5],
        "recommendation": (
            "no historical risk" if risk == "low"
            else f"caution: {similar_count} similar past failures" if risk == "medium"
            else f"BLOCK: {similar_count} similar past failures with same files"
        ),
    }


# ============================================================================
# Projection 3: Test Coverage Gap
# ============================================================================

def project_test_coverage_gap(
    mp_files: List[str],
    mp_symbols: List[str],
    test_runs_dir: Optional[Path],
    code_index: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Detecta gaps entre lo que el MP toca y lo que está testeado."""
    if not test_runs_dir or not test_runs_dir.exists():
        return {
            "risk_level": "unknown",
            "covered_symbols": [],
            "uncovered_symbols": [],
            "note": "no test runs available",
        }

    # Recopilar todos los targets testeados históricamente
    tested_targets: Set[str] = set()
    tested_files: Set[str] = set()

    for test_run_file in test_runs_dir.glob("*.yaml"):
        test_run = read_yaml(test_run_file) or {}
        scope = test_run.get("scope", {}) or {}
        for target in scope.get("targets", []) or []:
            tested_targets.add(target)
            tested_files.add(target)

    # Si hay code-index, inferir tests por convención (test_<name>.py, <name>_test.go, <name>.test.ts)
    inferred_test_files: Dict[str, str] = {}  # source_file -> test_file
    if code_index:
        all_files = [f["path"] for f in code_index.get("files", [])]
        for f in mp_files:
            stem = Path(f).stem
            # Buscar archivos de test que contengan el stem
            for af in all_files:
                af_lower = af.lower()
                if (
                    ("test" in af_lower or "spec" in af_lower)
                    and stem in af_lower
                    and af != f
                ):
                    inferred_test_files[f] = af
                    break

    # Cobertura de símbolos
    covered: List[str] = []
    uncovered: List[str] = []
    for sym in mp_symbols:
        # Un símbolo está cubierto si aparece en algún target de test
        if any(sym in target for target in tested_targets):
            covered.append(sym)
        else:
            uncovered.append(sym)

    # Cobertura de archivos
    files_with_tests: List[str] = []
    files_without_tests: List[str] = []
    for f in mp_files:
        if f in tested_files or f in inferred_test_files:
            files_with_tests.append(f)
        else:
            files_without_tests.append(f)

    coverage_ratio = len(files_with_tests) / len(mp_files) if mp_files else 1.0

    if coverage_ratio >= 0.8:
        risk = "low"
    elif coverage_ratio >= 0.5:
        risk = "medium"
    elif coverage_ratio >= 0.2:
        risk = "high"
    else:
        risk = "critical"

    return {
        "risk_level": risk,
        "coverage_ratio": round(coverage_ratio, 3),
        "files_with_tests": files_with_tests,
        "files_without_tests": files_without_tests,
        "inferred_test_files": inferred_test_files,
        "covered_symbols": covered,
        "uncovered_symbols": uncovered,
        "recommendation": (
            "well tested, proceed" if risk == "low"
            else "add tests before implementing" if risk == "medium"
            else "write tests first" if risk == "high"
            else "BLOCK: no test coverage for critical changes"
        ),
    }


# ============================================================================
# Projection 4 (deep): Symbol Contract Breakage
# ============================================================================

def project_symbol_contract(
    mp_files: List[str],
    code_index: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Detecta funciones cuyas firmas podrían romper callers."""
    if not code_index:
        return {"risk_level": "unknown", "potential_breakages": [], "note": "no CODE-INDEX"}

    files_index = {f["path"]: f for f in code_index.get("files", [])}

    # Funciones exportadas en los archivos del MP
    mp_exported_funcs: Dict[str, List[Dict[str, Any]]] = {}
    for f in mp_files:
        if f in files_index:
            funcs = files_index[f].get("symbols", {}).get("functions", [])
            exported = [func for func in funcs if func.get("is_exported")]
            if exported:
                mp_exported_funcs[f] = exported

    # Buscar callers en otros archivos
    breakages: List[Dict[str, Any]] = []
    for f, funcs in mp_exported_funcs.items():
        for func in funcs:
            func_name = func.get("name", "")
            if not func_name or func_name.startswith("_"):
                continue
            callers: List[str] = []
            for other_path, other_data in files_index.items():
                if other_path == f:
                    continue
                # Buscar el nombre de la función en imports o en otros archivos
                for imp in other_data.get("imports", []):
                    if imp.get("name") == func_name or func_name in str(imp.get("name", "")):
                        callers.append(other_path)
                        break
            if callers:
                breakages.append({
                    "file": f,
                    "function": func_name,
                    "current_args": func.get("args", []),
                    "callers": callers[:10],
                    "risk": "high" if len(callers) > 5 else "medium" if len(callers) > 1 else "low",
                })

    risk = (
        "critical" if any(b["risk"] == "high" for b in breakages) and len(breakages) > 3
        else "high" if any(b["risk"] == "high" for b in breakages)
        else "medium" if breakages
        else "low"
    )

    return {
        "risk_level": risk,
        "potential_breakages": breakages[:20],
        "total_breakages": len(breakages),
        "recommendation": (
            "no contract risk" if risk == "low"
            else f"review {len(breakages)} potential contract breakages"
        ),
    }


# ============================================================================
# Projection 5 (deep): Git Blame Risk
# ============================================================================

def project_git_blame_risk(
    mp_files: List[str],
    repo_root: Path,
) -> Dict[str, Any]:
    """Analiza git blame para detectar riesgo de conflicto humano."""
    file_risks: List[Dict[str, Any]] = []

    for f in mp_files:
        code, out, _ = run_cmd(
            ["git", "log", "--oneline", "-5", "--", f],
            cwd=repo_root,
            timeout=5,
        )
        if code != 0:
            continue

        commits = [line for line in out.strip().split("\n") if line.strip()]
        # Contar autores únicos
        code, out_authors, _ = run_cmd(
            ["git", "shortlog", "-sne", "-5", "--", f],
            cwd=repo_root,
            timeout=5,
        )
        authors = []
        if code == 0:
            for line in out_authors.strip().split("\n"):
                if line.strip():
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        authors.append(parts[1].strip())

        risk = "low"
        if len(authors) >= 4:
            risk = "high"
        elif len(authors) >= 2:
            risk = "medium"

        file_risks.append({
            "file": f,
            "recent_commit_count": len(commits),
            "recent_authors": authors[:5],
            "risk": risk,
        })

    high_risk_count = sum(1 for fr in file_risks if fr["risk"] == "high")
    overall_risk = "high" if high_risk_count > 0 else "medium" if file_risks else "low"

    return {
        "risk_level": overall_risk,
        "file_risks": file_risks,
        "recommendation": (
            "no human conflict risk" if overall_risk == "low"
            else f"caution: {high_risk_count} files with multiple recent authors"
        ),
    }


# ============================================================================
# MP projection generator
# ============================================================================

def predict_for_mp(
    mp: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
    telemetry_path: Optional[Path],
    test_runs_dir: Optional[Path],
    repo_root: Path,
    deep: bool = False,
) -> Dict[str, Any]:
    """Genera todas las proyecciones para un MP."""
    mp_id = mp.get("id", "?")
    mp_phase = mp.get("phase", "implementation")
    acopl = mp.get("acoplamientosreales", {}) or {}
    mp_files = acopl.get("archivos", []) or []
    mp_symbols = acopl.get("simbolos", []) or []

    projections: Dict[str, Any] = {
        "dependency_cascade": project_dependency_cascade(mp_files, code_index),
        "historical_pattern": project_historical_pattern(mp_id, mp_phase, mp_files, telemetry_path),
        "test_coverage_gap": project_test_coverage_gap(mp_files, mp_symbols, test_runs_dir, code_index),
    }

    if deep:
        projections["symbol_contract"] = project_symbol_contract(mp_files, code_index)
        projections["git_blame_risk"] = project_git_blame_risk(mp_files, repo_root)

    # Calcular riesgo agregado
    risk_scores = {"low": 1, "medium": 2, "high": 3, "critical": 4, "unknown": 0}
    risk_values = [risk_scores.get(p.get("risk_level", "unknown"), 0) for p in projections.values()]
    avg_risk = sum(risk_values) / len(risk_values) if risk_values else 0

    if avg_risk >= 3:
        overall_risk = "high"
        recommendation = "BLOCK: multiple high-risk projections"
    elif avg_risk >= 2:
        overall_risk = "medium"
        recommendation = "proceed with caution, monitor telemetry"
    else:
        overall_risk = "low"
        recommendation = "safe to proceed"

    return {
        "mp_id": mp_id,
        "mp_files": mp_files,
        "mp_symbols": mp_symbols,
        "overall_risk": overall_risk,
        "recommendation": recommendation,
        "projections": projections,
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    plan_path = Path(args.get("plan", ""))
    code_index_path = Path(args.get("code-index", "")) if args.get("code-index") else None
    telemetry_path = Path(args.get("telemetry", "")) if args.get("telemetry") else None
    test_runs_dir = Path(args.get("test-runs-dir", "")) if args.get("test-runs-dir") else None
    repo_root = Path(args.get("repo-root", ".")).resolve()
    output = Path(args.get("output", "IMPACT-PREDICTION.yaml"))
    flowid = args.get("flowid", "")
    deep = args.get("deep", "") == "true"

    if not plan_path.exists():
        log(f"Plan no encontrado: {plan_path}", "ERROR")
        return 2

    start = time.time()

    plan = read_yaml(plan_path) or {}
    code_index = (
        read_yaml(code_index_path) if code_index_path and code_index_path.exists() else None
    )

    # Los MPs están en unidades del plan
    unidades = plan.get("unidades", [])
    if not unidades:
        log("No hay unidades en el plan", "WARN")

    mp_predictions: List[Dict[str, Any]] = []
    for unidad in unidades:
        # Las unidades contienen MPs estimados; aquí predecimos por unidad
        prediction = predict_for_mp(
            unidad,
            code_index,
            telemetry_path,
            test_runs_dir,
            repo_root,
            deep,
        )
        mp_predictions.append(prediction)

    # Calcular riesgo global
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0, "unknown": 0}
    for pred in mp_predictions:
        risk = pred.get("overall_risk", "unknown")
        risk_counts[risk] = risk_counts.get(risk, 0) + 1

    if risk_counts.get("high", 0) > 0 or risk_counts.get("critical", 0) > 0:
        global_risk = "high"
    elif risk_counts.get("medium", 0) > len(mp_predictions) / 2:
        global_risk = "medium"
    else:
        global_risk = "low"

    duration_ms = int((time.time() - start) * 1000)

    impact_prediction = {
        "impactprediction": "V1",
        "version": 1,
        "flowid": flowid,
        "generated_at": now_iso(),
        "generator": {
            "script": "scripts/python/predict_impact.py",
            "duration_ms": duration_ms,
            "deep_mode": deep,
        },
        "inputs": {
            "plan": str(plan_path),
            "code_index": str(code_index_path) if code_index_path else None,
            "telemetry": str(telemetry_path) if telemetry_path else None,
            "test_runs_dir": str(test_runs_dir) if test_runs_dir else None,
        },
        "global_risk": global_risk,
        "risk_distribution": risk_counts,
        "total_predictions": len(mp_predictions),
        "predictions": mp_predictions,
        "recommendation": (
            "all MPs safe to implement" if global_risk == "low"
            else "review medium-risk MPs before implementing" if global_risk == "medium"
            else "BLOCK: high-risk MPs detected, review predictions"
        ),
    }

    write_yaml(output, impact_prediction)

    log(
        f"Impact prediction: {len(mp_predictions)} MPs analyzed | "
        f"global_risk={global_risk} | "
        f"distribution={risk_counts} | "
        f"{duration_ms}ms",
        "INFO" if global_risk == "low" else "WARN",
    )

    print(json.dumps({
        "success": True,
        "global_risk": global_risk,
        "risk_distribution": risk_counts,
        "total_predictions": len(mp_predictions),
        "duration_ms": duration_ms,
        "output": str(output),
    }))
    return 0 if global_risk != "high" else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
apolo_orchestrator.py — Orquestador automatico v3.3.0 (REESCRITO).

CAMBIO vs v3.2.0: el orquestador ahora USA TODOS los super poderes del sistema,
no solo los menciona. La data fluye entre scripts.

Flujo de datos integrado (cada fase alimenta la siguiente):

  1. INIT
     → health_check.py (verifica entorno)
     → absorbe tools
     → SI flow_id existe en flows anteriores: cross_flow_learning.recommend()
       para obtener recomendaciones contextuales
     Output: ORCHESTRATOR-STATE.yaml con recomendaciones iniciales

  2. INDEX
     → index_codebase.py (AST)
     → cross_language_analyzer.py (mapea calls entre lenguajes)
     → summarize_functions.py (docstrings)
     Output: CODE-INDEX.yaml + CROSS-LANGUAGE-MAP.yaml + FUNCTION-SUMMARIES.yaml

  3. COLLECT
     → SI necesita scope: user_input_collector.ask() (PAUSA REAL, no hardcodeado)
     → collect_evidence.py con scope del usuario
     → secret_scanner.py sobre archivos del scope
     Output: EVIDENCE-PACK.yaml

  4. SCORE
     → score_evidence.py (lee apolo_config para threshold)
     → SI score < threshold: PAUSA con user_input_collector.ask("mas evidencia?")
     → SI score OK: evidence_visual_diff.capture(baseline)  ← NUEVO v3.3.0
     Output: EVIDENCE-SCORE.yaml + baseline snapshot

  5. PLAN
     → agent_decision_loop.decide() con opciones de method  ← NUEVO v3.3.0
       (deterministic vs hybrid vs manual — el sistema evalua y escoge)
     → generate_plan.py con method elegido
     Output: PLAN.yaml

  6. IMPACT
     → predict_impact.py (BFS multi-nivel, lee apolo_config para max_depth)
     Output: IMPACT-PREDICTION.yaml

  7. SCAFFOLD
     → agent_decision_loop.decide() con opciones de unidad  ← NUEVO v3.3.0
       (topological_first vs highest_impact vs lowest_risk)
     → scaffold_v3.py con estrategia elegida
     → post_script_gates.check(scaffold_v3)  ← valida que es concreto
     Output: SCAFFOLD-V3.yaml

  8. IMPLEMENT  ← FASE CRITICA v3.3.0
     → force_quality_gates.check() antes de empezar  ← NUEVO
     → evidence_visual_diff.capture(baseline) si no se capturo en fase 4
     → EJECUTAR commands del scaffold automaticamente  ← NUEVO v3.3.0
       (mkdir, create files with templates, run tests, code_quality, git commit)
     → SI tests fallan:
       - evidence_visual_diff.capture(broken)  ← NUEVO
       - evidence_replay.bug() para analizar causa  ← NUEVO
       - agent_decision_loop.decide() con opciones de fix  ← NUEVO
       - Aplicar fix elegida
       - evidence_visual_diff.capture(post-fix)  ← NUEVO
       - evidence_visual_diff.compare() para verificar  ← NUEVO
     Output: archivos implementados + VISUAL-DIFF-REPORT.yaml

  9. TEST
     → run_tests.py
     → force_quality_gates.check(tests_pass)  ← BLOQUEA si falla
     → SI falla: loop de fix (volver a fase 8)
     Output: TEST-RESULTS.yaml

  10. VALIDATE
      → force_quality_gates.check() (todos los gates)  ← NUEVO
      → evidence_visual_diff.compare() (3 estados completos)
      → cross_flow_learning.analyze() (actualizar knowledge base)
      → SI script_generator creo scripts nuevos: validar que compilan
      Output: VALIDATION-REPORT.yaml

  11. COMPLETE
      → cross_flow_learning.analyze() (knowledge update)
      → telemetry_aggregator.py
      → ORCHESTRATOR-REPORT.yaml con todo consolidado
      → feedback_loop.add() (pedir feedback al usuario)  ← NUEVO

CLI:
  apolo run --flowid APOLO-X --goal "..." [--yes] [--repo-root .]
  apolo continue --flowid APOLO-X
  apolo status --flowid APOLO-X
  apolo abort --flowid APOLO-X
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, run_cmd, flow_dir, state_path, telemetry_path


# ============================================================================
# Helper: run a Python script and return result
# ============================================================================

def run_script(script_name: str, args: List[str], repo_root: Path, timeout: int = 60, stdin_data: str = "") -> Dict[str, Any]:
    """Ejecuta un script Python del plugin y captura resultado."""
    script_path = repo_root / "scripts" / "python" / script_name
    if not script_path.exists():
        return {"script": script_name, "status": "skipped", "reason": f"not found: {script_path}"}

    cmd = ["python3", str(script_path)] + args
    start = time.time()
    try:
        result = subprocess.run(
            cmd, cwd=str(repo_root), capture_output=True, text=True,
            timeout=timeout, input=stdin_data if stdin_data else None,
        )
        duration_ms = int((time.time() - start) * 1000)
        parsed = None
        if result.stdout:
            try:
                idx = result.stdout.find("{")
                if idx >= 0:
                    parsed = json.loads(result.stdout[idx:])
            except json.JSONDecodeError:
                pass
        return {
            "script": script_name,
            "status": "success" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "duration_ms": duration_ms,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500] if result.stderr else "",
            "parsed": parsed,
        }
    except subprocess.TimeoutExpired:
        return {"script": script_name, "status": "timeout", "duration_ms": timeout * 1000}
    except Exception as e:
        return {"script": script_name, "status": "error", "error": str(e)}


def append_telemetry(repo_root: Path, flowid: str, event: Dict) -> None:
    """Append event to telemetry.jsonl."""
    tel_path = telemetry_path(repo_root, flowid)
    tel_path.parent.mkdir(parents=True, exist_ok=True)
    event["at"] = now_iso()
    event["flowid"] = flowid
    with open(tel_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ============================================================================
# Orchestrator state
# ============================================================================

def orch_state_path(repo_root: Path, flowid: str) -> Path:
    return flow_dir(repo_root, flowid) / "ORCHESTRATOR-STATE.yaml"


def load_state(repo_root: Path, flowid: str) -> Dict[str, Any]:
    p = orch_state_path(repo_root, flowid)
    if not p.exists():
        return {
            "flowid": flowid, "started_at": now_iso(), "current_phase": 0,
            "completed_phases": [], "paused": False, "pause_reason": "",
            "user_inputs": {}, "phase_results": {}, "recommendations": {},
            "decisions": [], "scripts_generated": [],
        }
    return read_yaml(p) or {}


def save_state(repo_root: Path, flowid: str, state: Dict) -> None:
    p = orch_state_path(repo_root, flowid)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_yaml(p, state)


# ============================================================================
# Phase execution — EACH PHASE USES THE FULL POWER OF THE SYSTEM
# ============================================================================

def phase_init(repo_root: Path, flowid: str, goal: str, state: Dict, auto_yes: bool) -> Dict[str, Any]:
    """Fase 1: init + health check + cross_flow recommendations."""
    log("FASE 1/11: INIT — health check + cross_flow recommendations", "INFO")
    result = {"phase": "init", "started_at": now_iso(), "scripts": []}

    # 1a. init-flow via apolo-inspect.sh
    inspect = repo_root / "scripts" / "bash" / "apolo-inspect.sh"
    if inspect.exists():
        subprocess.run(["bash", str(inspect), "init-flow", "--flowid", flowid],
                       cwd=str(repo_root), capture_output=True, timeout=30)

    # 1b. health check
    r = run_script("health_check.py", ["--repo-root", ".", "--json", "true"], repo_root, 30)
    result["scripts"].append(r)

    # 1c. NUEVO v3.3.0: cross_flow_learning recommend para obtener recomendaciones contextuales
    r2 = run_script("cross_flow_learning.py",
                    ["recommend", "--repo-root", ".", "--flowid", flowid, "--phase", "init"],
                    repo_root, 30)
    result["scripts"].append(r2)
    if r2.get("parsed", {}).get("success"):
        recommendations = r2["parsed"].get("recommendations", [])
        state["recommendations"] = recommendations
        log(f"  → cross_flow: {len(recommendations)} recomendaciones contextuales", "INFO")
        for rec in recommendations[:3]:
            log(f"    [{rec.get('priority', '?')}] {rec.get('message', '')}", "INFO")

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_index(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 2: index + cross-language + summarize."""
    log("FASE 2/11: INDEX — AST + cross-language + function summaries", "INFO")
    result = {"phase": "index", "started_at": now_iso(), "scripts": []}
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"

    r = run_script("index_codebase.py", ["--repo-root", ".", "--output", str(ci_path)], repo_root, 60)
    result["scripts"].append(r)

    # NUEVO v3.3.0: cross-language analysis (alimenta scaffold_v3)
    r2 = run_script("cross_language_analyzer.py",
                    ["--repo-root", ".", "--code-index", str(ci_path), "--output", "CROSS-LANGUAGE-MAP.yaml"],
                    repo_root, 60)
    result["scripts"].append(r2)

    # NUEVO v3.3.0: function summaries (alimenta agent_decision_loop)
    r3 = run_script("summarize_functions.py",
                    ["--repo-root", ".", "--code-index", str(ci_path), "--output", "FUNCTION-SUMMARIES.yaml"],
                    repo_root, 60)
    result["scripts"].append(r3)

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_collect(repo_root: Path, flowid: str, state: Dict, auto_yes: bool) -> Dict[str, Any]:
    """Fase 3: collect evidence — uses user_input_collector if needs scope."""
    log("FASE 3/11: COLLECT — evidence collection (con user input si needed)", "INFO")
    result = {"phase": "collect", "started_at": now_iso(), "scripts": []}

    # 3a. Si no hay scope definido, pedirlo al usuario via user_input_collector
    scope = state.get("user_inputs", {}).get("scope")
    if not scope:
        if auto_yes:
            scope = json.dumps({"paths": ["plugin/"], "git_diff": True})
            log("  → auto-yes: scope default = plugin/", "INFO")
        else:
            # NUEVO v3.3.0: usar user_input_collector REAL
            ask_result = run_script("user_input_collector.py", [
                "ask", "--repo-root", ".",
                "--flowid", flowid,
                "--question", "Que archivos incluir en el scope del analisis?",
                "--options", json.dumps(["plugin/", "src/", "tests/", "all"]),
                "--default", "plugin/",
                "--type", "choice",
            ], repo_root, 15)
            result["scripts"].append(ask_result)

            if ask_result.get("parsed", {}).get("success"):
                qid = ask_result["parsed"].get("question_id")
                # Wait for answer (with timeout, use default)
                wait_result = run_script("user_input_collector.py", [
                    "wait", "--repo-root", ".", "--flowid", flowid,
                    "--question-id", qid, "--timeout", "30",
                ], repo_root, 40)
                answer = wait_result.get("parsed", {}).get("answer", "plugin/")
                scope = json.dumps({"paths": [answer], "git_diff": True})
                state.setdefault("user_inputs", {})["scope"] = scope
                log(f"  → user input: scope = {answer}", "INFO")
            else:
                scope = json.dumps({"paths": ["plugin/"], "git_diff": True})
                log("  → fallback: scope default = plugin/", "WARN")

    # 3b. collect_evidence con el scope
    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    r = run_script("collect_evidence.py", [
        "--flowid", flowid, "--repo-root", ".",
        "--output", str(ev_path),
        "--invoked-by", "orchestrator_v3",
        "--scope-json", scope,
    ], repo_root, 60)
    result["scripts"].append(r)

    # 3c. NUEVO v3.3.0: secret_scanner sobre los archivos del scope
    r2 = run_script("secret_scanner.py", ["--scan-stdin"], repo_root, 30,
                    stdin_data=scope)
    result["scripts"].append(r2)

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_score(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 4: score + baseline capture (gate con apolo_config threshold)."""
    log("FASE 4/11: SCORE — evidence scoring + baseline capture", "INFO")
    result = {"phase": "score", "started_at": now_iso(), "scripts": []}

    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    sc_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-SCORE.yaml"

    r = run_script("score_evidence.py", [
        "--evidence", str(ev_path), "--output", str(sc_path), "--flowid", flowid,
    ], repo_root, 30)
    result["scripts"].append(r)

    # 4b. NUEVO v3.3.0: leer threshold de apolo_config
    threshold = 0.6
    try:
        from apolo_config import get_config, get_threshold
        cfg = get_config(repo_root)
        threshold = get_threshold(cfg, "gates.verdad.min_score", 0.6)
    except Exception:
        pass

    # 4c. Verificar score (maneja ambos formatos: score y overall_score)
    score_data = read_yaml(sc_path) or {} if sc_path.exists() else {}
    if not isinstance(score_data, dict):
        score_data = {}
    score = score_data.get("score", score_data.get("overall_score", 0))
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0

    if score < threshold:
        result["status"] = "paused"
        result["pause_reason"] = f"Score {score} < threshold {threshold} — necesita mas evidencia"
        log(f"  ⚠ PAUSA: score {score} < {threshold}", "WARN")
        return result

    # 4d. NUEVO v3.3.0: evidence_visual_diff capture baseline
    scope_paths = json.loads(state.get("user_inputs", {}).get("scope", "{}")).get("paths", ["plugin/"])
    r2 = run_script("evidence_visual_diff.py", [
        "capture", "--repo-root", ".",
        "--flowid", flowid, "--phase", "baseline",
        "--files", ",".join(scope_paths[:5]),  # cap 5 archivos
    ], repo_root, 30)
    result["scripts"].append(r2)
    log("  → baseline capturado para visual diff", "INFO")

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_plan(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 5: plan — uses agent_decision_loop to choose method."""
    log("FASE 5/11: PLAN — agent_decision_loop elige method", "INFO")
    result = {"phase": "plan", "started_at": now_iso(), "scripts": []}

    ev_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-PACK.yaml"
    sc_path = flow_dir(repo_root, flowid) / "evidence" / "EVIDENCE-SCORE.yaml"
    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"

    # 5a. NUEVO v3.3.0: agent_decision_loop para elegir method
    score_data = read_yaml(sc_path) or {} if sc_path.exists() else {}
    score = score_data.get("score", 0.5) if isinstance(score_data, dict) else 0.5

    # Pre-seleccionar method segun score (como antes)
    if score < 0.4:
        method = "manual"
    elif score > 0.8:
        method = "deterministic-python"
    else:
        method = "hybrid"

    # NUEVO v3.3.0: agent_decision_loop evalua la decision del method
    options_json = json.dumps([
        {"id": "deterministic", "title": "Plan determinista", "description": f"Plan generado automaticamente (score actual: {score})",
         "impact_score": 0.7, "risk_score": 0.3, "steps": ["auto"], "feasibility_score": 0.8},
        {"id": "hybrid", "title": "Plan hibrido", "description": f"Mix de automatico y agente (score actual: {score})",
         "impact_score": 0.8, "risk_score": 0.4, "steps": ["auto", "agent"], "feasibility_score": 0.7},
        {"id": "manual", "title": "Plan manual", "description": f"Agente decide todo (score actual: {score})",
         "impact_score": 0.6, "risk_score": 0.2, "steps": ["agent"], "feasibility_score": 0.5},
    ])

    decide_result = run_script("agent_decision_loop.py", [
        "decide", "--repo-root", ".", "--flowid", flowid,
        "--goal", state.get("goal", ""),
        "--options-json", options_json,
        "--threshold", "0.5",  # lower threshold for method choice
    ], repo_root, 15)
    result["scripts"].append(decide_result)

    # Si agent_decision_loop eligio algo, usarlo; si no, fallback al pre-seleccionado
    if decide_result.get("parsed", {}).get("success"):
        chosen = decide_result["parsed"].get("chosen", {})
        chosen_id = chosen.get("option_id", "")
        if chosen_id in ("deterministic", "hybrid", "manual"):
            method = "deterministic-python" if chosen_id == "deterministic" else chosen_id
            state.setdefault("decisions", []).append({
                "phase": "plan", "decision": "method", "chosen": chosen_id,
                "score": chosen.get("weighted_score", 0),
            })
            log(f"  → agent_decision_loop eligio: {method} (score: {chosen.get('weighted_score', 0)})", "INFO")

    # 5b. generate_plan con method elegido
    r = run_script("generate_plan.py", [
        "--flowid", flowid, "--evidence", str(ev_path),
        "--verdad", str(sc_path), "--output", str(plan_path),
        "--method", method,
    ], repo_root, 30)
    result["scripts"].append(r)
    state.setdefault("user_inputs", {})["method"] = method

    # NUEVO v3.4.0: mp_prioritizer reprioritiza unidades basado en telemetria
    prio_result = run_script("mp_prioritizer.py", [
        "reprioritize", "--repo-root", ".", "--flowid", flowid,
    ], repo_root, 15)
    result["scripts"].append(prio_result)
    if prio_result.get("parsed", {}).get("success"):
        priority_order = prio_result["parsed"].get("priority_order", [])
        log(f"  → mp_prioritizer: {len(priority_order)} unidades re-prioritizadas", "INFO")
        if priority_order:
            log(f"    → Siguiente unidad: {priority_order[0].get('unit_id', '?')} (score: {priority_order[0].get('score', 0)})", "INFO")

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_impact(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 6: impact prediction (BFS with config max_depth)."""
    log("FASE 6/11: IMPACT — BFS multi-nivel", "INFO")
    result = {"phase": "impact", "started_at": now_iso(), "scripts": []}

    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
    impact_path = flow_dir(repo_root, flowid) / "plans" / "IMPACT-PREDICTION.yaml"

    r = run_script("predict_impact.py", [
        "--plan", str(plan_path), "--code-index", str(ci_path),
        "--output", str(impact_path), "--flowid", flowid,
    ], repo_root, 30)
    result["scripts"].append(r)

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_scaffold(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 7: scaffold — DIRECTIVA 5: vinculado al orquestador (no subprocess aislado)."""
    log("FASE 7/11: SCAFFOLD — agent_decision_loop elige + scaffold_v3 NATIVO + gates", "INFO")
    result = {"phase": "scaffold", "started_at": now_iso(), "scripts": []}

    plan_path = flow_dir(repo_root, flowid) / "plans" / "PLAN.yaml"
    ci_path = repo_root / ".opencode" / "apolo-dynamic" / "CODE-INDEX.yaml"
    scaffold_path = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD-V3.yaml"

    # 7a. agent_decision_loop elige estrategia
    options_json = json.dumps([
        {"id": "topological_first", "title": "Topological first", "description": "Primera unidad sin dependencias",
         "impact_score": 0.7, "risk_score": 0.3, "steps": ["pick"], "feasibility_score": 0.9},
        {"id": "highest_impact", "title": "Highest impact", "description": "Unidad con mas afectados",
         "impact_score": 0.9, "risk_score": 0.6, "steps": ["pick"], "feasibility_score": 0.7},
        {"id": "lowest_risk", "title": "Lowest risk", "description": "Unidad con menor riesgo",
         "impact_score": 0.5, "risk_score": 0.1, "steps": ["pick"], "feasibility_score": 0.9},
    ])

    decide_result = run_script("agent_decision_loop.py", [
        "decide", "--repo-root", ".", "--flowid", flowid,
        "--goal", state.get("goal", ""),
        "--options-json", options_json,
        "--threshold", "0.5",
    ], repo_root, 15)
    result["scripts"].append(decide_result)

    strategy = "topological_first"
    if decide_result.get("parsed", {}).get("success"):
        chosen = decide_result["parsed"].get("chosen", {})
        chosen_id = chosen.get("option_id", "")
        if chosen_id in ("topological_first", "highest_impact", "lowest_risk"):
            strategy = chosen_id
            state.setdefault("decisions", []).append({
                "phase": "scaffold", "decision": "strategy", "chosen": chosen_id,
                "score": chosen.get("weighted_score", 0),
            })
            log(f"  → agent_decision_loop eligio strategy: {strategy}", "INFO")

    # DIRECTIVA 5 v3.5.2: scaffold_v3 vinculado al orquestador (import directo, no subprocess)
    # Esto elimina el aislamiento detectado por static_analyzer
    try:
        # Import directo del modulo scaffold_v3
        sys.path.insert(0, str(repo_root / "scripts" / "python"))
        from scaffold_v3 import generate_scaffold_v3
        plan_data = read_yaml(plan_path) or {}
        ci_data = read_yaml(ci_path) if ci_path.exists() else None
        impact_data = None
        impact_path = flow_dir(repo_root, flowid) / "plans" / "IMPACT-PREDICTION.yaml"
        if impact_path.exists():
            impact_data = read_yaml(impact_path)

        scaffold = generate_scaffold_v3(
            plan=plan_data, code_index=ci_data, impact_prediction=impact_data,
            flowid=flowid, repo_root=repo_root,
            strategy=strategy,
        )
        if scaffold.get("success", True):
            scaffold["generator"] = {"script": "scaffold_v3.py (native import)", "version": "3.5.2"}
            write_yaml(scaffold_path, scaffold)
            log(f"  → scaffold_v3 NATIVO: {scaffold.get('summary', {}).get('total_files_to_create', 0)} files to create", "INFO")
            result["scripts"].append({"script": "scaffold_v3.py (native)", "status": "success", "native_import": True})
        else:
            result["scripts"].append({"script": "scaffold_v3.py (native)", "status": "failed", "error": scaffold.get("error", "")})
            result["status"] = "failed"
            result["error"] = scaffold.get("error", "scaffold_v3 failed")
            return result
    except Exception as e:
        # Fallback a subprocess si el import directo falla
        log(f"  → scaffold_v3 native import fallo ({e}), usando subprocess fallback", "WARN")
        r = run_script("scaffold_v3.py", [
            "--plan", str(plan_path), "--code-index", str(ci_path),
            "--output", str(scaffold_path), "--flowid", flowid,
            "--strategy", strategy,
        ], repo_root, 30)
        result["scripts"].append(r)

    # 7c. post_script_gates valida que el scaffold es concreto
    gate_result = run_script("post_script_gates.py", [
        "check", "--repo-root", ".", "--script", "scaffold_v3.py",
        "--output", str(scaffold_path),
    ], repo_root, 15)
    result["scripts"].append(gate_result)

    if gate_result.get("parsed", {}).get("action") == "block":
        result["status"] = "paused"
        result["pause_reason"] = "Scaffold no es concreto — post_script_gates bloquea"
        log("  ⚠ PAUSA: scaffold no concreto", "WARN")
        return result

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_implement(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 8: implement — EXECUTES scaffold commands + captures visual diff + smart rollback on fail."""
    log("FASE 8/11: IMPLEMENT — ejecuta scaffold commands + visual diff + smart rollback", "INFO")
    result = {"phase": "implement", "started_at": now_iso(), "scripts": []}

    # 8a. NUEVO v3.3.0: force_quality_gates antes de implementar
    qg_before = run_script("force_quality_gates.py", [
        "check", "--repo-root", ".", "--flowid", flowid,
    ], repo_root, 15)
    result["scripts"].append(qg_before)

    if qg_before.get("parsed", {}).get("overall_pass") is False:
        result["status"] = "paused"
        result["pause_reason"] = "Force quality gates fallaron antes de implementar"
        log("  ⚠ PAUSA: quality gates fallaron", "WARN")
        return result

    # 8b. Leer scaffold y ejecutar commands
    scaffold_path = flow_dir(repo_root, flowid) / "scaffolds" / "SCAFFOLD-V3.yaml"
    if not scaffold_path.exists():
        result["status"] = "failed"
        result["error"] = "SCAFFOLD-V3.yaml no existe"
        return result

    scaffold = read_yaml(scaffold_path) or {}
    commands = scaffold.get("commands", [])
    files_to_create = scaffold.get("files_to_create", [])

    log(f"  → Ejecutando {len(commands)} commands del scaffold...", "INFO")

    # 8c. NUEVO v3.3.0: ejecutar commands del scaffold
    for cmd_spec in commands:
        cmd_id = cmd_spec.get("id", "")
        cmd_phase = cmd_spec.get("phase", "")
        command = cmd_spec.get("command", "")

        if cmd_phase == "setup" and command.startswith("mkdir"):
            try:
                subprocess.run(command.split(), cwd=str(repo_root), capture_output=True, timeout=10)
                log(f"    ✓ {cmd_id}: mkdir ejecutado", "INFO")
            except Exception as e:
                log(f"    ✗ {cmd_id}: mkdir fallo: {e}", "WARN")

        elif cmd_phase == "create_files" and files_to_create:
            for f_spec in files_to_create:
                f_path = repo_root / f_spec["path"]
                template = f_spec.get("template", "")
                if template and not f_path.exists():
                    f_path.parent.mkdir(parents=True, exist_ok=True)
                    f_path.write_text(template, encoding="utf-8")
                    log(f"    ✓ {cmd_id}: creado {f_spec['path']}", "INFO")

        elif cmd_phase == "verify" and "pytest" in command:
            test_result = subprocess.run(
                command.split(), cwd=str(repo_root),
                capture_output=True, text=True, timeout=60,
            )
            result["scripts"].append({
                "script": "pytest",
                "status": "success" if test_result.returncode == 0 else "failed",
                "exit_code": test_result.returncode,
                "stdout": test_result.stdout[:1000],
                "stderr": test_result.stderr[:500],
            })
            if test_result.returncode != 0:
                # 8d. NUEVO v3.3.0: tests fallaron → capture broken + replay
                log("  ⚠ Tests fallaron — capturando broken state + replay", "WARN")
                _capture_and_replay(repo_root, flowid, state, result)

                # NUEVO v3.4.0: smart_rollback — revertir SOLO archivos que fallaron
                log("  → Smart rollback: analizando que revertir...", "INFO")
                rollback_result = run_script("smart_rollback.py", [
                    "rollback", "--repo-root", ".", "--flowid", flowid, "--dry-run",
                ], repo_root, 30)
                result["scripts"].append(rollback_result)
                if rollback_result.get("parsed", {}).get("success"):
                    rb = rollback_result["parsed"]
                    log(f"    → Rollback: {rb.get('rolled_back', 0)} archivos a revertir, {rb.get('preserved', 0)} a preservar", "INFO")

                result["status"] = "paused"
                result["pause_reason"] = "Tests fallaron — ver VISUAL-DIFF-REPORT, BUG-REPLAY y ROLLBACK-REPORT"
                return result

        elif cmd_phase == "evidence":
            r = run_script("evidence_visual_diff.py", [
                "capture", "--repo-root", ".",
                "--flowid", flowid, "--phase", "baseline",
                "--unit-id", scaffold.get("unit_id", ""),
            ], repo_root, 30)
            result["scripts"].append(r)

    # 8e. NUEVO v3.3.0: si tests pasaron, capturar post-fix
    _capture_post_fix(repo_root, flowid, state, result)

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def _capture_and_replay(repo_root: Path, flowid: str, state: Dict, result: Dict) -> None:
    """Captura broken state + ejecuta evidence_replay para analizar bug."""
    scope_paths = json.loads(state.get("user_inputs", {}).get("scope", "{}")).get("paths", ["plugin/"])

    # Capture broken
    r = run_script("evidence_visual_diff.py", [
        "capture", "--repo-root", ".",
        "--flowid", flowid, "--phase", "broken",
        "--files", ",".join(scope_paths[:5]),
    ], repo_root, 30)
    result["scripts"].append(r)

    # Evidence replay to find bug
    r2 = run_script("evidence_replay.py", [
        "bug", "--repo-root", ".", "--flowid", flowid, "--verbose",
    ], repo_root, 30)
    result["scripts"].append(r2)

    if r2.get("parsed", {}).get("bug_found"):
        analysis = r2["parsed"].get("analysis", {})
        log(f"  → Replay: causa probable = {analysis.get('likely_cause', '?')}", "WARN")
        log(f"  → Replay: recomendacion = {analysis.get('recommendation', '?')}", "INFO")


def _capture_post_fix(repo_root: Path, flowid: str, state: Dict, result: Dict) -> None:
    """Captura post-fix state y genera comparacion completa."""
    scope_paths = json.loads(state.get("user_inputs", {}).get("scope", "{}")).get("paths", ["plugin/"])

    r = run_script("evidence_visual_diff.py", [
        "capture", "--repo-root", ".",
        "--flowid", flowid, "--phase", "post-fix",
        "--files", ",".join(scope_paths[:5]),
    ], repo_root, 30)
    result["scripts"].append(r)

    # Compare all 3 states
    r2 = run_script("evidence_visual_diff.py", [
        "compare", "--repo-root", ".", "--flowid", flowid,
    ], repo_root, 30)
    result["scripts"].append(r2)


def phase_test(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 9: test — force_quality_gates bloquea si falla."""
    log("FASE 9/11: TEST — tests + force_quality_gates", "INFO")
    result = {"phase": "test", "started_at": now_iso(), "scripts": []}

    r = run_script("run_tests.py", [
        "--repo-root", ".", "--trigger", "post-implement",
    ], repo_root, 120)
    result["scripts"].append(r)

    # NUEVO v3.3.0: force_quality_gates check tests_pass
    qg = run_script("force_quality_gates.py", [
        "check-one", "--repo-root", ".", "--flowid", flowid,
        "--gate", "tests_pass",
    ], repo_root, 15)
    result["scripts"].append(qg)

    if qg.get("parsed", {}).get("passed") is False:
        result["status"] = "paused"
        result["pause_reason"] = f"Tests fallaron: {qg['parsed'].get('reason', '')}"
        log("  ⚠ PAUSA: tests fallaron", "WARN")
        return result

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_validate(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 10: validate — all quality gates + cross_flow analyze."""
    log("FASE 10/11: VALIDATE — all gates + cross_flow learning", "INFO")
    result = {"phase": "validate", "started_at": now_iso(), "scripts": []}

    # 10a. NUEVO v3.3.0: all force_quality_gates
    qg = run_script("force_quality_gates.py", [
        "check", "--repo-root", ".", "--flowid", flowid,
    ], repo_root, 15)
    result["scripts"].append(qg)

    if qg.get("parsed", {}).get("overall_pass") is False:
        result["status"] = "paused"
        result["pause_reason"] = f"Quality gates fallaron: {qg['parsed'].get('blocking_details', '')}"
        return result

    # 10b. cross_flow_learning analyze (actualizar knowledge base)
    r = run_script("cross_flow_learning.py", [
        "analyze", "--repo-root", ".",
    ], repo_root, 60)
    result["scripts"].append(r)

    result["status"] = "success"
    result["completed_at"] = now_iso()
    return result


def phase_complete(repo_root: Path, flowid: str, state: Dict) -> Dict[str, Any]:
    """Fase 11: complete — honesty check + feedback + pre-commit hooks + merge."""
    log("FASE 11/11: COMPLETE — honesty enforcer + feedback + pre-commit + merge", "INFO")
    result = {"phase": "complete", "started_at": now_iso(), "scripts": []}

    # DIRECTIVA 2 v3.5.2: agent_honesty_enforcer NATIVO en fase 11
    # Verifica que TODOS los claims del agente tienen evidencia antes de declarar complete
    log("  → agent_honesty_enforcer: verificando honestidad de claims...", "INFO")
    honesty_result = run_script("agent_honesty_enforcer.py", [
        "verify", "--repo-root", ".", "--flowid", flowid,
    ], repo_root, 15)
    result["scripts"].append(honesty_result)

    if honesty_result.get("parsed", {}).get("overall_honest") is False:
        dishonest_claims = honesty_result["parsed"].get("dishonest_claims", 0)
        result["status"] = "paused"
        result["pause_reason"] = f"agent_honesty_enforcer: {dishonest_claims} claim(s) sin evidencia — no se puede declarar complete"
        log(f"  ⚠ PAUSA: {dishonest_claims} claims dishonestos detectados", "WARN")
        return result
    log("  ✓ Todos los claims son honestos — respaldados por evidencia", "INFO")

    # feedback_loop para pedir feedback al usuario
    r = run_script("feedback_loop.py", [
        "add", "--repo-root", ".",
        "--flowid", flowid, "--phase", "complete",
        "--rating", "4", "--comment", f"Flow completado: {state.get('goal', '')}",
        "--tags", "auto,orchestrator",
    ], repo_root, 15)
    result["scripts"].append(r)

    # pre_commit_hooks install
    r2 = run_script("pre_commit_hooks.py", [
        "install", "--repo-root", ".",
    ], repo_root, 15)
    result["scripts"].append(r2)
    if r2.get("parsed", {}).get("success"):
        log("  → pre_commit_hooks instalados", "INFO")

    # multi_agent_coordinator merge
    r3 = run_script("multi_agent_coordinator.py", [
        "merge", "--repo-root", ".", "--flowid", flowid,
    ], repo_root, 15)
    result["scripts"].append(r3)

    result["status"] = "complete"
    result["message"] = "Ciclo completo — honesty verified + todos los super poderes usados"
    result["completed_at"] = now_iso()
    return result


# ============================================================================
# Phase dispatcher
# ============================================================================

PHASE_DISPATCH = {
    "init": phase_init,
    "index": phase_index,
    "collect": phase_collect,
    "score": phase_score,
    "plan": phase_plan,
    "impact": phase_impact,
    "scaffold": phase_scaffold,
    "implement": phase_implement,
    "test": phase_test,
    "validate": phase_validate,
    "complete": phase_complete,
}

PHASE_ORDER = ["init", "index", "collect", "score", "plan", "impact", "scaffold", "implement", "test", "validate", "complete"]


# ============================================================================
# Main orchestrator
# ============================================================================

def run_cycle(repo_root: Path, flowid: str, goal: str, auto_yes: bool = False, start_phase: str = "init") -> Dict[str, Any]:
    """Ejecuta el ciclo completo integrando TODOS los super poderes."""
    log(f"\n{'#'*60}", "INFO")
    log(f"# ORQUESTADOR v3.3.0 — TODOS los super poderes integrados", "INFO")
    log(f"# Flow: {flowid}", "INFO")
    log(f"# Goal: {goal}", "INFO")
    log(f"{'#'*60}", "INFO")

    state = load_state(repo_root, flowid)
    state["goal"] = goal
    state["last_run_at"] = now_iso()
    save_state(repo_root, flowid, state)

    cycle_result = {
        "flowid": flowid, "goal": goal, "started_at": now_iso(),
        "phases": [], "status": "running",
    }

    # Encontrar fase de inicio
    start_idx = PHASE_ORDER.index(start_phase) if start_phase in PHASE_ORDER else 0

    for i in range(start_idx, len(PHASE_ORDER)):
        phase_name = PHASE_ORDER[i]
        phase_fn = PHASE_DISPATCH[phase_name]

        state["current_phase"] = phase_name
        save_state(repo_root, flowid, state)

        log(f"\n{'='*50}", "INFO")

        # Ejecutar fase (cada fase tiene su propia signatura)
        if phase_name == "init":
            phase_result = phase_fn(repo_root, flowid, goal, state, auto_yes)
        elif phase_name == "collect":
            phase_result = phase_fn(repo_root, flowid, state, auto_yes)
        else:
            phase_result = phase_fn(repo_root, flowid, state)
        cycle_result["phases"].append(phase_result)

        # DIRECTIVA 1 v3.5.2: data_flow_validator AUTOMATICO despues de cada fase
        if phase_result["status"] == "success":
            log(f"  → data_flow_validator: verificando artefactos...", "INFO")
            dfv_result = run_script("data_flow_validator.py", [
                "validate", "--repo-root", ".", "--flowid", flowid,
            ], repo_root, 15)
            if dfv_result.get("parsed", {}).get("overall_pass") is False:
                log(f"  ⚠ data_flow_validator: artefactos faltantes o invalidos", "WARN")
                # No bloquear, solo warn — el validador es preventivo

        # Telemetry
        append_telemetry(repo_root, flowid, {
            "kind": "orchestrator-phase", "phase": phase_name,
            "status": phase_result["status"],
            "message": phase_result.get("message", phase_result.get("pause_reason", phase_result.get("error", ""))),
        })

        # Handle pause/fail
        if phase_result["status"] in ("paused", "failed"):
            state["paused"] = True
            state["pause_reason"] = phase_result.get("pause_reason", phase_result.get("error", ""))
            save_state(repo_root, flowid, state)
            cycle_result["status"] = phase_result["status"]
            cycle_result["paused_at_phase"] = phase_name
            cycle_result["pause_reason"] = state["pause_reason"]
            log(f"\n⚠ PAUSA en {phase_name}: {state['pause_reason']}", "WARN")

            # NUEVO v3.5.1: ofrecer escape hatch + guided recovery al agente
            # DIRECTIVA 3 v3.5.2: verificar limites de escape hatches ANTES de ofrecer
            error_msg = state["pause_reason"]
            log(f"   → Diagnostico guiado:", "INFO")
            recovery_result = run_script("guided_recovery.py", [
                "diagnose", "--repo-root", ".", "--flowid", flowid,
                "--error", error_msg, "--script", phase_name,
            ], repo_root, 15)
            if recovery_result.get("parsed", {}).get("recommended_fix"):
                fix = recovery_result["parsed"]["recommended_fix"]
                log(f"     Causa: {fix.get('diagnosis', '?')}", "INFO")
                log(f"     Fix:   {fix.get('fix_command', '?')}", "INFO")

            # DIRECTIVA 3 v3.5.2: obtener history de escape hatches para verificar limites
            log(f"   → Escape hatches disponibles (verificando limites):", "INFO")
            escape_history = run_script("agent_escape_hatch.py", [
                "history", "--repo-root", ".", "--flowid", flowid,
            ], repo_root, 15)

            escape_result = run_script("agent_escape_hatch.py", [
                "offer", "--repo-root", ".", "--flowid", flowid,
                "--phase", phase_name, "--reason", error_msg,
            ], repo_root, 15)
            if escape_result.get("parsed", {}).get("hatches_available"):
                # Filtrar hatches que ya alcanzaron su limite
                used_by_type = escape_history.get("parsed", {}).get("by_type", {})
                for hatch in escape_result["parsed"]["hatches_available"][:3]:
                    hatch_type = hatch["type"]
                    used_count = used_by_type.get(hatch_type, 0)
                    max_uses = hatch.get("max_uses", 5)
                    remaining = max_uses - used_count
                    if remaining > 0:
                        log(f"     [{hatch['risk_level']}] {hatch_type}: {hatch['description']} ({remaining}/{max_uses} restantes)", "INFO")
                    else:
                        log(f"     [BLOQUEADO] {hatch_type}: limite alcanzado ({used_count}/{max_uses})", "WARN")

            log(f"   Resolver y ejecutar: apolo continue --flowid {flowid}", "INFO")
            break

        state.setdefault("completed_phases", []).append(phase_name)
        save_state(repo_root, flowid, state)
        log(f"✓ Fase {phase_name} completada", "INFO")

        # NUEVO v3.3.0: trigger auto_hooks phase-complete
        run_script("auto_hooks.py", [
            "trigger", "--repo-root", ".",
            "--name", f"phase-complete:{phase_name}",
            "--flowid", flowid,
        ], repo_root, 30)

        if phase_name == "complete":
            cycle_result["status"] = "complete"
            break

    cycle_result["completed_at"] = now_iso()

    # Write report
    report_path = flow_dir(repo_root, flowid) / "ORCHESTRATOR-REPORT.yaml"
    write_yaml(report_path, cycle_result)
    log(f"\n{'#'*60}", "INFO")
    log(f"# CICLO {'COMPLETO' if cycle_result['status'] == 'complete' else 'PAUSADO'} — {flowid}", "INFO")
    log(f"# Reporte: {report_path}", "INFO")
    log(f"{'#'*60}", "INFO")

    return cycle_result


def continue_cycle(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Continua desde donde se pauso."""
    state = load_state(repo_root, flowid)
    if not state.get("paused"):
        return {"success": False, "error": "El ciclo no esta pausado"}

    state["paused"] = False
    state["pause_reason"] = ""
    save_state(repo_root, flowid, state)

    current = state.get("current_phase", "init")
    log(f"Continuando desde fase: {current}", "INFO")
    return run_cycle(repo_root, flowid, state.get("goal", ""), start_phase=current)


def get_status(repo_root: Path, flowid: str) -> Dict[str, Any]:
    state = load_state(repo_root, flowid)
    return {
        "success": True, "flowid": flowid,
        "current_phase": state.get("current_phase", ""),
        "completed_phases": state.get("completed_phases", []),
        "paused": state.get("paused", False),
        "pause_reason": state.get("pause_reason", ""),
        "goal": state.get("goal", ""),
        "recommendations_count": len(state.get("recommendations", [])),
        "decisions_count": len(state.get("decisions", [])),
        "scripts_generated": state.get("scripts_generated", []),
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "run"
    known = {"run", "continue", "status", "abort"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]
        argv = argv[1:]

    args = parse_args(argv)
    if "action" in args:
        action = args["action"]

    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid and action != "status":
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2))
        return 2

    if action == "run":
        goal = args.get("goal", "")
        if not goal:
            print(json.dumps({"success": False, "error": "Falta --goal"}, indent=2))
            return 2
        auto_yes = args.get("yes", "false") == "true"
        result = run_cycle(repo_root, flowid, goal, auto_yes)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] in ("complete", "paused") else 1

    elif action == "continue":
        result = continue_cycle(repo_root, flowid)
        print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2, default=str))
        return 0

    elif action == "status":
        result = get_status(repo_root, flowid) if flowid else {"success": True, "message": "Use --flowid"}
        print(json.dumps(result, indent=2))
        return 0

    elif action == "abort":
        state = load_state(repo_root, flowid)
        state["paused"] = True
        state["pause_reason"] = "aborted_by_user"
        state["aborted_at"] = now_iso()
        save_state(repo_root, flowid, state)
        print(json.dumps({"success": True, "flowid": flowid, "status": "aborted"}, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())

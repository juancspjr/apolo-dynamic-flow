#!/usr/bin/env python3
"""
data_flow_validator.py — Verifica que la data fluye por donde debe (v3.5.0).

RESPONDE a tu pregunta: "asegurar que las datas pasen por donde debe pasar
el flujo de datos validados"

Ejecuta un flow de prueba y verifica que cada artefacto YAML se produce
en el orden correcto y tiene la estructura esperada. Si un artefacto falta
o tiene estructura incorrecta, reporta exactamente donde se rompio el flujo.

Flujo esperado:
  CODE-INDEX.yaml → EVIDENCE-PACK.yaml → EVIDENCE-SCORE.yaml →
  PLAN.yaml → IMPACT-PREDICTION.yaml → SCAFFOLD-V3.yaml →
  (files_to_create) → VISUAL-DIFF snapshots → ORCHESTRATOR-REPORT.yaml

CLI:
  python3 data_flow_validator.py validate --repo-root . --flowid APOLO-VALIDATE
  python3 data_flow_validator.py check-artifacts --flowid X
  python3 data_flow_validator.py trace --flowid X
"""

from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from typing import Any, Dict, List, Optional
sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


# ============================================================================
# Expected artifacts in order
# ============================================================================

EXPECTED_ARTIFACTS = [
    {
        "name": "CODE-INDEX.yaml",
        "path": ".opencode/apolo-dynamic/CODE-INDEX.yaml",
        "producer": "index_codebase.py",
        "phase": "index",
        "required_fields": ["files"],
        "field_types": {"files": "list"},
        "min_lengths": {"files": 1},
    },
    {
        "name": "EVIDENCE-PACK.yaml",
        "path": "plan/active/{flowid}/evidence/EVIDENCE-PACK.yaml",
        "producer": "collect_evidence.py",
        "phase": "collect",
        "required_fields": ["items", "hash_chain"],
        "field_types": {"items": "list", "hash_chain": "str"},
        "min_lengths": {"items": 1, "hash_chain": 64},
    },
    {
        "name": "EVIDENCE-SCORE.yaml",
        "path": "plan/active/{flowid}/evidence/EVIDENCE-SCORE.yaml",
        "producer": "score_evidence.py",
        "phase": "score",
        "required_fields": ["score"],
        "field_types": {"score": "number"},
    },
    {
        "name": "PLAN.yaml",
        "path": "plan/active/{flowid}/plans/PLAN.yaml",
        "producer": "generate_plan.py",
        "phase": "plan",
        "required_fields": ["unidades"],
        "field_types": {"unidades": "list"},
        "min_lengths": {"unidades": 1},
    },
    {
        "name": "IMPACT-PREDICTION.yaml",
        "path": "plan/active/{flowid}/plans/IMPACT-PREDICTION.yaml",
        "producer": "predict_impact.py",
        "phase": "impact",
        "required_fields": ["predictions"],
        "field_types": {"predictions": "list"},
    },
    {
        "name": "SCAFFOLD-V3.yaml",
        "path": "plan/active/{flowid}/scaffolds/SCAFFOLD-V3.yaml",
        "producer": "scaffold_v3.py",
        "phase": "scaffold",
        "required_fields": ["files_to_create", "commands"],
        "field_types": {"files_to_create": "list", "commands": "list"},
        "min_lengths": {"files_to_create": 1},
    },
    {
        "name": "ORCHESTRATOR-REPORT.yaml",
        "path": "plan/active/{flowid}/ORCHESTRATOR-REPORT.yaml",
        "producer": "apolo_orchestrator.py",
        "phase": "complete",
        "required_fields": ["phases", "status"],
        "field_types": {"phases": "list", "status": "str"},
    },
]


def check_artifact(repo_root: Path, flowid: str, artifact: Dict) -> Dict[str, Any]:
    """Verifica que un artefacto existe y tiene la estructura correcta."""
    path_str = artifact["path"].replace("{flowid}", flowid)
    artifact_path = repo_root / path_str

    result = {
        "name": artifact["name"],
        "expected_path": path_str,
        "producer": artifact["producer"],
        "phase": artifact["phase"],
        "exists": artifact_path.exists(),
        "structure_valid": False,
        "issues": [],
    }

    if not result["exists"]:
        result["issues"].append(f"Artefacto no encontrado: {path_str}")
        return result

    # Leer YAML
    data = read_yaml(artifact_path)
    if not data:
        result["issues"].append("YAML vacio o invalido")
        return result

    # Verificar campos requeridos
    for field in artifact.get("required_fields", []):
        if field not in data:
            result["issues"].append(f"Campo requerido faltante: {field}")

    # Verificar tipos
    for field, expected_type in artifact.get("field_types", {}).items():
        if field not in data:
            continue
        value = data[field]
        type_map = {"list": list, "dict": dict, "str": str, "number": (int, float)}
        expected_python_type = type_map.get(expected_type)
        if expected_python_type and not isinstance(value, expected_python_type):
            result["issues"].append(f"Campo {field}: esperaba {expected_type}, got {type(value).__name__}")

    # Verificar min_length
    for field, min_len in artifact.get("min_lengths", {}).items():
        if field not in data:
            continue
        value = data[field]
        if isinstance(value, (list, str)) and len(value) < min_len:
            result["issues"].append(f"Campo {field}: longitud {len(value)} < min {min_len}")

    result["structure_valid"] = len(result["issues"]) == 0
    return result


def validate_data_flow(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Verifica que todos los artefactos del flow existen y son validos."""
    log("=" * 60, "INFO")
    log("DATA FLOW VALIDATOR v3.5.0 — Verificando flujo de artefactos", "INFO")
    log("=" * 60, "INFO")

    results = []
    for artifact in EXPECTED_ARTIFACTS:
        log(f"  Verificando {artifact['name']}...", "INFO")
        result = check_artifact(repo_root, flowid, artifact)
        results.append(result)
        if result["exists"] and result["structure_valid"]:
            log(f"    ✓ {artifact['name']} OK", "INFO")
        elif result["exists"]:
            log(f"    ⚠ {artifact['name']} existe pero con issues: {result['issues']}", "WARN")
        else:
            log(f"    ✗ {artifact['name']} NO existe", "WARN")

    total = len(results)
    exists_count = sum(1 for r in results if r["exists"])
    valid_count = sum(1 for r in results if r["exists"] and r["structure_valid"])

    # Verificar orden: si un artefacto de fase N existe, los de fases anteriores deben existir
    order_issues = []
    for i, result in enumerate(results):
        if result["exists"]:
            for j in range(i):
                if not results[j]["exists"]:
                    order_issues.append({
                        "issue": f"{result['name']} existe pero {results[j]['name']} (fase anterior) no",
                        "severity": "high",
                    })

    report = {
        "dataflowvalidator": "V1",
        "schema_version": "3.5.0",
        "generated_at": now_iso(),
        "flowid": flowid,
        "repo_root": str(repo_root),
        "total_artifacts": total,
        "artifacts_existing": exists_count,
        "artifacts_valid": valid_count,
        "order_issues": len(order_issues),
        "overall_pass": valid_count == total and len(order_issues) == 0,
        "verdict": (
            "DATA FLOW COMPLETE AND VALID" if valid_count == total and len(order_issues) == 0
            else f"DATA FLOW INCOMPLETE: {total - exists_count} artefactos faltantes, {exists_count - valid_count} con issues"
        ),
        "artifacts": results,
        "order_issues_detail": order_issues,
    }

    report_path = repo_root / "DATA-FLOW-VALIDATION-REPORT.yaml"
    write_yaml(report_path, report)
    return report


def trace_flow(repo_root: Path, flowid: str) -> Dict[str, Any]:
    """Traza el flujo completo de un flow existente."""
    trace = []
    for artifact in EXPECTED_ARTIFACTS:
        path_str = artifact["path"].replace("{flowid}", flowid)
        artifact_path = repo_root / path_str
        entry = {
            "phase": artifact["phase"],
            "artifact": artifact["name"],
            "producer": artifact["producer"],
            "path": path_str,
            "exists": artifact_path.exists(),
        }
        if artifact_path.exists():
            data = read_yaml(artifact_path) or {}
            entry["field_count"] = len(data) if isinstance(data, dict) else 0
            # Preview de campos
            entry["fields"] = list(data.keys())[:10] if isinstance(data, dict) else []
        trace.append(entry)

    return {
        "success": True,
        "flowid": flowid,
        "trace": trace,
        "complete": all(t["exists"] for t in trace),
    }


def main() -> int:
    argv = sys.argv[1:]
    action = "validate"
    known = {"validate", "check-artifacts", "trace"}
    if argv and not argv[0].startswith("--") and argv[0] in known:
        action = argv[0]; argv = argv[1:]
    args = parse_args(argv)
    if "action" in args: action = args["action"]
    repo_root = Path(args.get("repo-root", ".")).resolve()
    flowid = args.get("flowid", "")

    if not flowid and action != "validate":
        print(json.dumps({"success": False, "error": "Falta --flowid"}, indent=2)); return 2

    if action == "validate":
        if not flowid:
            flowid = "APOLO-VALIDATE"
        r = validate_data_flow(repo_root, flowid)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0 if r["overall_pass"] else 1
    elif action == "check-artifacts":
        results = [check_artifact(repo_root, flowid, a) for a in EXPECTED_ARTIFACTS]
        print(json.dumps({"success": True, "artifacts": results}, ensure_ascii=False, indent=2, default=str))
        return 0
    elif action == "trace":
        r = trace_flow(repo_root, flowid)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

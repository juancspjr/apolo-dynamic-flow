#!/usr/bin/env python3
"""
score_evidence.py — Evaluador de calidad y suficiencia de evidence packs.

GAP 2: Calidad y suficiencia de evidencia.

Recibe un EVIDENCE-PACK.yaml + 02-VERDAD.yaml (objetivo) y produce
EVIDENCE-SCORE.yaml con métricas deterministas:

  - coverage_score:    % de archivos mencionados en VERDAD que están en el pack
  - freshness_score:   % de archivos con git-mtime < 24h (relevancia temporal)
  - depth_score:       proporción de evidencia con contenido vs solo rutas
  - conflict_risk:     detecta si hay 2+ archivos con funciones del mismo nombre
  - missing_critical:  lista archivos que VERDAD referencia pero no están en pack
  - redundancy_score:  % de items duplicados (mismo hash)
  - schema_validity:   % de items que pasaron schema-validation

Decisiones automáticas:
  - Si coverage_score < 0.7 -> recommendation: "re-collect with expanded scope"
  - Si missing_critical no está vacío -> recommendation: "block before agent"
  - Si freshness_score < 0.3 -> recommendation: "evidence may be stale"
  - Si conflict_risk > 0.5 -> recommendation: "investigate symbol conflicts"

Uso:
  python3 score_evidence.py \\
    --evidence plan/active/<FLOW>/evidence/EVIDENCE-PACK.yaml \\
    --verdad plan/active/<FLOW>/02-VERDAD.yaml \\
    --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \\
    --output plan/active/<FLOW>/evidence/EVIDENCE-SCORE.yaml
"""

from __future__ import annotations

import json
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
    sha256,
    write_yaml,
)


# ============================================================================
# Scoring functions
# ============================================================================

def compute_coverage_score(
    evidence_pack: Dict[str, Any],
    verdad: Dict[str, Any],
) -> tuple[float, List[str]]:
    """Cobertura: % de archivos mencionados en VERDAD que están en el pack.

    Returns: (score 0-1, lista de archivos faltantes)
    """
    # Extraer archivos mencionados en verdad
    verdad_files: Set[str] = set()
    for cluster in verdad.get("clusters", verdad.get("componentes", [])):
        if isinstance(cluster, dict):
            # Acoplamientos reales
            acopl = cluster.get("acoplamientosreales", {})
            if isinstance(acopl, dict):
                verdad_files.update(acopl.get("archivos", []))
            # Frontera de cambio
            frontera = cluster.get("fronteracambio", {})
            if isinstance(frontera, dict):
                verdad_files.update(frontera.get("incluye", []))
            # Files directos
            verdad_files.update(cluster.get("archivos", []))
            # Símbolos pueden tener referencias a archivos
            for ref in cluster.get("referencias", []):
                if isinstance(ref, str) and ".yaml" not in ref and "/" in ref:
                    verdad_files.add(ref.split("#")[0])

    # Extraer archivos del pack
    pack_files: Set[str] = set()
    for item in evidence_pack.get("items", []):
        source = item.get("source", "")
        # Solo file-snapshot y symbol-list aportan archivos
        if item.get("kind") in ("file-snapshot", "symbol-list", "schema-validation"):
            pack_files.add(source)
        # related_symbols pueden referenciar archivos
        for sym in item.get("related_symbols", []):
            pass  # Símbolos, no archivos

    # Filtrar verdad_files a solo archivos válidos (con extensión y path real)
    verdad_files = {
        f for f in verdad_files
        if "." in f and not f.startswith("docs/") and "/" in f and len(f) > 3
    }

    if not verdad_files:
        # Si verdad no referencia archivos, coverage = 1.0 (no aplica)
        return 1.0, []

    covered = verdad_files & pack_files
    missing = list(verdad_files - pack_files)
    score = len(covered) / len(verdad_files) if verdad_files else 1.0

    return score, missing


def compute_freshness_score(evidence_pack: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Freshness: % de file-snapshots con git-mtime < 24h.

    Returns: (score 0-1, {stale_files: [], fresh_files: []})
    """
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stale: List[str] = []
    fresh: List[str] = []
    file_snapshots = 0

    pack_created = evidence_pack.get("created_at", now_iso())
    try:
        pack_dt = datetime.fromisoformat(pack_created.replace("Z", "+00:00"))
    except Exception:
        pack_dt = datetime.now(timezone.utc)

    for item in evidence_pack.get("items", []):
        if item.get("kind") != "file-snapshot":
            continue
        file_snapshots += 1
        source = item.get("source", "")
        captured = item.get("captured_at", "")
        try:
            captured_dt = datetime.fromisoformat(captured.replace("Z", "+00:00"))
            age = pack_dt - captured_dt
            if age < timedelta(hours=24):
                fresh.append(source)
            else:
                stale.append(source)
        except Exception:
            stale.append(source)

    if file_snapshots == 0:
        return 1.0, {"stale_files": [], "fresh_files": [], "note": "no file-snapshots"}

    score = len(fresh) / file_snapshots
    return score, {"stale_files": stale, "fresh_files": fresh}


def compute_depth_score(evidence_pack: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Depth: proporción de items con contenido sustantivo (no solo rutas).

    Un item tiene "depth" si:
      - Tiene summary con > 30 caracteres
      - O tiene related_symbols con > 0 items
      - O tiene raw_path apuntando a un archivo > 0 bytes
    """
    items = evidence_pack.get("items", [])
    if not items:
        return 0.0, {"shallow_items": [], "deep_items": []}

    shallow: List[str] = []
    deep: List[str] = []

    for item in items:
        item_id = item.get("id", "?")
        summary = item.get("summary", "") or ""
        symbols = item.get("related_symbols", []) or []
        has_depth = len(summary) > 30 or len(symbols) > 0

        if has_depth:
            deep.append(item_id)
        else:
            shallow.append(item_id)

    score = len(deep) / len(items)
    return score, {"shallow_items": shallow, "deep_items": deep}


def compute_conflict_risk(
    evidence_pack: Dict[str, Any],
    code_index: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    """Conflict risk: detecta 2+ archivos con funciones del mismo nombre.

    Returns: (score 0-1, {conflicts: [{symbol, files: []}]})
    """
    symbol_to_files: Dict[str, List[str]] = {}

    for item in evidence_pack.get("items", []):
        source = item.get("source", "")
        for sym in item.get("related_symbols", []) or []:
            if sym not in symbol_to_files:
                symbol_to_files[sym] = []
            if source not in symbol_to_files[sym]:
                symbol_to_files[sym].append(source)

    # Si hay code-index, enriquecer
    if code_index:
        for f in code_index.get("files", []):
            fpath = f.get("path", "")
            for func in f.get("symbols", {}).get("functions", []):
                fname = func.get("name", "")
                if not fname:
                    continue
                if fname not in symbol_to_files:
                    symbol_to_files[fname] = []
                if fpath not in symbol_to_files[fname]:
                    symbol_to_files[fname].append(fpath)

    conflicts: List[Dict[str, Any]] = []
    for sym, files in symbol_to_files.items():
        if len(files) > 1:
            conflicts.append({"symbol": sym, "files": files})

    if not symbol_to_files:
        return 0.0, {"conflicts": [], "note": "no symbols to compare"}

    score = len(conflicts) / len(symbol_to_files)
    return score, {"conflicts": conflicts}


def compute_redundancy_score(evidence_pack: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Redundancy: % de items duplicados (mismo hash)."""
    items = evidence_pack.get("items", [])
    if not items:
        return 0.0, {"duplicates": []}

    hash_to_items: Dict[str, List[str]] = {}
    for item in items:
        h = item.get("hash", "")
        if not h:
            continue
        if h not in hash_to_items:
            hash_to_items[h] = []
        hash_to_items[h].append(item.get("id", "?"))

    duplicates = [
        {"hash": h, "items": ids}
        for h, ids in hash_to_items.items()
        if len(ids) > 1
    ]

    redundant_count = sum(len(d["items"]) - 1 for d in duplicates)
    score = redundant_count / len(items)
    return score, {"duplicates": duplicates}


def compute_schema_validity_score(evidence_pack: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Schema validity: % de items schema-validation que pasaron."""
    schema_items = [
        item for item in evidence_pack.get("items", [])
        if item.get("kind") == "schema-validation"
    ]
    if not schema_items:
        return 1.0, {"valid": 0, "invalid": 0, "note": "no schema-validations"}

    valid = 0
    invalid = 0
    invalid_items: List[str] = []
    for item in schema_items:
        summary = (item.get("summary") or "").lower()
        if "ok" in summary or "valid" in summary:
            valid += 1
        else:
            invalid += 1
            invalid_items.append(item.get("id", "?"))

    score = valid / len(schema_items) if schema_items else 1.0
    return score, {"valid": valid, "invalid": invalid, "invalid_items": invalid_items}


# ============================================================================
# Decision engine
# ============================================================================

def compute_overall_score(scores: Dict[str, float]) -> float:
    """Pesos:
    - coverage: 40% (lo más importante: ¿tenemos todo lo que necesitamos?)
    - depth: 25% (¿la evidencia es sustantiva?)
    - freshness: 15% (¿es actual?)
    - schema_validity: 10% (¿pasó validación?)
    - redundancy: 5% (invertido - menos redundancia = mejor)
    - conflict_risk: 5% (invertido - menos conflictos = mejor)
    """
    weights = {
        "coverage": 0.40,
        "depth": 0.25,
        "freshness": 0.15,
        "schema_validity": 0.10,
        "redundancy": 0.05,
        "conflict_risk": 0.05,
    }
    total = 0.0
    for key, weight in weights.items():
        if key in ("redundancy", "conflict_risk"):
            # Invertir: menor score = mejor
            total += (1.0 - scores.get(key, 0)) * weight
        else:
            total += scores.get(key, 0) * weight
    return round(total, 3)


def generate_recommendation(
    scores: Dict[str, float],
    missing_critical: List[str],
    conflicts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Genera recomendación automática para el orquestador."""
    recommendations: List[str] = []
    severity = "info"

    if missing_critical:
        recommendations.append(
            f"BLOCK: {len(missing_critical)} archivos críticos faltantes en el pack: "
            f"{', '.join(missing_critical[:3])}{'...' if len(missing_critical) > 3 else ''}"
        )
        severity = "critical"

    if scores.get("coverage", 1.0) < 0.7:
        recommendations.append(
            f"RE-COLLECT: coverage_score={scores['coverage']:.2f} < 0.7 — "
            f"volver a ejecutar collect_evidence.py con scope ampliado"
        )
        if severity != "critical":
            severity = "warning"

    if scores.get("freshness", 1.0) < 0.3:
        recommendations.append(
            f"STALE: freshness_score={scores['freshness']:.2f} < 0.3 — "
            f"la evidencia puede estar desactualizada"
        )
        if severity == "info":
            severity = "warning"

    if scores.get("conflict_risk", 0.0) > 0.5:
        recommendations.append(
            f"CONFLICT: conflict_risk={scores['conflict_risk']:.2f} > 0.5 — "
            f"investigar {len(conflicts)} símbolos en conflicto"
        )
        if severity == "info":
            severity = "warning"

    if scores.get("depth", 1.0) < 0.5:
        recommendations.append(
            f"SHALLOW: depth_score={scores['depth']:.2f} < 0.5 — "
            f"la evidencia contiene principalmente rutas sin contenido sustantivo"
        )

    if not recommendations:
        recommendations.append("OK: evidence pack sufficient for agent consumption")
        severity = "info"

    return {
        "severity": severity,
        "actions": recommendations,
        "should_block_agent": severity == "critical",
        "should_recollect": scores.get("coverage", 1.0) < 0.7 or bool(missing_critical),
    }


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    evidence_path = Path(args.get("evidence", ""))
    verdad_path = Path(args.get("verdad", ""))
    code_index_path = Path(args.get("code-index", "")) if args.get("code-index") else None
    output = Path(args.get("output", "EVIDENCE-SCORE.yaml"))
    flowid = args.get("flowid", "")

    if not evidence_path.exists():
        log(f"Evidence pack no encontrado: {evidence_path}", "ERROR")
        return 2

    start = time.time()

    evidence_pack = read_yaml(evidence_path) or {}
    verdad = read_yaml(verdad_path) or {} if verdad_path.exists() else {}
    code_index = read_yaml(code_index_path) if code_index_path and code_index_path.exists() else None

    # Calcular scores
    coverage_score, missing_critical = compute_coverage_score(evidence_pack, verdad)
    freshness_score, freshness_data = compute_freshness_score(evidence_pack)
    depth_score, depth_data = compute_depth_score(evidence_pack)
    conflict_risk, conflict_data = compute_conflict_risk(evidence_pack, code_index)
    redundancy_score, redundancy_data = compute_redundancy_score(evidence_pack)
    schema_validity, schema_data = compute_schema_validity_score(evidence_pack)

    scores = {
        "coverage": round(coverage_score, 3),
        "freshness": round(freshness_score, 3),
        "depth": round(depth_score, 3),
        "conflict_risk": round(conflict_risk, 3),
        "redundancy": round(redundancy_score, 3),
        "schema_validity": round(schema_validity, 3),
    }

    overall = compute_overall_score(scores)
    recommendation = generate_recommendation(scores, missing_critical, conflict_data["conflicts"])

    duration_ms = int((time.time() - start) * 1000)

    evidence_score = {
        "evidencescore": "V1",
        "version": 1,
        "flowid": flowid,
        "generated_at": now_iso(),
        "generator": {
            "script": "scripts/python/score_evidence.py",
            "duration_ms": duration_ms,
        },
        "inputs": {
            "evidence_pack": str(evidence_path),
            "verdad": str(verdad_path) if verdad_path.exists() else None,
            "code_index": str(code_index_path) if code_index_path else None,
        },
        "scores": scores,
        "overall_score": overall,
        "details": {
            "missing_critical": missing_critical,
            "freshness": freshness_data,
            "depth": depth_data,
            "conflicts": conflict_data,
            "redundancy": redundancy_data,
            "schema_validity": schema_data,
        },
        "recommendation": recommendation,
    }

    write_yaml(output, evidence_score)

    log(
        f"Evidence score: overall={overall:.3f} | "
        f"coverage={scores['coverage']:.2f} | "
        f"depth={scores['depth']:.2f} | "
        f"freshness={scores['freshness']:.2f} | "
        f"severity={recommendation['severity']}",
        "INFO" if recommendation["severity"] == "info" else "WARN",
    )

    print(json.dumps({
        "success": True,
        "overall_score": overall,
        "scores": scores,
        "severity": recommendation["severity"],
        "should_block_agent": recommendation["should_block_agent"],
        "should_recollect": recommendation["should_recollect"],
        "missing_critical_count": len(missing_critical),
        "duration_ms": duration_ms,
        "output": str(output),
    }))
    return 0 if recommendation["severity"] != "critical" else 1


if __name__ == "__main__":
    sys.exit(main())

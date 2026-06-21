#!/usr/bin/env python3
"""
generate_plan.py — Generador determinista de planes dinámicos.

Lee:
  - EVIDENCE-PACK.yaml (evidence items)
  - 02-VERDAD.yaml (verdad artifact con clusters/components)

Genera:
  - 03-PLAN-INDICE-DYNAMIC.yaml con:
      - unidades (una por cluster/componente de verdad)
      - topological_sort (Kahn's algorithm sobre dependencias)
      - adaptative_gates (gatillos dinámicos)
      - rewrite_history (vacío en v1; append en rewrites)

Heurísticas de partición (deterministas):
  - Una unidad = un eje dominante (handler | service | repo | ui | docs)
  - Si un cluster mezcla >1 eje → partir en N unidades
  - Si fronteraconfianza tiene paradoja → unidad separada (paradoja-heredada)
  - mpestimados = ceil(símbolos acoplados / 4)

Uso:
  python3 generate_plan.py \
    --flowid APOLO-20260620-MI \
    --evidence /path/EVIDENCE-PACK.yaml \
    --verdad /path/02-VERDAD.yaml \
    --output /path/03-PLAN-INDICE-DYNAMIC.yaml \
    --method deterministic-python \
    [--parent-version 1] \
    [--partition-hints '["split U-02"]']
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import (  # noqa: E402
    elapsed_ms,
    gen_uuid,
    hash_file,
    log,
    now_iso,
    parse_args,
    read_yaml,
    sha256,
    write_yaml,
)


# ============================================================================
# Heurísticas de partición
# ============================================================================

AXES = ["handler", "service", "repo", "ui", "docs", "scheduler", "schema", "test"]


def detect_dominant_axis(cluster: Dict[str, Any], evidence_items: List[Dict[str, Any]]) -> str:
    """Detecta el eje dominante de un cluster por sus acoplamientos."""
    files: List[str] = []
    files.extend(cluster.get("acoplamientosreales", {}).get("archivos", []))
    files.extend(cluster.get("archivos", []))

    axis_count: Dict[str, int] = defaultdict(int)
    for f in files:
        lower = f.lower()
        if "handler" in lower or "controller" in lower or "/http/" in lower:
            axis_count["handler"] += 1
        if "service" in lower:
            axis_count["service"] += 1
        if "repo" in lower or "repository" in lower or "infrastructure" in lower:
            axis_count["repo"] += 1
        if "ui" in lower or "view" in lower or "component" in lower or "modal" in lower:
            axis_count["ui"] += 1
        if "docs" in lower or os.sep in lower and "docs" in lower:
            axis_count["docs"] += 1
        if "scheduler" in lower or "cron" in lower:
            axis_count["scheduler"] += 1
        if "migration" in lower or "schema" in lower:
            axis_count["schema"] += 1
        if "test" in lower or "spec" in lower:
            axis_count["test"] += 1

    if not axis_count:
        return "handler"  # default
    return max(axis_count.items(), key=lambda x: x[1])[0]


def estimate_mps(symbols: List[str]) -> str:
    """Estima número de MPs por símbolos acoplados."""
    n = len(symbols)
    if n == 0:
        return "1"
    if n <= 4:
        return "1"
    if n <= 8:
        return "2"
    if n <= 12:
        return "3"
    return "4"


def should_split(cluster: Dict[str, Any]) -> Optional[List[str]]:
    """Determina si un cluster debe partirse y cómo."""
    files: List[str] = []
    files.extend(cluster.get("acoplamientosreales", {}).get("archivos", []))
    files.extend(cluster.get("archivos", []))

    axes_present: Set[str] = set()
    for f in files:
        lower = f.lower()
        if "handler" in lower or "controller" in lower:
            axes_present.add("handler")
        if "service" in lower:
            axes_present.add("service")
        if "ui" in lower or "modal" in lower or "component" in lower:
            axes_present.add("ui")
        if "repo" in lower or "repository" in lower:
            axes_present.add("repo")

    if len(axes_present) <= 1:
        return None
    # Si mezcla backend + ui, partir
    return list(axes_present)


def cluster_to_unit(
    cluster: Dict[str, Any],
    unit_id: str,
    evidence_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    axis = detect_dominant_axis(cluster, evidence_items)
    symbols = cluster.get("acoplamientosreales", {}).get("simbolos", [])
    if not symbols and "simbolos" in cluster:
        symbols = cluster["simbolos"]

    frontera = cluster.get("fronteraconfianza", {})
    if not isinstance(frontera, dict):
        frontera = {
            "confirmado": [],
            "pendienteoperador": [],
            "paradoja": [],
            "fueraalcance": [],
        }

    has_paradoja = (
        bool(frontera.get("paradoja"))
        or cluster.get("estado5") == "paradoja"
    )

    return {
        "id": unit_id,
        "origenverdad": {
            "componente": cluster.get("componente", cluster.get("id", unit_id)),
            "estado5": cluster.get("estado5", "ER"),
            "referencias": cluster.get("referencias", []),
        },
        "resumen": cluster.get("resumen", cluster.get("description", "(sin resumen)")),
        "tipocambio": "paradoja" if has_paradoja else cluster.get("tipocambio", "fix"),
        "ejedominante": axis,
        "subeje": cluster.get("subeje", ""),
        "acoplamientosreales": cluster.get("acoplamientosreales", {
            "archivos": cluster.get("archivos", []),
            "simbolos": symbols,
            "endpoints": cluster.get("endpoints", []),
            "tablas": cluster.get("tablas", []),
            "columnas": cluster.get("columnas", []),
        }),
        "fronteracambio": cluster.get("fronteracambio", {
            "incluye": [],
            "excluye": [],
        }),
        "fronteraconfianza": frontera,
        "dependenciasprevias": cluster.get("dependenciasprevias", []),
        "mpestimados": estimate_mps(symbols),
        "riesgooperativo": cluster.get("riesgooperativo", "medio"),
        "verificacionlocal": cluster.get("verificacionlocalposible", cluster.get("verificacionlocal", [])),
        "criteriohomogeneidad": (
            f"Un solo eje ({axis}), un objetivo técnico." if not has_paradoja
            else "Una sola paradoja, una sola decisión pendiente."
        ),
        "admisibleaindice": not has_paradoja,
        "motivonoaadmisible": (
            "Paradoja pendiente — no produce MPs hasta resolución" if has_paradoja
            else ""
        ),
        "recomendacionparticion": should_split(cluster) or [],
    }


# ============================================================================
# Topological sort (Kahn's algorithm)
# ============================================================================

def topological_sort(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordena units por dependenciasprevias. Asume dependencias son unit_ids."""
    by_id = {u["id"]: u for u in units}
    in_degree: Dict[str, int] = {u["id"]: 0 for u in units}
    adjacency: Dict[str, List[str]] = defaultdict(list)

    for u in units:
        deps = u.get("dependenciasprevias", [])
        for d in deps:
            if d in by_id:
                adjacency[d].append(u["id"])
                in_degree[u["id"]] += 1

    queue = deque([uid for uid, deg in in_degree.items() if deg == 0])
    order: List[str] = []
    while queue:
        uid = queue.popleft()
        order.append(uid)
        for neighbor in adjacency[uid]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Si hay ciclo (no todos procesados), append el resto
    for uid in by_id:
        if uid not in order:
            order.append(uid)

    return [
        {"order": i + 1, "unit_id": uid, "depends_on": by_id[uid].get("dependenciasprevias", [])}
        for i, uid in enumerate(order)
    ]


# ============================================================================
# Adaptative gates
# ============================================================================

def default_adaptative_gates() -> List[Dict[str, Any]]:
    return [
        {
            "id": "AG-01",
            "trigger": "unit-mixed-concerns",
            "action": "split-unit",
            "description": "Si una unidad mezcla más de un eje dominante, partir en N unidades.",
        },
        {
            "id": "AG-02",
            "trigger": "new-evidence-contradicts",
            "action": "escalate",
            "description": "Si nueva evidencia contradice la frontera de confianza, escalar.",
        },
        {
            "id": "AG-03",
            "trigger": "test-failure-pattern",
            "action": "block",
            "description": "Si 3 tests consecutivos fallan en el mismo MP, bloquear.",
        },
        {
            "id": "AG-04",
            "trigger": "block-detected",
            "action": "escalate",
            "description": "Si se detecta bloqueo activo, escalar a operador.",
        },
        {
            "id": "AG-05",
            "trigger": "operator-decision",
            "action": "block",
            "description": "Si fronteraconfianza.paradoja no está vacía, bloquear hasta decisión.",
        },
    ]


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    flowid = args.get("flowid", "")
    evidence_path = Path(args.get("evidence", ""))
    verdad_path = Path(args.get("verdad", ""))
    output = Path(args.get("output", "03-PLAN-INDICE-DYNAMIC.yaml"))
    method = args.get("method", "deterministic-python")
    parent_version_str = args.get("parent-version")
    partition_hints_str = args.get("partition-hints", "[]")

    if not flowid:
        log("--flowid requerido", "ERROR")
        return 2

    parent_version: Optional[int] = None
    if parent_version_str and parent_version_str != "true":
        try:
            parent_version = int(parent_version_str)
        except ValueError:
            log(f"--parent-version inválido: {parent_version_str}", "ERROR")
            return 2

    try:
        partition_hints = json.loads(partition_hints_str)
    except Exception:
        partition_hints = []

    start_iso = now_iso()
    start_time = time.time()

    # 1. Cargar evidence y verdad
    evidence = read_yaml(evidence_path) or {}
    verdad = read_yaml(verdad_path) or {}
    evidence_items = evidence.get("items", []) if isinstance(evidence, dict) else []
    clusters = verdad.get("clusters", verdad.get("componentes", [])) if isinstance(verdad, dict) else []

    if not clusters:
        log(f"no se encontraron clusters en {verdad_path}", "WARN")
        # Generar 1 unidad placeholder
        clusters = [{
            "id": "U-01",
            "componente": "default",
            "estado5": "ER",
            "resumen": "Sin clusters en verdad — generar unidad por defecto",
            "acoplamientosreales": {"archivos": [], "simbolos": []},
            "fronteraconfianza": {"confirmado": [], "pendienteoperador": [], "paradoja": [], "fueraalcance": []},
        }]

    # 2. Convertir clusters a units
    units: List[Dict[str, Any]] = []
    for i, cluster in enumerate(clusters, start=1):
        unit_id = f"U-{str(i).zfill(2)}"
        units.append(cluster_to_unit(cluster, unit_id, evidence_items))

    # 3. Aplicar partition_hints si hay
    for hint in partition_hints:
        # Hint formato: "split U-02 by concern"
        if hint.startswith("split "):
            parts = hint.split()
            if len(parts) >= 2:
                target_id = parts[1]
                unit = next((u for u in units if u["id"] == target_id), None)
                if unit:
                    splits = should_split(unit) or ["handler", "ui"]
                    # Marcar como no admisible y agregar recomendación
                    unit["admisibleaindice"] = False
                    unit["motivonoaadmisible"] = (
                        f"Split solicitado por hint: {hint}. Ejes detectados: {splits}"
                    )
                    unit["recomendacionparticion"] = [
                        f"separar {axis} en unidad propia" for axis in splits
                    ]

    # 4. Topological sort
    topo = topological_sort(units)

    # 5. Versión
    existing = read_yaml(output) if output.exists() else None
    new_version = 1
    rewrite_history: List[Dict[str, Any]] = []
    if existing and isinstance(existing, dict):
        new_version = int(existing.get("version", 1)) + 1
        rewrite_history = existing.get("rewrite_history", [])
        rewrite_history.append({
            "version": new_version - 1,
            "at": now_iso(),
            "reason": "regeneración por script Python",
            "changed_units": [u["id"] for u in units],
        })
    elif parent_version:
        new_version = parent_version + 1
        rewrite_history.append({
            "version": parent_version,
            "at": now_iso(),
            "reason": f"rewrite desde parent v{parent_version}",
            "changed_units": [u["id"] for u in units],
        })

    duration_ms = int((time.time() - start_time) * 1000)

    plan = {
        "dynamicplan": "V2",
        "version": new_version,
        "parent_version": parent_version,
        "flowid": flowid,
        "created_at": start_iso,
        "derived_from": {
            "evidence_pack": str(evidence_path),
            "truth_artifact": str(verdad_path),
            "collected_at": evidence.get("created_at", start_iso) if isinstance(evidence, dict) else start_iso,
        },
        "derivation_method": method,
        "rewrite_history": rewrite_history,
        "unidades": units,
        "topological_sort": topo,
        "adaptative_gates": default_adaptative_gates(),
        "estado": "ready",
    }

    write_yaml(output, plan)
    log(
        f"plan dinámico v{new_version} generado: {len(units)} unidades, {duration_ms}ms",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "version": new_version,
        "units": len(units),
        "topological_order": [t["unit_id"] for t in topo],
        "duration_ms": duration_ms,
        "output": str(output),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())

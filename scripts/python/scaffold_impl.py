#!/usr/bin/env python3
"""
scaffold_impl.py — Generador de andamios de implementación.

GAP 4: Apoyo activo a la implementación.

Para un MP específico del DYNAMIC-PLAN.yaml, genera IMPL-SCAFFOLD.yaml con:

  - Lista exacta de archivos a tocar (del CODE-INDEX, no inferida)
  - Firmas de funciones que debe mantener (para no romper contratos)
  - Tests existentes que debe seguir pasando
  - Template de estructura del cambio según patrones del repo
  - Checkpoints intermedios: "después de X, corre tests antes de continuar Y"
  - Dependencias circulares a evitar
  - Sugerencia de orden de edición (archivos sin dependencias primero)

El agente implementa con un andamio, no en el vacío.

Uso:
  python3 scaffold_impl.py \\
    --plan plan/active/<FLOW>/03-PLAN-INDICE-DYNAMIC.yaml \\
    --unit-id U-01 \\
    --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \\
    --impact-prediction plan/active/<FLOW>/IMPACT-PREDICTION.yaml \\
    --output plan/active/<FLOW>/IMPL-SCAFFOLD-U01.yaml \\
    [--flowid APOLO-...]
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
    write_yaml,
)


# ============================================================================
# Scaffold builders
# ============================================================================

def build_files_to_touch(
    unidad: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Lista exacta de archivos a tocar, enriquecida con metadata del CODE-INDEX."""
    acopl = unidad.get("acoplamientosreales", {}) or {}
    file_paths = acopl.get("archivos", []) or []

    if not code_index:
        return [{"path": p, "exists_in_index": False} for p in file_paths]

    files_index = {f["path"]: f for f in code_index.get("files", [])}

    enriched: List[Dict[str, Any]] = []
    for p in file_paths:
        if p in files_index:
            f = files_index[p]
            enriched.append({
                "path": p,
                "exists_in_index": True,
                "language": f.get("language"),
                "size_bytes": f.get("size_bytes"),
                "git_last_modified": f.get("git_last_modified"),
                "summary": f.get("summary"),
                "exported_functions": [
                    fn["name"] for fn in f.get("symbols", {}).get("functions", [])
                    if fn.get("is_exported")
                ][:10],
                "exported_classes": [
                    c["name"] for c in f.get("symbols", {}).get("classes", [])
                    if c.get("is_exported")
                ][:5],
            })
        else:
            # Buscar por stem
            stem = Path(p).stem
            found = None
            for fpath, fdata in files_index.items():
                if Path(fpath).stem == stem:
                    found = fdata
                    break
            if found:
                enriched.append({
                    "path": p,
                    "exists_in_index": True,
                    "matched_by_stem": True,
                    "language": found.get("language"),
                    "summary": found.get("summary"),
                    "exported_functions": [
                        fn["name"] for fn in found.get("symbols", {}).get("functions", [])
                        if fn.get("is_exported")
                    ][:10],
                })
            else:
                enriched.append({
                    "path": p,
                    "exists_in_index": False,
                    "note": "archivo no indexado, crear nuevo",
                })

    return enriched


def build_function_contracts(
    unidad: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Firmas de funciones que el agente debe mantener para no romper callers."""
    if not code_index:
        return []

    acopl = unidad.get("acoplamientosreales", {}) or {}
    mp_symbols = acopl.get("simbolos", []) or []
    mp_files = acopl.get("archivos", []) or []

    files_index = {f["path"]: f for f in code_index.get("files", [])}

    contracts: List[Dict[str, Any]] = []
    for f_path in mp_files:
        # Buscar archivo en índice
        f_data = files_index.get(f_path)
        if not f_data:
            # Por stem
            stem = Path(f_path).stem
            for fp, fd in files_index.items():
                if Path(fp).stem == stem:
                    f_data = fd
                    break

        if not f_data:
            continue

        # Para cada símbolo del MP, buscar su firma actual
        for sym in mp_symbols:
            for func in f_data.get("symbols", {}).get("functions", []):
                if func.get("name") == sym:
                    contracts.append({
                        "file": f_path,
                        "function": sym,
                        "current_args": func.get("args", []),
                        "is_async": func.get("is_async", False),
                        "is_exported": func.get("is_exported", False),
                        "line": func.get("line"),
                        "docstring": func.get("docstring"),
                        "contract_to_preserve": (
                            f"Mantener firma: {'async ' if func.get('is_async') else ''}"
                            f"{sym}({', '.join(func.get('args', []))})"
                        ),
                    })
            for cls in f_data.get("symbols", {}).get("classes", []):
                if cls.get("name") == sym:
                    contracts.append({
                        "file": f_path,
                        "class": sym,
                        "current_bases": cls.get("bases", []),
                        "current_methods": [m["name"] for m in cls.get("methods", [])],
                        "contract_to_preserve": (
                            f"Mantener clase {sym} con métodos públicos: "
                            f"{', '.join(m['name'] for m in cls.get('methods', []) if not m['name'].startswith('_'))}"
                        ),
                    })

    return contracts


def build_existing_tests(
    unidad: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
    test_runs_dir: Optional[Path],
) -> Dict[str, Any]:
    """Tests existentes que deben seguir pasando tras la implementación."""
    acopl = unidad.get("acoplamientosreales", {}) or {}
    mp_files = acopl.get("archivos", []) or []

    # Inferir tests por convención
    inferred: Dict[str, List[str]] = {}
    if code_index:
        all_files = [f["path"] for f in code_index.get("files", [])]
        for f in mp_files:
            stem = Path(f).stem
            tests_for_f = []
            for af in all_files:
                af_lower = af.lower()
                if ("test" in af_lower or "spec" in af_lower) and stem in af_lower and af != f:
                    tests_for_f.append(af)
            if tests_for_f:
                inferred[f] = tests_for_f

    # Tests que históricamente han corrido sobre estos archivos
    historical: List[Dict[str, Any]] = []
    if test_runs_dir and test_runs_dir.exists():
        for test_run_file in test_runs_dir.glob("*.yaml"):
            test_run = read_yaml(test_run_file) or {}
            scope = test_run.get("scope", {}) or {}
            targets = scope.get("targets", []) or []
            mp_stems = {Path(f).stem for f in mp_files}
            target_stems = {Path(t).stem for t in targets if isinstance(t, str)}
            if target_stems & mp_stems:
                historical.append({
                    "run_file": test_run_file.name,
                    "trigger": test_run.get("trigger"),
                    "summary": test_run.get("summary"),
                    "exit_code": test_run.get("exit_code"),
                    "tested_targets": targets,
                })

    return {
        "inferred_test_files": inferred,
        "historical_runs": historical[:10],
        "must_keep_passing": list(set().union(*[set(v) for v in inferred.values()])) if inferred else [],
    }


def build_edit_order(
    unidad: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Sugiere orden de edición: archivos sin dependencias primero."""
    acopl = unidad.get("acoplamientosreales", {}) or {}
    mp_files = acopl.get("archivos", []) or []

    if not code_index or not mp_files:
        return [{"order": i + 1, "file": f, "reason": "no dependency info"} for i, f in enumerate(mp_files)]

    dep_graph = code_index.get("dependency_graph", {})
    mp_set = set(mp_files)

    # Para cada archivo del MP, contar cuántos otros archivos del MP dependen de él
    in_mp_dependents: Dict[str, int] = {f: 0 for f in mp_files}
    for f in mp_files:
        # Buscar dependencias reales (por stem si path no coincide)
        f_deps = dep_graph.get(f, [])
        if not f_deps:
            stem = Path(f).stem
            for fp, deps in dep_graph.items():
                if Path(fp).stem == stem:
                    f_deps = deps
                    break
        for dep in f_deps:
            if dep in mp_set:
                in_mp_dependents[dep] = in_mp_dependents.get(dep, 0) + 1

    # Ordenar: más dependientes primero (para que si rompe, rompa temprano)
    sorted_files = sorted(mp_files, key=lambda f: -in_mp_dependents.get(f, 0))

    order: List[Dict[str, Any]] = []
    for i, f in enumerate(sorted_files):
        order.append({
            "order": i + 1,
            "file": f,
            "dependents_in_mp": in_mp_dependents.get(f, 0),
            "reason": (
                "foundational - others depend on it" if in_mp_dependents.get(f, 0) > 0
                else "leaf - no other MP files depend on it"
            ),
        })

    return order


def build_checkpoints(
    unidad: Dict[str, Any],
    edit_order: List[Dict[str, Any]],
    impact_prediction: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Genera checkpoints intermedios: 'después de X, corre tests antes de continuar Y'."""
    checkpoints: List[Dict[str, Any]] = []
    mp_id = unidad.get("id", "?")

    # Checkpoint 1: antes de empezar
    checkpoints.append({
        "id": f"CP-{mp_id}-1",
        "when": "before-start",
        "action": "verify-clean-git",
        "command": "git status --porcelain",
        "expected": "empty output (clean working tree)",
    })

    # Checkpoints intermedios: después de cada archivo con dependientes
    files_with_deps = [e for e in edit_order if e["dependents_in_mp"] > 0]
    for i, f in enumerate(files_with_deps):
        checkpoints.append({
            "id": f"CP-{mp_id}-{i + 2}",
            "when": f"after-editing:{f['file']}",
            "action": "run-micro-tests",
            "command": (
                f"python3 scripts/python/run_tests.py --trigger micro-change "
                f"--kind unit --targets-json '[\"{f["file"]}\"]' --mp-id {mp_id}"
            ),
            "expected": "exit_code 0 (tests pass)",
            "reason": f"file has {f['dependents_in_mp']} dependents in MP, verify before continuing",
        })

    # Checkpoint: si impact prediction dice riesgo alto, añadir validación extra
    if impact_prediction:
        for pred in impact_prediction.get("predictions", []):
            if pred.get("mp_id") == mp_id and pred.get("overall_risk") in ("high", "critical"):
                checkpoints.append({
                    "id": f"CP-{mp_id}-risk",
                    "when": "after-implementation",
                    "action": "run-mutation-tests",
                    "command": (
                        f"python3 scripts/python/run_tests.py --trigger section-change "
                        f"--kind mutation --mp-id {mp_id}"
                    ),
                    "expected": "mutation_score > 0.7",
                    "reason": f"impact prediction: {pred.get('overall_risk')} risk",
                })
                break

    # Checkpoint final
    checkpoints.append({
        "id": f"CP-{mp_id}-final",
        "when": "after-implementation-complete",
        "action": "run-full-suite",
        "command": "python3 tests/run_all_tests.py",
        "expected": "ALL 5 TESTS PASSED",
    })

    return checkpoints


def build_circular_deps_warning(
    unidad: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detecta dependencias circulares entre los archivos del MP."""
    acopl = unidad.get("acoplamientosreales", {}) or {}
    mp_files = acopl.get("archivos", []) or []

    if not code_index:
        return []

    dep_graph = code_index.get("dependency_graph", {})
    mp_set = set(mp_files)

    # Resolver por stem si paths no coinciden
    resolved_graph: Dict[str, List[str]] = {}
    for f in mp_files:
        deps = dep_graph.get(f, [])
        if not deps:
            stem = Path(f).stem
            for fp, d in dep_graph.items():
                if Path(fp).stem == stem:
                    deps = d
                    break
        # Filtrar solo deps dentro del MP
        in_mp_deps = []
        for dep in deps:
            if dep in mp_set:
                in_mp_deps.append(dep)
            else:
                # Por stem
                dep_stem = Path(dep).stem
                for mf in mp_files:
                    if Path(mf).stem == dep_stem:
                        in_mp_deps.append(mf)
                        break
        resolved_graph[f] = list(set(in_mp_deps))

    # Detectar ciclos (DFS)
    cycles: List[Dict[str, Any]] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {f: WHITE for f in mp_files}

    def dfs(node: str, path: List[str]) -> None:
        color[node] = GRAY
        for neighbor in resolved_graph.get(node, []):
            if color.get(neighbor, WHITE) == GRAY:
                # Ciclo encontrado
                cycle_start = path.index(neighbor) if neighbor in path else 0
                cycle = path[cycle_start:] + [neighbor]
                cycles.append({
                    "files": cycle,
                    "description": " -> ".join(cycle),
                })
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor, path + [neighbor])
        color[node] = BLACK

    for f in mp_files:
        if color[f] == WHITE:
            dfs(f, [f])

    # Deduplicar ciclos
    unique_cycles: List[Dict[str, Any]] = []
    seen_signatures: Set[str] = set()
    for c in cycles:
        sig = frozenset(c["files"])
        if sig not in seen_signatures:
            seen_signatures.add(sig)
            unique_cycles.append(c)

    return unique_cycles[:5]


def build_change_template(
    unidad: Dict[str, Any],
    code_index: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Genera un template de estructura del cambio según patrones del repo."""
    tipocambio = unidad.get("tipocambio", "fix")
    mp_files = unidad.get("acoplamientosreales", {}).get("archivos", []) or []

    templates: Dict[str, Dict[str, Any]] = {
        "fix": {
            "pattern": "bug-fix",
            "structure": [
                "1. Identificar la función/method con el bug (revisar tests existentes que fallen)",
                "2. Reproducir el bug con un test que falle",
                "3. Aplicar el fix mínimo necesario",
                "4. Verificar que el test ahora pasa",
                "5. Correr tests del módulo completo",
            ],
            "anti_patterns": [
                "No refactorizar mientras se fixea",
                "No añadir funcionalidad nueva en un fix",
                "No cambiar la firma de la función",
            ],
        },
        "refactor": {
            "pattern": "safe-refactor",
            "structure": [
                "1. Verificar que tests existentes pasan antes de refactorizar",
                "2. Hacer el refactor en pasos pequeños (un archivo a la vez)",
                "3. Después de cada paso, correr tests",
                "4. No cambiar comportamiento observable",
                "5. Al final, verificar cobertura de tests no disminuyó",
            ],
            "anti_patterns": [
                "No mezclar refactor con fix o feat",
                "No cambiar interfaces públicas sin actualizar callers",
                "No eliminar código sin verificar que no se usa",
            ],
        },
        "feat": {
            "pattern": "feature-add",
            "structure": [
                "1. Escribir test que describa el comportamiento nuevo (debe fallar)",
                "2. Implementar la funcionalidad mínima que haga pasar el test",
                "3. Refactor para limpiar",
                "4. Añadir tests adicionales para edge cases",
                "5. Documentar la nueva funcionalidad",
            ],
            "anti_patterns": [
                "No implementar features no solicitadas",
                "No romper APIs existentes",
                "No añadir dependencias innecesarias",
            ],
        },
        "paradoja": {
            "pattern": "decision-needed",
            "structure": [
                "1. Documentar la paradoja con contexto completo",
                "2. Identificar las opciones de decisión",
                "3. Listar pros/contras de cada opción",
                "4. ESCALAR al operador (no implementar)",
            ],
            "anti_patterns": [
                "No implementar sin decisión del operador",
                "No asumir la decisión del operador",
            ],
        },
        "docs": {
            "pattern": "docs-only",
            "structure": [
                "1. Identificar audiencia del docs",
                "2. Escribir contenido con ejemplos concretos",
                "3. Verificar enlaces y referencias",
                "4. Spellcheck y grammar check",
            ],
            "anti_patterns": [
                "No mezclar docs con cambios de código",
            ],
        },
    }

    return templates.get(tipocambio, templates["fix"])


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    args = parse_args(sys.argv[1:])
    plan_path = Path(args.get("plan", ""))
    unit_id = args.get("unit-id", "")
    code_index_path = Path(args.get("code-index", "")) if args.get("code-index") else None
    impact_prediction_path = Path(args.get("impact-prediction", "")) if args.get("impact-prediction") else None
    test_runs_dir = Path(args.get("test-runs-dir", "")) if args.get("test-runs-dir") else None
    output = Path(args.get("output", "IMPL-SCAFFOLD.yaml"))
    flowid = args.get("flowid", "")

    if not plan_path.exists():
        log(f"Plan no encontrado: {plan_path}", "ERROR")
        return 2

    if not unit_id:
        log("--unit-id requerido (ej: U-01)", "ERROR")
        return 2

    start = time.time()

    plan = read_yaml(plan_path) or {}
    code_index = (
        read_yaml(code_index_path) if code_index_path and code_index_path.exists() else None
    )
    impact_prediction = (
        read_yaml(impact_prediction_path)
        if impact_prediction_path and impact_prediction_path.exists()
        else None
    )

    # Buscar la unidad por ID
    unidad = None
    for u in plan.get("unidades", []):
        if u.get("id") == unit_id:
            unidad = u
            break

    if not unidad:
        log(f"Unidad {unit_id} no encontrada en el plan", "ERROR")
        return 2

    # Construir andamio
    files_to_touch = build_files_to_touch(unidad, code_index)
    function_contracts = build_function_contracts(unidad, code_index)
    existing_tests = build_existing_tests(unidad, code_index, test_runs_dir)
    edit_order = build_edit_order(unidad, code_index)
    checkpoints = build_checkpoints(unidad, edit_order, impact_prediction)
    circular_deps = build_circular_deps_warning(unidad, code_index)
    change_template = build_change_template(unidad, code_index)

    duration_ms = int((time.time() - start) * 1000)

    # Veredicto
    has_circular = bool(circular_deps)
    has_unindexed = any(not f.get("exists_in_index") for f in files_to_touch)
    missing_tests = bool(existing_tests.get("must_keep_passing")) is False and len(files_to_touch) > 0

    if has_circular:
        verdict = "block-circular-deps"
        verdict_reason = f"{len(circular_deps)} dependencias circulares detectadas"
    elif has_unindexed:
        verdict = "proceed-with-caution"
        verdict_reason = "algunos archivos no están en CODE-INDEX (¿crear nuevos?)"
    elif missing_tests:
        verdict = "write-tests-first"
        verdict_reason = "no se encontraron tests existentes para los archivos del MP"
    else:
        verdict = "proceed"
        verdict_reason = "andamio generado, todos los archivos indexados, tests encontrados"

    scaffold = {
        "implscaffold": "V1",
        "version": 1,
        "flowid": flowid,
        "unit_id": unit_id,
        "generated_at": now_iso(),
        "generator": {
            "script": "scripts/python/scaffold_impl.py",
            "duration_ms": duration_ms,
        },
        "inputs": {
            "plan": str(plan_path),
            "code_index": str(code_index_path) if code_index_path else None,
            "impact_prediction": str(impact_prediction_path) if impact_prediction_path else None,
        },
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "files_to_touch": files_to_touch,
        "function_contracts": function_contracts,
        "existing_tests": existing_tests,
        "edit_order": edit_order,
        "checkpoints": checkpoints,
        "circular_dependencies": circular_deps,
        "change_template": change_template,
        "summary": {
            "total_files": len(files_to_touch),
            "total_contracts": len(function_contracts),
            "total_checkpoints": len(checkpoints),
            "has_circular_deps": has_circular,
            "tests_found": len(existing_tests.get("must_keep_passing", [])),
        },
    }

    write_yaml(output, scaffold)

    log(
        f"Scaffold for {unit_id}: {len(files_to_touch)} files, "
        f"{len(function_contracts)} contracts, {len(checkpoints)} checkpoints, "
        f"verdict={verdict}, {duration_ms}ms",
        "INFO" if verdict == "proceed" else "WARN",
    )

    print(json.dumps({
        "success": True,
        "unit_id": unit_id,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "total_files": len(files_to_touch),
        "total_contracts": len(function_contracts),
        "total_checkpoints": len(checkpoints),
        "has_circular_deps": has_circular,
        "duration_ms": duration_ms,
        "output": str(output),
    }))
    return 0 if verdict == "proceed" else 1


if __name__ == "__main__":
    sys.exit(main())

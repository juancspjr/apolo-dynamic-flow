#!/usr/bin/env python3
"""
scaffold_v3.py — Scaffold mejorado con auto-seleccion de U-NN y archivos concretos (v3.1.0).

Cierra 2 GAPs del INTEGRATION-VERDICT.md:

  GAP #5.1: "Seleccion de U-NN para scaffold_impl — el agente decide cual
             unidad implementar primero. El sistema no prioriza automaticamente
             basandose en impacto/criticidad."

  Scaffold concreto: "El YAML producido por scaffold_impl.py es abstracto
             (descripcion de la unidad, no andamio accionable). No contiene
             files_to_create, files_to_modify, ni commands."

Mejoras sobre scaffold_impl.py:

  1. AUTO-SELECT U-NN: Si no se pasa --unit-id, escoge automaticamente la
     siguiente unidad del topological_sort segun estrategia configurable:
       - topological_first (default): primera unidad sin dependencias pendientes
       - highest_impact: unidad con mas afectados en IMPACT-PREDICTION
       - lowest_risk: unidad con riesgooperativo = "bajo"

  2. FILES_TO_CREATE CONCRETOS: Ademas de files_to_touch (que pueden ser
     archivos existentes a modificar), genera files_to_create con paths
     REALES derivados del plan:
       - Tests: tests/test_<unit_id>_v3.py
       - Implementation: derivada del eje dominante
       - Scaffolds: plan/active/<flow>/scaffolds/SCAFFOLD-<unit_id>.yaml

  3. COMMANDS ACCIONABLES: Genera commands[] con comandos bash ejecutables:
       - "python3 scripts/python/run_tests.py --targets <files>"
       - "git add <files> && git commit -m 'U-NN: <resumen>'"
       - "python3 scripts/python/code_quality.py --targets <files>"

CLI:
  # Auto-select U-NN (no requiere --unit-id)
  python3 scaffold_v3.py --plan plan.yaml --code-index ci.yaml --output sf.yaml --flowid X

  # Forzar unidad especifica
  python3 scaffold_v3.py --plan plan.yaml --unit-id U-02 --code-index ci.yaml --output sf.yaml

  # Especificar estrategia
  python3 scaffold_v3.py --plan plan.yaml --strategy highest_impact --code-index ci.yaml --output sf.yaml
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from common import log, now_iso, parse_args, read_yaml, write_yaml, flow_dir


# ============================================================================
# Unit selection strategies
# ============================================================================

def select_unit_topological_first(plan: Dict) -> Optional[Dict[str, Any]]:
    """Selecciona la primera unidad del topological_sort."""
    topo = plan.get("topological_sort", []) or []
    unidades = plan.get("unidades", []) or []
    if not topo or not unidades:
        return unidades[0] if unidades else None

    # Tomar la primera entrada del topological sort
    first_entry = topo[0]
    if isinstance(first_entry, dict):
        first_id = first_entry.get("unit_id") or first_entry.get("id")
    else:
        first_id = str(first_entry)

    for u in unidades:
        if u.get("id") == first_id:
            return u
    return unidades[0]


def select_unit_highest_impact(plan: Dict, impact_prediction: Optional[Dict]) -> Optional[Dict[str, Any]]:
    """Selecciona la unidad con mas afectados en IMPACT-PREDICTION."""
    unidades = plan.get("unidades", []) or []
    if not unidades:
        return None

    if not impact_prediction:
        return select_unit_topological_first(plan)

    # Buscar la unidad con mas afectados
    predictions = impact_prediction.get("predictions", []) or []
    unit_impacts: Dict[str, int] = {}
    for pred in predictions:
        uid = pred.get("unit_id") or pred.get("unit")
        if uid:
            affected = pred.get("affected_count", 0) or pred.get("total_affected", 0) or 0
            unit_impacts[uid] = unit_impacts.get(uid, 0) + int(affected)

    if not unit_impacts:
        return select_unit_topological_first(plan)

    # Ordenar por impacto descendente
    sorted_units = sorted(unit_impacts.items(), key=lambda x: -x[1])
    best_unit_id = sorted_units[0][0]

    for u in unidades:
        if u.get("id") == best_unit_id:
            log(f"Auto-select: {best_unit_id} (impacto: {sorted_units[0][1]} afectados)", "INFO")
            return u
    return select_unit_topological_first(plan)


def select_unit_lowest_risk(plan: Dict) -> Optional[Dict[str, Any]]:
    """Selecciona la unidad con riesgooperativo mas bajo."""
    unidades = plan.get("unidades", []) or []
    if not unidades:
        return None

    risk_order = {"bajo": 0, "medio": 1, "alto": 2, "high": 2, "medium": 1, "low": 0}
    sorted_units = sorted(
        unidades,
        key=lambda u: risk_order.get(str(u.get("riesgooperativo", "medio")).lower(), 1)
    )
    return sorted_units[0]


def auto_select_unit(
    plan: Dict,
    strategy: str = "topological_first",
    impact_prediction: Optional[Dict] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Selecciona automaticamente la siguiente unidad a implementar."""
    if strategy == "topological_first":
        unit = select_unit_topological_first(plan)
        reason = "primera unidad del topological_sort"
    elif strategy == "highest_impact":
        unit = select_unit_highest_impact(plan, impact_prediction)
        reason = "unidad con mayor impacto predicho"
    elif strategy == "lowest_risk":
        unit = select_unit_lowest_risk(plan)
        reason = "unidad con menor riesgo operativo"
    else:
        log(f"Estrategia desconocida: {strategy}, usando topological_first", "WARN")
        unit = select_unit_topological_first(plan)
        reason = "estrategia fallback a topological_first"

    if not unit:
        return None, "no units in plan"

    return unit, f"auto-selected via {strategy}: {reason}"


# ============================================================================
# Concrete files_to_create generation
# ============================================================================

def generate_files_to_create(
    unidad: Dict[str, Any],
    plan: Dict,
    flowid: str,
    repo_root: Path,
) -> List[Dict[str, Any]]:
    """Genera files_to_create CONCRETOS con paths reales."""
    unit_id = unidad.get("id", "U-XX")
    files: List[Dict[str, Any]] = []

    # 1. Test file concreto
    test_path = f"tests/test_{unit_id.lower().replace('-', '_')}_v3.py"
    files.append({
        "path": test_path,
        "type": "test",
        "action": "create",
        "template": _test_template(unit_id, unidad),
        "reason": f"Test skeleton para unidad {unit_id}",
        "must_pass_before_merge": True,
    })

    # 2. Implementation file concreto (derivado del eje dominante)
    eje = unidad.get("ejedominante", "") or "handler"
    subeje = unidad.get("subeje", "") or ""
    impl_path = _derive_impl_path(unit_id, eje, subeje, plan)
    files.append({
        "path": impl_path,
        "type": "implementation",
        "action": "create_or_modify",
        "template": _impl_template(unit_id, unidad, eje),
        "reason": f"Implementacion del eje {eje}" + (f" / {subeje}" if subeje else ""),
        "must_pass_before_merge": True,
    })

    # 3. Scaffold YAML concreto (este mismo archivo)
    if flowid:
        scaffold_path = f"plan/active/{flowid}/scaffolds/SCAFFOLD-{unit_id}.yaml"
        files.append({
            "path": scaffold_path,
            "type": "scaffold_artifact",
            "action": "create",
            "template": "# Generado por scaffold_v3.py",
            "reason": f"Artefacto de scaffold para {unit_id}",
            "must_pass_before_merge": False,
        })

    # 4. Evidence snapshot concreto
    if flowid:
        evidence_path = f"plan/active/{flowid}/scaffolds/{unit_id}-EVIDENCE-BASELINE.yaml"
        files.append({
            "path": evidence_path,
            "type": "evidence_baseline",
            "action": "create",
            "template": "# Baseline capturado antes de implementar",
            "reason": f"Evidence baseline para diff visual (v3.1.0)",
            "must_pass_before_merge": False,
        })

    return files


def _derive_impl_path(unit_id: str, eje: str, subeje: str, plan: Dict) -> str:
    """Deriva el path del archivo de implementacion del eje dominante."""
    eje_lower = (eje or "handler").lower()
    # Map eje → path convencion
    eje_to_path = {
        "handler": f"plugin/handlers/{unit_id.lower()}-handler.ts",
        "router": f"plugin/routers/{unit_id.lower()}-router.ts",
        "service": f"plugin/services/{unit_id.lower()}-service.ts",
        "schema": f"schemas/{unit_id.lower()}-schema.yaml",
        "test": f"tests/test-{unit_id.lower()}.ts",
        "doc": f"docs/{unit_id.lower()}.md",
        "config": f"config/{unit_id.lower()}.yaml",
    }
    return eje_to_path.get(eje_lower, f"plugin/{unit_id.lower()}-{eje_lower}.ts")


def _test_template(unit_id: str, unidad: Dict) -> str:
    """Template de test concreto para la unidad."""
    resumen = unidad.get("resumen", "Unidad sin descripcion")[:60]
    return f'''#!/usr/bin/env python3
"""
Test automatico generado por scaffold_v3.py para {unit_id}.
Unidad: {resumen}
"""
import pytest


class Test{unit_id.replace("-", "")}:
    """Tests para {unit_id}."""

    def setup_method(self):
        """Setup antes de cada test."""
        # TODO: inicializar dependencias
        pass

    def test_basic_creation(self):
        """Test basico: el modulo debe poder importarse."""
        # TODO: implementar
        # from plugin.{unit_id.lower()} import main
        # assert main is not None
        assert True, "Skeleton test — implementar"

    def test_contract_preserved(self):
        """Test de contrato: la firma publica no debe cambiar."""
        # TODO: validar contrato
        assert True, "Skeleton test — implementar"

    def test_no_regressions(self):
        """Test de regresion: comportamiento previo se mantiene."""
        # TODO: implementar
        assert True, "Skeleton test — implementar"
'''


def _impl_template(unit_id: str, unidad: Dict, eje: str) -> str:
    """Template de implementacion concreto para la unidad."""
    resumen = unidad.get("resumen", "Implementacion")[:60]
    return f'''/**
 * {unit_id} — {resumen}
 *
 * Eje dominante: {eje}
 * Generado por scaffold_v3.py (v3.1.0)
 * NO BORRAR: los contracts estan en SCAFFOLD-{unit_id}.yaml
 */

// TODO: implementar {unit_id}
// Sugerencia: empezar por el contrato mas restrictivo y validar con tests

export interface {unit_id.replace("-", "")}Config {{
  // TODO: definir config
}}

export async function {unit_id.lower().replace("-", "_")}(config: {unit_id.replace("-", "")}Config): Promise<void> {{
  // TODO: implementar
  throw new Error("{unit_id} no implementado");
}}
'''


# ============================================================================
# Commands generation
# ============================================================================

def generate_commands(
    unidad: Dict[str, Any],
    files_to_create: List[Dict],
    files_to_modify: List[Dict],
    flowid: str,
) -> List[Dict[str, Any]]:
    """Genera commands[] accionables que el agente puede ejecutar."""
    unit_id = unidad.get("id", "U-XX")
    commands: List[Dict[str, Any]] = []

    # 1. Setup: crear estructura de directorios
    dirs_needed = set()
    for f in files_to_create + files_to_modify:
        path = f.get("path", "")
        if "/" in path:
            dirs_needed.add("/".join(path.split("/")[:-1]))

    if dirs_needed:
        commands.append({
            "id": f"CMD-{unit_id}-1",
            "phase": "setup",
            "command": f"mkdir -p {' '.join(sorted(dirs_needed))}",
            "description": "Crear estructura de directorios",
            "expected_exit_code": 0,
        })

    # 2. Create files
    for i, f in enumerate(files_to_create, 1):
        commands.append({
            "id": f"CMD-{unit_id}-{i+1}",
            "phase": "create_files",
            "command": f"# Crear archivo: {f['path']}",
            "description": f"Crear {f['type']}: {f['reason']}",
            "template_provided": True,
            "expected_exit_code": 0,
        })

    # 3. Run tests
    test_files = [f["path"] for f in files_to_create if f.get("type") == "test"]
    if test_files:
        commands.append({
            "id": f"CMD-{unit_id}-tests",
            "phase": "verify",
            "command": f"python3 -m pytest {' '.join(test_files)} -v",
            "description": "Ejecutar tests de la unidad (deben pasar)",
            "expected_exit_code": 0,
            "on_fail": "block",
        })

    # 4. Code quality check
    impl_files = [f["path"] for f in files_to_create + files_to_modify if f.get("type") in ("implementation", "modify")]
    if impl_files:
        commands.append({
            "id": f"CMD-{unit_id}-quality",
            "phase": "verify",
            "command": f"python3 scripts/python/code_quality.py --repo-root . --include {','.join(impl_files)}",
            "description": "Verificar calidad del codigo implementado",
            "expected_exit_code": 0,
            "on_fail": "warn",
        })

    # 5. Capture baseline evidence (v3.1.0)
    if flowid:
        commands.append({
            "id": f"CMD-{unit_id}-baseline",
            "phase": "evidence",
            "command": f"python3 scripts/python/evidence_visual_diff.py capture --flowid {flowid} --phase baseline --unit-id {unit_id}",
            "description": "Capturar evidence baseline para diff visual (v3.1.0)",
            "expected_exit_code": 0,
            "on_fail": "warn",
        })

    # 6. Git commit
    all_files = [f["path"] for f in files_to_create + files_to_modify]
    if all_files:
        resumen = unidad.get("resumen", unit_id)[:40].replace("'", "").replace('"', "")
        commands.append({
            "id": f"CMD-{unit_id}-commit",
            "phase": "finalize",
            "command": f"git add {' '.join(all_files)} && git commit -m '{unit_id}: {resumen}'",
            "description": "Commit de la implementacion",
            "expected_exit_code": 0,
            "on_fail": "warn",
        })

    return commands


# ============================================================================
# Main scaffold generation
# ============================================================================

def generate_scaffold_v3(
    plan: Dict,
    code_index: Optional[Dict],
    impact_prediction: Optional[Dict],
    flowid: str,
    repo_root: Path,
    unit_id: str = "",
    strategy: str = "topological_first",
) -> Dict[str, Any]:
    """Genera el scaffold v3 con auto-select y archivos concretos."""

    # 1. Auto-select unit if not provided
    selection_reason = ""
    if not unit_id:
        unidad, selection_reason = auto_select_unit(plan, strategy, impact_prediction)
        if not unidad:
            return {
                "success": False,
                "error": "No se pudo seleccionar unidad automaticamente",
                "reason": selection_reason,
            }
        unit_id = unidad.get("id", "U-XX")
        log(f"Auto-selected: {unit_id} ({selection_reason})", "INFO")
    else:
        # Find unit by ID
        unidad = None
        for u in plan.get("unidades", []) or []:
            if u.get("id") == unit_id:
                unidad = u
                break
        if not unidad:
            return {"success": False, "error": f"Unidad {unit_id} no encontrada en el plan"}
        selection_reason = f"unit_id explicito: {unit_id}"

    # 2. Generate files_to_create (CONCRETOS)
    files_to_create = generate_files_to_create(unidad, plan, flowid, repo_root)

    # 3. Generate files_to_modify (de acoplamientosreales)
    acopl = unidad.get("acoplamientosreales", {}) or {}
    mp_files = acopl.get("archivos", []) or []
    files_to_modify = []
    for f in mp_files:
        files_to_modify.append({
            "path": f,
            "type": "modify",
            "action": "modify",
            "reason": f"Archivo en acoplamiento real de {unit_id}",
            "must_preserve_contract": True,
        })

    # 4. Generate commands
    commands = generate_commands(unidad, files_to_create, files_to_modify, flowid)

    # 5. Build scaffold
    scaffold = {
        "implscaffoldv3": "V1",
        "schema_version": "3.1.0",
        "generated_at": now_iso(),
        "flowid": flowid,
        "unit_id": unit_id,
        "selection": {
            "strategy": strategy,
            "reason": selection_reason,
            "auto_selected": not bool(unit_id) or selection_reason.startswith("auto"),
        },
        "verdict": "proceed" if files_to_create else "block-no-files",
        "verdict_reason": f"{len(files_to_create)} files to create, {len(files_to_modify)} files to modify, {len(commands)} commands",
        "files_to_create": files_to_create,
        "files_to_modify": files_to_modify,
        "commands": commands,
        "unit_metadata": {
            "id": unit_id,
            "resumen": unidad.get("resumen", ""),
            "tipocambio": unidad.get("tipocambio", ""),
            "ejedominante": unidad.get("ejedominante", ""),
            "subeje": unidad.get("subeje", ""),
            "riesgooperativo": unidad.get("riesgooperativo", ""),
            "mpestimados": unidad.get("mpestimados", 0),
        },
        "summary": {
            "total_files_to_create": len(files_to_create),
            "total_files_to_modify": len(files_to_modify),
            "total_commands": len(commands),
            "is_concrete": len(files_to_create) > 0,
            "has_actionable_commands": len(commands) > 0,
        },
    }

    return scaffold


def main() -> int:
    args = parse_args(sys.argv[1:])
    repo_root = Path(args.get("repo-root", ".")).resolve()
    plan_path = Path(args.get("plan", ""))
    unit_id = args.get("unit-id", "")
    code_index_path = Path(args.get("code-index", "")) if args.get("code-index") else None
    impact_prediction_path = Path(args.get("impact-prediction", "")) if args.get("impact-prediction") else None
    output = Path(args.get("output", "SCAFFOLD-V3.yaml"))
    flowid = args.get("flowid", "")
    strategy = args.get("strategy", "topological_first")

    if not plan_path.exists():
        log(f"Plan no encontrado: {plan_path}", "ERROR")
        return 2

    plan = read_yaml(plan_path) or {}
    code_index = read_yaml(code_index_path) if code_index_path and code_index_path.exists() else None
    impact_prediction = read_yaml(impact_prediction_path) if impact_prediction_path and impact_prediction_path.exists() else None

    start = time.time()
    scaffold = generate_scaffold_v3(
        plan=plan,
        code_index=code_index,
        impact_prediction=impact_prediction,
        flowid=flowid,
        repo_root=repo_root,
        unit_id=unit_id,
        strategy=strategy,
    )
    duration_ms = int((time.time() - start) * 1000)

    if not scaffold.get("success", True):
        print(json.dumps(scaffold, indent=2, default=str))
        return 2

    scaffold["generator"] = {
        "script": "scripts/python/scaffold_v3.py",
        "duration_ms": duration_ms,
        "version": "3.1.0",
    }

    write_yaml(output, scaffold)

    log(
        f"Scaffold v3 for {scaffold['unit_id']}: "
        f"{scaffold['summary']['total_files_to_create']} files to create, "
        f"{scaffold['summary']['total_files_to_modify']} to modify, "
        f"{scaffold['summary']['total_commands']} commands, "
        f"verdict={scaffold['verdict']}, {duration_ms}ms",
        "INFO",
    )

    print(json.dumps({
        "success": True,
        "unit_id": scaffold["unit_id"],
        "selection_reason": scaffold["selection"]["reason"],
        "verdict": scaffold["verdict"],
        "is_concrete": scaffold["summary"]["is_concrete"],
        "files_to_create": scaffold["summary"]["total_files_to_create"],
        "files_to_modify": scaffold["summary"]["total_files_to_modify"],
        "commands": scaffold["summary"]["total_commands"],
        "duration_ms": duration_ms,
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

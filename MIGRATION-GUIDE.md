# MIGRATION GUIDE — de `apolo-flow-guardian.ts` a `apolo-dynamic-flow`

## Resumen

Esta guía te lleva de la arquitectura vieja (`apolo-flow-guardian.ts` + 8 agentes + 12 skills + 13 commands + 8 schemas) a la nueva (`apolo-dynamic-flow` con state machine explícita, scripts Python deterministas y absorción de tools externas).

## Pre-migración: backup

```bash
# Backup del plugin viejo y config
cp -r .opencode .opencode.backup.$(date +%Y%m%d)
cp opencode.json opencode.json.backup.$(date +%Y%m%d)
cp -r plan plan.backup.$(date +%Y%m%d)
```

## Paso 1: Copiar el nuevo plugin

```bash
# Asumiendo que apolo-dynamic-flow/ está en /home/z/my-project/download/
cp -r /home/z/my-project/download/apolo-dynamic-flow ./
```

## Paso 2: Migrar opencode.json

Reemplaza la entrada del plugin viejo por la nueva:

```json
{
  "plugin": {
    "apolo-dynamic-flow": "./apolo-dynamic-flow/plugin/index.ts"
  },
  "mcp": {
    "opencode-fastedit": { /* ... */ },
    "@playwright/mcp": { /* ... */ }
  }
}
```

**Eliminar** del `opencode.json`:
- Cualquier referencia a `apolo-flow-guardian.ts`
- MCPs declarados como "opcionales" pero nunca integrados (chrome-devtools-mcp, opencode-mcp-triage, etc.) — el nuevo plugin los absorberá automáticamente si los necesitas vía `absorbTools`

## Paso 3: Migrar schemas

Los 8 schemas viejos (en `.opencode/schemas/`) pueden coexistir con los 7 nuevos. Recomendado:

```bash
# Mover schemas viejos a backup
mkdir -p .opencode/schemas.viejos
mv .opencode/schemas/*.schema.yaml .opencode/schemas.viejos/

# Copiar schemas nuevos
cp apolo-dynamic-flow/schemas/*.schema.yaml .opencode/schemas/
```

**Mapeo de schemas viejos → nuevos**:

| Schema viejo | Schema nuevo | Notas |
|---|---|---|
| `00-OBJETIVO.schema.yaml` | (sin cambio) | Se mantiene compatible |
| `01-ASR.schema.yaml` | (sin cambio) | Se mantiene compatible |
| `02-VERDAD.schema.yaml` | (sin cambio) | Se mantiene compatible |
| `apolo-loop-v2.schema.yaml` | `dynamic-plan.schema.yaml` | Añade versionado, topological_sort, adaptative_gates |
| `03-PLAN-INDICE.schema.yaml` | `dynamic-plan.schema.yaml` | Reemplazado por plan dinámico |
| `MP-XX.schema.yaml` | (sin cambio) | Se mantiene compatible |
| `current.schema.yaml` | `flow-state.schema.yaml` | Reemplazado por state machine serializado |
| `evidence-index.schema.yaml` | `evidence-pack.schema.yaml` | Añade hash_chain, capabilities, degradation_log |

**Schemas nuevos sin equivalente viejo**:
- `test-result.schema.yaml` — antes no existía
- `tool-registry.schema.yaml` — antes no existía
- `telemetry-event.schema.yaml` — antes no existía (self-audit.log era pasivo)
- `block-log.schema.yaml` — antes era markdown (`99-BLOQUEOS.md`), ahora es YAML tipado

## Paso 4: Migrar agentes

Los 8 agentes viejos (orchestrator, implementer, surface-scanner, truth-auditor, microplanner, evidence-acquisition, mutation-guardian, planner) NO se eliminan. El nuevo plugin los orquesta de forma diferente:

- **orchestrator**: ahora invoca `apolo.flow.tick()` repetidamente. Ya no decide transiciones manualmente.
- **implementer**: sigue editando archivos, pero tras cada edición, el orquestador llama `apolo.tests.run({ trigger: "micro-change" })`.
- **surface-scanner**: ahora alimenta `apolo.evidence.collect()` con el scope correcto.
- **truth-auditor**: consume `EVIDENCE-PACK.yaml` en vez de pensar qué leer.
- **microplanner**: ahora consume `DYNAMIC-PLAN.yaml` generado por Python. Ya no escribe planes manualmente.
- **evidence-acquisition**: subsiste, pero `collect_evidence.py` hace el grueso del trabajo.
- **mutation-guardian**: se invoca desde `run_tests.py` con `kind=mutation`.
- **planner**: deprecado. Sus funciones las absorbe `generate_plan.py`.

**Acción**: actualiza `AGENTS.md` para reflejar los nuevos flujos. NO elimines los archivos de agentes — solo actualiza sus instrucciones.

## Paso 5: Migrar skills

Las 12 skills locales (`.opencode/skills/`) se mantienen. El nuevo plugin las absorbe automáticamente vía `tool-absorber.ts`.

**Acción**: ejecuta `apolo.tools.absorb()` después de instalar el plugin. Verifica con `apolo-inspect.sh tools` que todas aparecen en `TOOL-REGISTRY.yaml`.

## Paso 6: Migrar commands

Los 13 commands viejos siguen disponibles. El nuevo plugin añade uno nuevo: `apolo-inspect`.

**Commands viejos a deprecar**:
- `apolo-estado` → reemplazado por `apolo-inspect state`
- `apolo-reanclar` → reemplazado por `apolo.flow.tick()` (el state machine maneja reanclaje)
- `apolo-check-drift` → reemplazado por `apolo-inspect telemetry` (drift se detecta por patrones en eventos)
- `apolo-go` / `apolo-avanzar` → reemplazados por `apolo.flow.tick()` (transición explícita)

**Acción**: deja los commands viejos disponibles durante 2 semanas de migración. Después, elimínalos de `.opencode/commands/`.

## Paso 7: Migrar flows activos

Para cada flow activo en `plan/active/<FLOW>/`:

1. Crea `FLOW-STATE.yaml` desde `FLOW-STATE.template.yaml`, poblando:
   - `flowid` (el mismo del flow)
   - `phase` (la fase actual del flow, infiriendo desde `CURRENT.md`)
   - `artifacts.*` (paths a los artefactos existentes)
2. Crea `BLOCK-LOG.yaml` desde `BLOCK-LOG.template.yaml`, migrando los bloqueos de `99-BLOQUEOS.md`.
3. Crea `telemetry.jsonl` vacío (`touch`).
4. Ejecuta `apolo.tools.absorb()` para poblar `TOOL-REGISTRY.yaml`.

**Script de migración automática** (sugerido):

```python
#!/usr/bin/env python3
"""Migra flows viejos a FLOW-STATE.yaml."""
import sys
from pathlib import Path
sys.path.insert(0, "apolo-dynamic-flow/scripts/python")
from common import read_yaml, write_yaml, now_iso

for flow_dir in Path("plan/active").iterdir():
    if not flow_dir.is_dir():
        continue
    flowid = flow_dir.name
    if (flow_dir / "FLOW-STATE.yaml").exists():
        continue  # ya migrado
    state = {
        "flowstate": "V2",
        "flowid": flowid,
        "version": 1,
        "schema_version": "V2",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "phase": "reanclaje",  # default; ajustar manualmente
        "phase_entered_at": now_iso(),
        "history": [],
        "loops": {
            "reanclaje": {"current": 0, "max": 2, "last_decision": ""},
            "planning-bootstrap": {"current": 0, "max": 2, "last_decision": ""},
            "asr": {"current": 0, "max": 2, "last_decision": ""},
            "verdad": {"current": 0, "max": 2, "last_decision": ""},
            "shaping": {"current": 0, "max": 2, "last_decision": ""},
            "plan-indice": {"current": 0, "max": 2, "last_decision": ""},
            "mp-validation": {"current": 0, "max": 2, "last_decision": ""},
            "implementation": {"current": 0, "max": 4, "last_decision": ""},
            "critical-validation": {"current": 0, "max": 2, "last_decision": ""},
        },
        "circuit_breaker": {"policy": "fail-closed", "escalation_path": []},
        "artifacts": {
            "objetivo": str(flow_dir / "00-OBJETIVO.yaml") if (flow_dir / "00-OBJETIVO.yaml").exists() else "",
            "asr": str(flow_dir / "01-ASR.yaml") if (flow_dir / "01-ASR.yaml").exists() else "",
            "verdad": str(flow_dir / "02-VERDAD.yaml") if (flow_dir / "02-VERDAD.yaml").exists() else "",
            "shaping": str(flow_dir / "02.5-PLAN-SHAPING.yaml") if (flow_dir / "02.5-PLAN-SHAPING.yaml").exists() else "",
            "plan_indice": str(flow_dir / "03-PLAN-INDICE.yaml") if (flow_dir / "03-PLAN-INDICE.yaml").exists() else "",
            "current_mps": [],
            "evidence_pack": "",
            "test_runs": [],
            "blocks_log": str(flow_dir / "BLOCK-LOG.yaml"),
        },
        "tools_absorbed": [],
        "tokens_consumed_total": 0,
        "operator_hints": [],
    }
    write_yaml(flow_dir / "FLOW-STATE.yaml", state)
    print(f"Migrado: {flowid}")
```

## Paso 8: Verificación post-migración

```bash
# 1. Tests del plugin pasan
cd apolo-dynamic-flow && python3 tests/run_all_tests.py

# 2. Tools absorbidas
./scripts/bash/apolo-inspect.sh tools

# 3. Health check
./scripts/bash/apolo-inspect.sh health

# 4. Estado de flows migrados
./scripts/bash/apolo-inspect.sh state --flowid APOLO-20260620-TU-FLOW

# 5. Panel de telemetría
./scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-TU-FLOW
```

## Rollback

Si algo falla:

```bash
# Restaurar opencode.json
cp opencode.json.backup.YYYYMMDD opencode.json

# Restaurar .opencode
rm -rf .opencode
mv .opencode.backup.YYYYMMDD .opencode

# Restaurar plan
rm -rf plan
mv plan.backup.YYYYMMDD plan

# Eliminar plugin nuevo (opcional)
rm -rf apolo-dynamic-flow
```

## Tiempos estimados

- **Setup**: 30 min (copiar plugin, editar opencode.json)
- **Migración de schemas**: 15 min
- **Migración de flows activos**: 1-2 horas (depende de cuántos flows)
- **Verificación**: 30 min
- **Total**: 2-3 horas para migración completa

## Soporte

Si encuentras issues durante la migración:
1. Verifica que `python3 tests/run_all_tests.py` pasa.
2. Verifica que `apolo-inspect.sh health` reporta todas las tools como `active` o `degraded` (no `unverified`).
3. Revisa `telemetry.jsonl` del flow problemático — los eventos `block-detected` y `gate-evaluated` te dirán dónde se atascó.

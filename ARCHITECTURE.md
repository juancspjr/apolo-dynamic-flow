# ARCHITECTURE — apolo-dynamic-flow

## Visión general

`apolo-dynamic-flow` es un plugin OpenCode (TypeScript) que reemplaza a `apolo-flow-guardian.ts`. Su objetivo es orquestar agentes con **flujos dinámicos** (no planes estáticos), apoyándose en **scripts Python deterministas** para todo lo que no requiere razonamiento del agente.

## Diagrama de componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OpenCode Runtime                              │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │              plugin/index.ts (entry point)                      │ │
│  │  hooks: tool:execute:before/after, session:start               │ │
│  │  tools: apolo.flow.{init,tick}                                  │ │
│  │         apolo.evidence.collect                                  │ │
│  │         apolo.plan.generate                                     │ │
│  │         apolo.tests.run                                         │ │
│  │         apolo.tools.absorb                                      │ │
│  │  commands: apolo-inspect                                        │ │
│  └────────────────┬───────────────────────────────────────────────┘ │
│                   │                                                   │
│  ┌────────────────▼──────────────────┐  ┌─────────────────────────┐ │
│  │  state-machine.ts                  │  │  telemetry.ts           │ │
│  │  - TRANSITIONS table               │  │  - appendEvent (jsonl)  │ │
│  │  - GATES por fase                  │  │  - computeStats          │ │
│  │  - canTransit, evaluateGate        │  │  - readEvents            │ │
│  └────────────────┬──────────────────┘  └─────────────────────────┘ │
│                   │                                                   │
│  ┌────────────────▼──────────────────┐  ┌─────────────────────────┐ │
│  │  loop-engine.ts                    │  │  block-detector.ts      │ │
│  │  - runLoopIteration                │  │  - detectBlocks         │ │
│  │  - transit / blockAndStay          │  │  - PLAN_CYCLE = 3       │ │
│  │  - circuit breaker (fail-closed /  │  │  - CONTEXT_OVERLOAD =12 │ │
│  │    fail-open-adaptive)             │  │  - suggestResolution    │ │
│  └────────────────┬──────────────────┘  └─────────────────────────┘ │
│                   │                                                   │
│  ┌────────────────▼──────────────────────────────────────────────┐  │
│  │              Wrappers TS → Python scripts                     │  │
│  │  evidence-collector.ts → collect_evidence.py                  │  │
│  │  plan-generator.ts     → generate_plan.py                     │  │
│  │  test-runner.ts        → run_tests.py + rollback.py           │  │
│  │  tool-absorber.ts      → absorb_mcp.py                        │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Filesystem artifacts                            │
│                                                                      │
│  plan/active/<FLOW>/                                                 │
│    FLOW-STATE.yaml          ← state machine persistido               │
│    BLOCK-LOG.yaml            ← bloqueos activos                       │
│    telemetry.jsonl           ← eventos append-only                    │
│    00-OBJETIVO.yaml                                                 │
│    01-ASR.yaml                                                      │
│    02-VERDAD.yaml                                                   │
│    02.5-PLAN-SHAPING.yaml                                           │
│    03-PLAN-INDICE-DYNAMIC.yaml  ← generado por Python                 │
│    evidence/EVIDENCE-PACK.yaml  ← generado por Python                 │
│    tests/run-<ts>-<uuid>.yaml   ← generado por Python                 │
│                                                                      │
│  .opencode/apolo-dynamic/                                            │
│    TOOL-REGISTRY.yaml         ← tools absorbidas                     │
│    screenshots/                ← capturas de playwright               │
└─────────────────────────────────────────────────────────────────────┘
```

## Decisiones de diseño

### 1. State machine explícita (no "planificación libre")

El proyecto viejo dejaba al orquestador decidir cuándo transitar de fase. Eso llevaba a:
- Transiciones implícitas que nadie auditaba.
- "Plan tras plan": el sistema volvía a `planning-bootstrap` sin razón clara.
- Bloqueos que se registraban pero no se resolvían.

**Solución**: tabla `TRANSITIONS` explícita con gates nombrados. Cada transición requiere:
- `from` y `to` válidos
- `gate` evaluado antes de transitar
- `requires` (artefactos que deben existir en `state.artifacts`)

### 2. Loop dinámico con circuit breaker por fase

Cada fase tiene su propio `LoopCounter`:
```yaml
loops:
  verdad: { current: 0, max: 2, last_decision: "" }
  implementation: { current: 0, max: 4, last_decision: "" }
```

Cuando un gate devuelve `refine`, se incrementa `current`. Si `current >= max`:
- `fail-closed` (default): bloquear y esperar intervención.
- `fail-open-adaptive`: escalar a `escalation_path[0]` si está definido.

**Resultado**: imposible entrar en loop infinito. El circuit breaker siempre corta.

### 3. Recolección determinista de evidencia

El proyecto viejo dependía del agente para "pensar" qué evidencia recopilar. Eso producía:
- Evidence packs incompletos.
- Variabilidad entre runs.
- El agente gastaba tokens decidiendo qué recopilar.

**Solución**: `collect_evidence.py` es determinista. Recibe un `scope` JSON y produce siempre el mismo `EVIDENCE-PACK.yaml` para los mismos inputs. El agente solo decide el scope, no cómo recopilar.

### 4. Planes generados por Python

El proyecto viejo usaba `02.5-PLAN-SHAPING.yaml` escrito por el agente. Eso producía:
- Planes estáticos que no se adaptaban a nueva evidencia.
- El agente perdía tokens pensando en partición de unidades.

**Solución**: `generate_plan.py` lee `EVIDENCE-PACK.yaml` + `02-VERDAD.yaml` y genera `DYNAMIC-PLAN.yaml` con:
- Unidades derivadas de clusters de verdad.
- `topological_sort` por algoritmo de Kahn sobre `dependenciasprevias`.
- `adaptative_gates` que pueden reescribir el plan en runtime.
- `rewrite_history` que audita cada versión.

### 5. Tests tras cada cambio

El proyecto viejo no tenía tests automáticos. El agente "verificaba" con narrativa.

**Solución**: `run_tests.py` se ejecuta tras cada `micro-change` o `section-change`. Si falla y el cambio fue micro → `rollback.py` restaura los archivos afectados vía `git restore`.

### 6. Absorción de tools externas

El proyecto viejo declaraba MCPs como "opcionales" pero nunca los integraba al orquestador.

**Solución**: `tool-absorber.ts` escanea:
- `opencode.json#mcp.*` → registra cada MCP con capabilities inferidas.
- `.opencode/skills/*/SKILL.md` → registra cada skill local.
- `.opencode/plugin/*.ts` → registra cada plugin TS.
- `scripts/python/*.py` → registra cada script Python.

Cada tool tiene:
- `health_check` (comando bash que verifica disponibilidad).
- `fallback` (tool alternativa si esta falla).
- `capabilities` (tags para lookup por capacidad).

Conflictos (mismas capabilities) se detectan y registran con `resolution: priority-first` por defecto.

### 7. Telemetría append-only

Cada decisión del orquestador emite un `TelemetryEvent` a `telemetry.jsonl`. El panel HTML los consume via fetch (cada 5s).

Tipos de evento:
- `phase-enter`, `phase-exit` — transiciones de fase.
- `loop-iter` — iteración de bucle en una fase.
- `gate-evaluated` — gate evaluado con su decisión.
- `block-detected`, `block-resolved` — bloqueos.
- `tool-absorbed`, `tool-invoked`, `tool-failed` — tools.
- `evidence-captured` — recolección completada.
- `plan-version-bump` — plan reescrito.
- `test-run`, `test-fail`, `rollback` — tests.
- `tokens-spent`, `operator-hint` — métricas y sugerencias.

### 8. Sin dependencias externas

- TypeScript plugin: solo usa `child_process`, `crypto`, `fs`, `path`. No requiere npm install.
- Python scripts: solo stdlib (`hashlib`, `json`, `subprocess`, `pathlib`, `re`). No requiere pip install.
- YAML parser/serializer: implementación propia minimalista (no PyYAML).
- JSON schema: validación mínima propia (no jsonschema).

**Trade-off**: el parser YAML no soporta features avanzadas (anchors, multi-line strings con `|`, flow style `{a: 1, b: 2}`). Para proyectos serios, instalar PyYAML y reemplazar `common.yaml_load/yaml_dump`.

## Flujo de un flow completo

```
1. Session start
   └─ absorbTools() → TOOL-REGISTRY.yaml poblado

2. apolo.flow.init({ flowid })
   └─ Crea FLOW-STATE.yaml con phase=reanclaje, loops=0

3. Loop hasta cierre:
   ├─ apolo.flow.tick()
   │   ├─ runLoopIteration(state, ctx)
   │   │   ├─ evaluateGate(gate_for_phase, ctx)
   │   │   ├─ if pass → transit → reset counter de la fase destino
   │   │   ├─ if refine → counter++ → if maxed → block/escalate
   │   │   └─ if block → blockAndStay → BLOCK-LOG.yaml
   │   ├─ detectBlocks(state) → detecta plan cycles, context overload
   │   └─ Persistir state + telemetría

4. En fase 'verdad':
   └─ apolo.evidence.collect({ scope: {...} })
       └─ collect_evidence.py → EVIDENCE-PACK.yaml

5. En fase 'plan-indice':
   └─ apolo.plan.generate({ verdad_path })
       └─ generate_plan.py → 03-PLAN-INDICE-DYNAMIC.yaml

6. En fase 'implementation':
   └─ Por cada MP:
       ├─ implementer edita archivos
       └─ apolo.tests.run({ trigger: "micro-change" })
           └─ run_tests.py + rollback.py si fail

7. En fase 'critical-validation':
   └─ apolo.tests.run({ trigger: "full-plan", kind: "mutation" })

8. En fase 'cierre-flow':
   └─ READINESS-REPORT generado desde state final
```

## Métricas de mejora esperada vs apolo-flow-guardian.ts

| Métrica | apolo-flow-guardian.ts | apolo-dynamic-flow |
|---|---|---|
| Líneas de código del plugin | 1,445 TS | ~1,600 TS + ~1,400 Python |
| Tests del propio plugin | 0 | 5 suites (todas pasan) |
| Schemas YAML | 8 (con duplicaciones) | 7 nuevos (sin duplicaciones) |
| MCPs integrados | 0 efectivos (solo declarados) | Todos los registrados absorbidos |
| Recolección de evidencia | Agente piensa | Script Python determinista |
| Generación de planes | Agente escribe YAML | Script Python desde evidence |
| Tests tras cambios | No | Automáticos con rollback |
| Loop infinito posible | Sí | No (circuit breaker por fase) |
| Telemetría | self-audit.log (pasivo) | telemetry.jsonl + panel HTML |
| CLI de inspección | No | apolo-inspect con 7 subcomandos |

## Limitaciones conocidas

1. **YAML parser minimalista**: no soporta anchors, multi-line strings con `|`, flow style. Para proyectos serios, instalar PyYAML.
2. **JSON schema validation mínima**: solo valida `required`, `type`, `enum`, `pattern`. No soporta `$ref`, `allOf`, `oneOf`. Para validación completa, instalar jsonschema.
3. **Tests Python del plugin TS**: los tests validan contratos leyendo el código TS, no ejecutándolo. Para tests reales, transpilar con `tsc` y ejecutar con node.
4. **Playwright screenshots**: requieren `npx` y conexión a internet la primera vez (descarga el binario).
5. **Mutación de tests**: `run_tests.py` detecta `kind=mutation` pero no implementa mutación real (requiere mutmut/go-mutesting). Solo corre tests normales y reporta.

## Próximos pasos sugeridos

1. Instalar PyYAML y jsonschema para robustez YAML/schema completa.
2. Integrar `mutmut` (Python) y `go-mutesting` (Go) para mutación real.
3. Compilar el plugin TS con `tsc` y empaquetar como npm package.
4. Añadir tests E2E que simulen un flow completo (init → tick × N → cierre).
5. Migrar progresivamente los 12 skills locales al nuevo formato de tool-absorber.

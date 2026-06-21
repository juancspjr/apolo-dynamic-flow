# APOLO Dynamic Flow

> **Plugin de orquestación de agentes para OpenCode** con flujos dinámicos, recolección híbrida de evidencia (scripts Python + agente), planes con 3 modos (deterministic/hybrid/manual), tests automáticos tras cada cambio y absorción de tools externas.

[![Tests](https://img.shields.io/badge/tests-40%2F40%20passing-brightgreen)](#10-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)
[![Version](https://img.shields.io/badge/version-2.5.0-blue)](#changelog)

---

## Tabla de contenidos

1. [Qué es este plugin](#1-qué-es-este-plugin)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Instalación](#3-instalación)
4. [Verificación](#4-verificación-de-la-instalación)
5. [Integración con OpenCode](#5-integración-con-opencode)
6. [Estructura](#6-estructura-completa-del-plugin)
7. [CLI apolo-inspect](#7-uso-del-cli-apolo-inspectsh)
8. [Panel de telemetría](#8-panel-de-telemetría)
9. [Configuración](#9-configuración-avanzada)
10. [Tests](#10-tests)
11. [Troubleshooting](#11-troubleshooting)
12. [Cómo funciona](#12-cómo-funciona-internamente)
13. [Docs adicionales](#13-documentación-adicional)
14. [Changelog](#changelog)
15. [Licencia](#licencia)

---

## 1. Qué es este plugin

`apolo-dynamic-flow` es un plugin TypeScript para OpenCode que **reemplaza a `apolo-flow-guardian.ts`**. Orquesta agentes con:

- **State machine explícita** con transiciones legales y gates por fase (no "planificación libre").
- **Loop dinámico con circuit breaker adaptativo** — cada fase tiene `max` iteraciones; al agotarse, escala o bloquea (sin loops infinitos).
- **Recolección híbrida de evidencia** (v2.2.1) — scripts Python capturan archivos, git diff, símbolos, endpoints, DB queries, screenshots, **Y el agente puede aportar evidencia propia** (observaciones, contexto cualitativo, runtime logs no capturables) vía `--agent-evidence`. Producen `EVIDENCE-PACK.yaml` con hash chain.
- **Planes con 3 modos** (v2.2.1) — `generate_plan.py` soporta `deterministic-python` (script genera todo), `hybrid` (script genera base + agente ajusta), `manual` (agente escribe todo, script valida). Permite manejar desde fixes mecánicos hasta elementos artísticos.
- **Tests automáticos tras cada cambio** — `run_tests.py` se ejecuta tras micro-cambios. Si falla y el cambio fue micro → rollback automático vía `git restore`.
- **Absorción automática de tools externas** — descubre MCPs en `opencode.json`, skills en `.opencode/skills/`, plugins en `.opencode/plugin/`, scripts en `scripts/python/`. Verifica salud y registra en `TOOL-REGISTRY.yaml`.
- **Absorción de skills externas** (v2.2.0) — `absorb_external_skills.py` descarga skills desde URLs, GitHub repos y hubs especializados (awesome-opencode, etc.).
- **Telemetría append-only** + panel HTML para visualización en tiempo real.
- **Routing declarativo** — `routing-rules.json` con 10 reglas editables sin tocar código TS.
- **Árbol de decisión D-NNN** — reemplaza "plan tras plan" por árbol finito con circuit breaker por patrón de fallos.
- **Tests TypeScript ejecutables** — 35 tests con `node --test` que validan módulos reales del plugin.
- **4 gaps cerrados** (v2.2.0):
  - `index_codebase.py` — comprensión de código via AST
  - `score_evidence.py` — scoring de calidad de evidencia
  - `predict_impact.py` — hologramas/predicción de impacto
  - `scaffold_impl.py` — andamio de implementación
- **Gestión activa de tools** (v2.2.0):
  - `apolo.context.query` — responde 17 tipos de preguntas del agente
  - `apolo.registry.recommend` — recomienda tools con scoring
  - `apolo.health.check` — hot reload de tools

### Problemas que resuelve (vs. plugin viejo)

| Problema | apolo-flow-guardian.ts | apolo-dynamic-flow |
|---|---|---|
| Planes estáticos | Sí, no se adaptaban | Planes dinámicos con 3 modos (deterministic/hybrid/manual) |
| Loop infinito "plan tras plan" | Sí | Circuit breaker por fase + árbol de decisión D-NNN |
| Recolección de evidencia | Agente piensa | Scripts Python deterministas + agente aporta evidencia propia (híbrido) |
| Tests tras cambios | No | Automáticos con rollback |
| MCPs absorbidos | No, solo declarados | Auto-descubrimiento + health check + fallback + hot reload |
| Skills externas | No | Absorción desde URLs/GitHub/hubs |
| Telemetría | self-audit.log pasivo | telemetry.jsonl + panel HTML + runtime-audit.log |
| Tests del propio plugin | 0 | 5 suites Python + 35 tests TypeScript |
| Routing | Lógica opaca en Python | Routing declarativo editable (routing-rules.json) |

---

## 2. Prerrequisitos

| Herramienta | Versión mínima | Verificar | Instalar |
|---|---|---|---|
| **Node.js** | 18.0.0 | `node --version` | `sudo apt install -y nodejs` |
| **npm** | 9.0.0 | `npm --version` | `sudo apt install -y npm` |
| **Python 3** | 3.10 | `python3 --version` | `sudo apt install -y python3` |
| **curl** | cualquiera | `curl --version` | `sudo apt install -y curl` |
| **git** | cualquiera | `git --version` | `sudo apt install -y git` |

Dependencias opcionales (auto-instaladas por `install.sh`):

- **PyYAML** — `pip3 install --user PyYAML`
- **jsonschema** — `pip3 install --user jsonschema`
- **playwright** — `npx playwright install chromium`

---

## 3. Instalación

### Método A — `install.sh` (recomendado)

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
```

El script hace 7 pasos: verificar prerrequisitos, validar archivos, crear carpetas, instalar npm deps, instalar Python deps, compilar TypeScript, correr tests Python y TypeScript.

### Método B — Manual

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
mkdir -p .opencode/apolo-dynamic/screenshots plan/active
npm install
pip3 install --user PyYAML jsonschema
npx tsc
python3 tests/run_all_tests.py
node --test dist/tests/plugin.test.js
```

### Opciones de `install.sh`

```bash
./install.sh                  # instalación completa
./install.sh --check          # solo verificar prerrequisitos
./install.sh --tests          # solo correr tests
./install.sh --no-npm         # saltar npm install
./install.sh --no-python-deps # saltar pip install
```

---

## 4. Verificación de la instalación

```bash
# Tests Python (5 suites, 42 asserts)
python3 tests/run_all_tests.py
# → "ALL 5 TESTS PASSED ✓"

# Tests TypeScript (35 tests)
npx tsc && node --test dist/tests/plugin.test.js
# → "pass 35 / fail 0"

# CLI funciona
bash scripts/bash/apolo-inspect.sh help

# Absorber tools
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)

# Init flow de prueba
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-$(date +%Y%m%d)-TEST
```

---

## 5. Integración con OpenCode

Edita el `opencode.json` de tu proyecto destino:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "./apolo-dynamic-flow/plugin/index.ts"
  ],
  "mcp": {
    "@playwright/mcp": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp@latest"],
      "enabled": true
    }
  }
}
```

> **IMPORTANTE**: `plugin` debe ser un **array** de strings (no un objeto).

Verificar: `opencode mcp list` debe listar MCPs sin error.

### Cómo el agente OpenCode absorbe este plugin

Cuando OpenCode carga el plugin, el archivo `plugin/index.ts` expone:

1. **Hooks**: `tool:execute:before`, `tool:execute:after`, `session:start`
2. **Tools** (invocables por el orquestador):
   - `apolo.flow.init` — inicializa un flow nuevo
   - `apolo.flow.tick` — ejecuta una iteración del loop dinámico
   - `apolo.evidence.collect` — dispara recolección híbrida (scripts + agente)
   - `apolo.plan.generate` — genera plan dinámico (3 modos)
   - `apolo.tests.run` — ejecuta tests tras cambios
   - `apolo.tools.absorb` — descubre y registra tools externas
   - `apolo.context.query` (v2.2.0) — consulta activa al sistema
   - `apolo.registry.recommend` (v2.2.0) — recomienda tools con scoring
   - `apolo.health.check` (v2.2.0) — hot reload de tools
3. **Commands**: `apolo-inspect` con 12 subcomandos

Ejemplo de uso desde el orquestador:

```typescript
// Inicializar un flow
await tools["apolo.flow.init"]({ flowid: "APOLO-20260620-MI-FLOW" });

// Loop principal
while (!done) {
  const result = await tools["apolo.flow.tick"]({ evidence_pack: true });
  if (result.decision === "block") break;
}

// Recolectar evidencia en modo híbrido (agente aporta observaciones)
await tools["apolo.evidence.collect"]({
  scope: { paths: ["src/handlers/foo.go"], endpoints: ["/api/v1/foo"] },
  invoked_by: "orchestrator",
  agent_evidence: [
    { kind: "runtime-log", source: "manual observation",
      summary: "race condition en foo()",
      agent_reasoning: "observé que cuando se llama dos veces rápido, falla" }
  ],
  agent_summary: "El agente observó comportamientos no detectables por scripts"
});

// Generar plan en modo hybrid (agente ajusta)
await tools["apolo.plan.generate"]({
  verdad_path: "plan/active/APOLO-20260620-MI/02-VERDAD.yaml",
  method: "hybrid",
  agent_adjustments: [
    { type: "mark-needs-judgment", unit_id: "U-01", reason: "decisión UX subjetiva" }
  ],
  agent_context: "El agente considera que U-01 requiere juicio humano"
});

// Tests tras implementación
await tools["apolo.tests.run"]({
  trigger: "micro-change",
  scope: { kind: "unit", targets: ["src/handlers/foo.go"], mp_id: "MP-01" },
  rollback_on_fail: true
});
```

---

## 6. Estructura completa del plugin

```
apolo-dynamic-flow/
├── install.sh                          # Instalación automática (7 pasos)
├── README.md                           # Este archivo
├── ARCHITECTURE.md / MIGRATION-GUIDE.md / ANALYSIS-REPORT.md
├── opencode.json / package.json (v2.2.1) / tsconfig.json
├── routing-rules.json                  # Routing declarativo (R-001..R-010)
│
├── plugin/                             # 18 módulos TypeScript
│   ├── index.ts, types.ts, state-machine.ts, loop-engine.ts
│   ├── block-detector.ts, evidence-collector.ts, plan-generator.ts
│   ├── test-runner.ts, tool-absorber.ts, telemetry.ts, inspector.ts, utils.ts
│   ├── core/
│   │   ├── runtime-logger.ts           # Log JSON Lines con seq monotónico
│   │   ├── router.ts                   # Router declarativo
│   │   ├── loop-engine-tree.ts         # Árbol de decisión D-NNN
│   │   └── micro-test-runner.ts        # Runner de micro-tests
│   ├── absorbers/
│   │   └── mcp-loader.ts               # Absorbedor MCP con fallback
│   └── parallel/
│       └── hypothesis-runner.ts        # Paralelizador de hipótesis
│
├── schemas/                            # 11 schemas
│   ├── *.schema.yaml (7)               # Schemas YAML de artefactos
│   └── json/                           # JSON schemas estrictos (draft-07)
│       ├── agent-io.json
│       ├── loop-engine-decision.json
│       ├── routing-rules.schema.json   # renombrado en v2.2.1
│       └── runtime-audit-log.json
│
├── templates/                          # 5 templates YAML
├── scripts/
│   ├── python/                         # 18 scripts Python
│   │   ├── common.py, collect_evidence.py (híbrido v2.2.1)
│   │   ├── generate_plan.py (3 modos v2.2.1)
│   │   ├── run_tests.py, absorb_mcp.py, validate_artifact.py
│   │   ├── telemetry_aggregator.py, inspect_tools.py
│   │   ├── rollback.py, serve_panel.py
│   │   ├── index_codebase.py (Gap 1)
│   │   ├── score_evidence.py (Gap 2)
│   │   ├── predict_impact.py (Gap 3)
│   │   ├── scaffold_impl.py (Gap 4)
│   │   ├── context_query.py (apolo.context.query)
│   │   ├── registry_recommend.py (apolo.registry.recommend)
│   │   ├── health_check.py (apolo.health.check + hot reload)
│   │   └── absorb_external_skills.py (URLs/GitHub/hubs)
│   └── bash/apolo-inspect.sh           # CLI (12 subcomandos, puerto 8765)
├── panel/                              # Panel de telemetría HTML
└── tests/                              # 6 suites (40 tests totales)
    ├── run_all_tests.py + test_*.py (5)
    └── plugin.test.ts                  # 35 tests TS con node --test
```

**Total**: 76 archivos (sin contar `node_modules`, `.git`, runtime artifacts).

---

## 7. Uso del CLI `apolo-inspect.sh`

```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [opciones]
```

### Subcomandos

| Subcomando | Descripción |
|---|---|
| `init-flow` | Inicializa un flow nuevo |
| `absorb` | Descubre y registra tools externas |
| `state` | Estado del flow activo |
| `tools` | Lista tools absorbidas |
| `blocks` | Lista bloqueos activos |
| `telemetry` | Stats de telemetría |
| `evidence` | Evidence pack actual |
| `plan` | Plan dinámico actual |
| `health` | Health check de tools |
| `all` | Resumen completo |
| `serve-panel` | Levanta panel HTTP (puerto 8765) |
| `test` | Corre tests del plugin |
| `help` | Muestra la ayuda |

### Opciones globales

| Opción | Descripción | Default |
|---|---|---|
| `--flowid FLOW` | Flow ID a inspeccionar | Detecta de `plan/CURRENT.md` |
| `--repo-root PATH` | Raíz del repo | Directorio actual |
| `--json` | Output en JSON (cuando aplica) | Off |

### Variables de entorno

| Variable | Descripción | Default |
|---|---|---|
| `PYTHON` | Path a python3 | `python3` |
| `PORT` | Puerto para `serve-panel` | `8765` |

---

## 8. Panel de telemetría

```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
# → http://localhost:8765/
```

7 tabs: Overview, Timeline, Loops, Blocks, Tests, Tools, Tokens. Auto-refresh cada 5s.

### Cambiar el puerto

```bash
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
```

---

## 9. Configuración avanzada

### Circuit breaker

En `templates/FLOW-STATE.template.yaml`:

```yaml
loops:
  verdad: { current: 0, max: 2, last_decision: "" }
  implementation: { current: 0, max: 4, last_decision: "" }
circuit_breaker:
  policy: fail-closed   # fail-closed | fail-open-adaptive
  escalation_path: []
```

### Routing declarativo

Edita `routing-rules.json` para cambiar qué agent se invoca en cada fase. 10 reglas (R-001..R-010).

### Recolección híbrida de evidencia (v2.2.1)

El agente puede aportar evidencia propia además de la que el script recolecta automáticamente:

```bash
python3 scripts/python/collect_evidence.py \
  --flowid APOLO-20260620-TEST --repo-root . \
  --output plan/active/APOLO-20260620-TEST/evidence/EVIDENCE-PACK.yaml \
  --scope-json '{"paths":["plugin/index.ts"],"endpoints":["/api/v1/foo"],"git_diff":true}' \
  --agent-evidence '[
    {"kind":"runtime-log","source":"manual observation",
     "summary":"race condition en init()",
     "agent_reasoning":"observé que cuando se llama init() dos veces rápido, falla"},
    {"kind":"capture","source":"screenshot UI",
     "summary":"el botón desaparece en mobile"}
  ]' \
  --agent-summary "El agente observó 2 comportamientos no detectables por scripts" \
  --agent-tags "runtime,manual-verified,ui-bug"
```

Los items del agente se mergean con los del script, marcados con `agent_observed: true` y IDs E-101+.

### 3 modos de generación de planes (v2.2.1)

```bash
# Modo 1: deterministic-python (default, para fixes/refactors mecánicos)
python3 scripts/python/generate_plan.py \
  --flowid APOLO-20260620-TEST --method deterministic-python \
  --evidence ... --verdad ... --output ...

# Modo 2: hybrid (para UX/diseño donde el agente ajusta)
python3 scripts/python/generate_plan.py \
  --flowid APOLO-20260620-TEST --method hybrid \
  --evidence ... --verdad ... --output ... \
  --agent-adjustments '[
    {"type":"mark-needs-judgment","unit_id":"U-01","reason":"decisión UX subjetiva"},
    {"type":"add-unit","unit":{"id":"U-99","resumen":"agente considera que falta este cambio"}},
    {"type":"modify-unit","unit_id":"U-02","modifications":{"riesgooperativo":"alto"}}
  ]' \
  --agent-context "El agente considera que U-01 requiere decisión humana sobre UX"

# Modo 3: manual (para elementos artísticos/subjetivos)
python3 scripts/python/generate_plan.py \
  --flowid APOLO-20260620-TEST --method manual \
  --evidence ... --verdad ... --output ... \
  --agent-adjustments '[
    {"id":"U-01","resumen":"rediseño del logo","tipocambio":"feat"},
    {"id":"U-02","resumen":"cambiar paleta de colores","tipocambio":"feat"}
  ]'
```

### Absorción de skills externas (v2.2.0)

```bash
# Absorber una skill de un URL directo
python3 scripts/python/absorb_external_skills.py \
  --repo-root . \
  --source github://opencode-ai/awesome-opencode/skills/my-skill/SKILL.md

# Absorber múltiples skills desde un archivo
python3 scripts/python/absorb_external_skills.py \
  --repo-root . \
  --sources-file skills-to-absorb.txt

# Absorber un hub completo
python3 scripts/python/absorb_external_skills.py \
  --repo-root . \
  --hub awesome-opencode
```

### Gestión activa de tools (v2.2.0)

```bash
# Consultar al sistema en lenguaje natural
python3 scripts/python/context_query.py \
  --flowid APOLO-20260620-TEST --repo-root . \
  --phase implementation --question "qué fase sigue"

# Recomendar tool para una tarea
python3 scripts/python/registry_recommend.py \
  --task "correr tests de TypeScript" --repo-root . --top 3

# Health check con hot reload
python3 scripts/python/health_check.py --repo-root . --fix true
```

---

## 10. Tests

El plugin tiene **40 tests** en 2 categorías.

### Correr todos los tests

```bash
# Tests Python (5 suites, 42 asserts)
python3 tests/run_all_tests.py

# Tests TypeScript (35 tests ejecutables)
npx tsc && node --test dist/tests/plugin.test.js

# Ambos con npm
npm run test:all
```

### Suites Python (5)

| Suite | Qué valida | # asserts |
|---|---|---:|
| `test_state_machine.py` | FSM: transiciones legales, gates | 6 |
| `test_loop_engine.py` | Loop dinámico, circuit breaker | 8 |
| `test_block_detector.py` | Detección de bloqueos | 7 |
| `test_tool_absorber.py` | Absorción de tools externas | 10 |
| `test_python_scripts.py` | Scripts Python (YAML, hash, generate_plan) | 11 |

### Suite TypeScript (35 tests ejecutables)

| Describe block | Tests | Qué valida |
|---|---:|---|
| `RuntimeLogger` | 4 | log JSON Lines, seq monotónico, pasivo |
| `DeclarativeRouter` | 5 | routing-rules.json, R-001..R-010, fallback |
| `LoopEngineTree` | 6 | D-001, advance, detectCircuitBreaker |
| `MicroTestRunner` | 4 | extractTestCommand, runTest |
| `McpAbsorber` | 7 | detectAvailableMcps, invokeMcp con fallback |
| `ParallelHypothesisRunner` | 5 | planHypotheses, selectWinner, scoreHypothesis |
| `ContextQueryTools` (v2.2.0) | 3 | apolo.context.query, registry.recommend, health.check |

**Total**: 35 tests TS + 42 asserts Python = **77 verificaciones**

---

## 11. Troubleshooting

### `Error: Configuration is invalid at opencode.json`

`plugin` debe ser array, no objeto:

```json
// Incorrecto
"plugin": { "apolo-dynamic-flow": "./plugin/index.ts" }

// Correcto
"plugin": [ "./plugin/index.ts" ]
```

### `OSError: Address already in use`

```bash
fuser -k 8765/tcp
# o usar otro puerto
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel ...
```

### Panel devuelve 404

Las rutas en `panel/panel.js` deben empezar con `/` (v2.2.1 ya fixeado):

```javascript
API.statePath = `/plan/active/${flowid}/FLOW-STATE.yaml`;
```

### `PY_DIR: variable sin asignar` (v2.2.1)

Si ves este error en `apolo-inspect.sh`, la sección `serve-panel` usa `$PY_DIR` que no está definido. Fix v2.2.2: usar `$PLUGIN_DIR/scripts/python`:

```bash
# Incorrecto (v2.2.1 con bug)
"$PYTHON" "$PY_DIR/serve_panel.py" ...

# Correcto (v2.2.2)
"$PYTHON" "$PLUGIN_DIR/scripts/python/serve_panel.py" ...
```

### MCPs aparecen como `failed`

Algunos paquetes npm no existen. Deshabilitar en `opencode.json` con `"enabled": false`.

### Tests fallan después de modificar `common.py`

Instalar PyYAML y reemplazar las funciones en `common.py`:

```bash
pip3 install --user PyYAML
```

```python
import yaml
def yaml_load(text): return yaml.safe_load(text)
def yaml_dump(obj): return yaml.safe_dump(obj, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

---

## 12. Cómo funciona internamente

### State machine de fases

```
reanclaje → planning-bootstrap → asr → verdad → shaping → plan-indice
                                                                ↓
                            cierre-flow ← critical-validation ← mp-validation ← implementation
```

### Loop dinámico con circuit breaker

```
tick() → evaluar gate → pass/refine/escalate/block → persistir + telemetría
```

### Recolección híbrida de evidencia (v2.2.1)

```
apolo.evidence.collect({ scope, agent_evidence, agent_summary }) →
  collect_evidence.py (Python) →
    [1] Script recolecta automáticamente:
        - File snapshots (hash SHA256)
        - Git diff / git log
        - Symbol extraction (Go/TS/Python)
        - Endpoint probes (curl)
        - DB queries (psql)
        - Screenshots (playwright si disponible)
        - Schema validation
    [2] MERGE con evidencia del agente:
        - Items aportados via --agent-evidence
        - Marcados con agent_observed: true
        - IDs E-101+ para distinguirlos
    →
  EVIDENCE-PACK.yaml (con hash_chain + agent_summary + agent_contributed_count)
```

### 3 modos de generación de planes (v2.2.1)

```
[1] deterministic-python:
    evidence + verdad → script genera unidades automáticamente → plan

[2] hybrid:
    evidence + verdad → script genera plan base →
    agente ajusta via --agent-adjustments:
      - add-unit (añadir unidad)
      - remove-unit (quitar unidad)
      - modify-unit (cambiar propiedades)
      - mark-needs-judgment (marcar como requiere decisión humana)
    → plan ajustado

[3] manual:
    agente pasa todas las unidades via --agent-adjustments →
    script solo valida schema, calcula topological sort, añade adaptative_gates
    → plan del agente validado
```

### Routing declarativo

```
route(ctx) → load routing-rules.json
           → ordenar por prioridad (1 = máxima)
           → primera regla que matchea
           → next_agent + reason + circuit_breaker
           → log al runtime-audit.log
```

### Árbol de decisión D-NNN

```
createRootNode(D-001) con 5 branches:
  - test_passes → advance_phase (terminal)
  - test_fails_retriable → retry_mp (crea D-002)
  - test_fails_terminal → raise_blocker (terminal)
  - blocker_persists → ask_operator (terminal)
  - iteration_exceeded → circuit_break (terminal)
```

### 4 gaps cerrados (v2.2.0)

```
[Gap 1] index_codebase.py → CODE-INDEX.yaml (AST, sin LLM)
[Gap 2] score_evidence.py → EVIDENCE-SCORE.yaml (coverage/freshness/depth/...)
[Gap 3] predict_impact.py → IMPACT-PREDICTION.yaml (dependency cascade,
        historical pattern, test gap)
[Gap 4] scaffold_impl.py → IMPL-SCAFFOLD-*.yaml (archivos, contracts,
        checkpoints, edit order, circular deps)
```

### Gestión activa de tools (v2.2.0)

```
apolo.context.query(question) → responde desde telemetry + state + code-index
apolo.registry.recommend(task) → scoring de tools con reasoning
apolo.health.check(fix=true) → verifica salud + re-absorbe en caliente
```

---

## 13. Documentación adicional

| Archivo | Contenido |
|---|---|
| `ARCHITECTURE.md` | Diseño detallado, decisiones técnicas, diagramas de componentes |
| `MIGRATION-GUIDE.md` | Migración desde `apolo-flow-guardian.ts` paso a paso |
| `ANALYSIS-REPORT.md` | Análisis del proyecto viejo + justificación del nuevo |

---

## Changelog

### v2.5.0

- **Calidad del análisis** (4 scripts nuevos + 1 modificado):
  - `predict_impact.py` (MODIFICADO) — `project_dependency_cascade` ahora hace **BFS multi-nivel** (no solo 1 nivel). Si A importa B que importa C que importa D, el cascade detecta A→B→C→D hasta profundidad configurable (default 5 niveles, `--cascade-depth`). Nuevos campos: `cascade_depth` (profundidad máxima alcanzada) y `affected_by_level` (conteo por nivel). Umbrales de riesgo ajustados: low <5, medium 5-15, high 16-30, critical >30.
  - `code_quality.py` (NUEVO) — Análisis de calidad **agnóstico al lenguaje** (Python, JS/TS, Go, Rust, Java, C++, PHP, HTML, CSS). Corre `bandit`, `radon`, `eslint-plugin-security`, `gosec`, `cppcheck` cuando están disponibles; degrada gracefully a regex estimation si no. Genera `CODE-QUALITY.yaml` con `security_findings`, `complexity_scores`, `high_complexity_functions` (>15) y `recommendations`.
  - `test_coverage.py` (NUEVO) — Análisis de cobertura de tests **por símbolo** (no por archivo). Integra `coverage.py` (Python), `nyc` (JS/TS) y `go test -cover` (Go). Si no hay herramientas, usa heurísticas por convención de nombres (`test_<name>.py`, `<name>_test.go`, `<name>.test.ts`). Genera `TEST-COVERAGE.yaml` con `total_symbols`, `covered_symbols`, `uncovered_symbols`, `coverage_percentage`, `critical_uncovered` (símbolos exportados sin test).
  - `lsp_integration.py` (NUEVO) — Integración con LSP para análisis semántico. Soporta `typescript-language-server`, `pylsp`/`pyright`, `gopls`, `rust-analyzer`, `jdtls`, `clangd`, `intelephense`. Implementa `find_references()`, `get_diagnostics()`, `go_to_definition()`, `get_hover()`. Si un LSP no está disponible, degrada a regex fallback.
  - `test_quality.py` (NUEVO) — 8 tests que validan las 4 nuevas capacidades. Resilientes: si una herramienta externa no está instalada, el test pasa verificando que la degradación es graceful.

### v2.4.0

- **Seguridad operacional**:
  - **Allowlist de orígenes**: `absorb_external_skills.py` ahora verifica que cada URL esté en `security_config.yaml#allowed_origins` antes de descargar. URLs no allowlisted son rechazadas. SSRF protection (localhost, 169.254.169.254, file:// bloqueados).
  - **Secret detection**: `secret_scanner.py` detecta 11 tipos de secretos (AWS keys, GitHub tokens, JWT, PEM private keys, DB connection strings, passwords, Slack tokens, Stripe keys, bearer tokens, API keys). Si detecta secretos en evidencia, los REDACTA antes de escribir el pack.
  - **Hash chain en audit log**: cada entrada de `runtime-audit.log` incluye `prev_hash` (hash de la entrada anterior) y `entry_hash` (hash de esta entrada). Manipular una entrada rompe la cadena — detectable con `verify_hash_chain()`.
  - **Sandboxing**: `security_config.yaml` soporta configuración de firejail (default) o Docker para ejecutar skills externas en entorno aislado.
  - **12 tests de seguridad** (`tests/test_security.py`): validan detección de cada tipo de secreto, redacción, allowlist (permitir/denegar/SSRF), hash chain (válido/manipulado).

### v2.3.0

- **Robustez de infraestructura**:
  - **PyYAML hard dependency**: el parser YAML minimalista fue eliminado. PyYAML es ahora obligatorio. Resuelve el riesgo de corrupción silenciosa de estado en YAML complejo.
  - **jsonschema hard dependency**: el validador minimalista fue eliminado. `jsonschema` (Draft7) es ahora obligatorio. Soporta `$ref`, `allOf`, `oneOf`, `anyOf`, `patternProperties`, `format`.
  - **Atomic writes**: `write_yaml` y `write_json` ahora usan `tempfile + os.fsync + os.replace` (rename atómico). El archivo destino nunca queda en estado parcial.
  - **File locks**: `read_yaml` adquiere `LOCK_SH` (compartido), `write_yaml` adquiere `LOCK_EX` (exclusivo) vía `fcntl.flock`. Concurrency-safe: 2 agentes pueden escribir al mismo archivo sin corromperlo.
- **Nuevos tests**: `tests/test_atomic.py` con 9 tests que validan atomicidad, concurrency, anchors YAML, strings multilínea, y que no quedan archivos temporales.
- **`install.sh`**: PyYAML y jsonschema son ahora hard requirements (no opcionales). Si no se pueden instalar, el script aborta con exit 2.

### v2.2.2

- **Fix `PY_DIR` bug**: la sección `serve-panel` de `apolo-inspect.sh` usaba `$PY_DIR` que no estaba definido, causando el error `scripts/bash/apolo-inspect.sh: línea 108: PY_DIR: variable sin asignar`. Fix: usar `$PLUGIN_DIR/scripts/python` que sí está definido.
- **README regenerado completo**: el README anterior (v2.2.1 parcheado) tenía el changelog v2.2.1 pero las secciones descriptivas seguían mostrando v2.2.0 como versión actual. Ahora el README está regenerado desde cero con toda la documentación de v2.2.1/v2.2.2 como actualidad.
- **`package.json`** — v2.2.2.

### v2.2.1

- **Modo híbrido en recolección de evidencia**: `collect_evidence.py` ahora acepta `--agent-evidence` (JSON con items aportados por el agente), `--agent-summary` (resumen cualitativo) y `--agent-tags` (tags adicionales). Los items del agente se mergean con los del script, marcados con `agent_observed: true` y IDs E-101+. Permite que el agente observe captures, añada contexto cualitativo, o incluya evidencia de runtime no capturable por scripts.
- **3 modos de generación de planes**: `generate_plan.py` ahora soporta `--method deterministic-python | hybrid | manual`:
  - **deterministic-python** (default): el script genera todo automáticamente, agente no interviene. Ideal para fixes/refactors.
  - **hybrid**: el script genera el plan base, el agente puede ajustar via `--agent-adjustments` (añadir/quitar/modificar unidades, marcar `needs_human_judgment`). Ideal para UX/diseño.
  - **manual**: el agente escribe todas las unidades via `--agent-adjustments`. El script solo valida schema, calcula topological sort y añade adaptative_gates. Ideal para elementos artísticos.
- **Fix panel**: `panel.js` ahora usa rutas absolutas (`/plan/active/...`) en vez de relativas — resuelve los 404s en el panel.
- **Fix `apolo-inspect.sh`**: `serve-panel` ahora usa `serve_panel.py` (servidor Python propio) en vez de `python3 -m http.server` desde `panel/`. Puerto default cambiado a 8765 (poco común para evitar conflictos).
- **Fix `PY_DIR` bug** (v2.2.2 micro-patch): la sección `serve-panel` usaba `$PY_DIR` que no estaba definido. Fix: usar `$PLUGIN_DIR/scripts/python`.
- **Fix schema duplicado**: `schemas/json/routing-rules.json` renombrado a `schemas/json/routing-rules.schema.json` para evitar conflicto con `routing-rules.json` de la raíz.

### v2.2.0

- **8 scripts Python nuevos** (cierre de los 4 gaps + gestión activa de tools + absorción externa):
  - `index_codebase.py` (Gap 1) — Indexador AST (Python `ast` + regex TS/JS/Go). Genera `CODE-INDEX.yaml`.
  - `score_evidence.py` (Gap 2) — Scoring de evidencia (coverage/freshness/depth/conflict/redundancy/schema).
  - `predict_impact.py` (Gap 3) — Hologramas: dependency cascade, historical pattern, test gap. Modo `--deep` añade symbol contract + git blame.
  - `scaffold_impl.py` (Gap 4) — Andamio: archivos a tocar, contracts a mantener, checkpoints, edit order, circular deps.
  - `context_query.py` — `apolo.context.query(question)` responde 17 tipos de preguntas en lenguaje natural.
  - `registry_recommend.py` — `apolo.registry.recommend(task)` recomienda tools con scoring y reasoning.
  - `health_check.py` — `apolo.health.check(fix=true)` hot reload de tools + re-absorción en caliente.
  - `absorb_external_skills.py` — Absorbe skills desde URLs, GitHub repos, hubs especializados (awesome-opencode, etc.).
- **4 schemas YAML nuevos**: `code-index`, `evidence-score`, `impact-prediction`, `impl-scaffold`.
- **Integración TS** (5 archivos modificados, sin romper existentes):
  - `evidence-collector.ts` invoca `index_codebase` + `score_evidence` automáticamente tras recolectar.
  - `plan-generator.ts` invoca `predict_impact` automáticamente tras generar plan.
  - `test-runner.ts` invoca `scaffold_impl` antes de tests si hay `unit_id`.
  - `tool-absorber.ts` añade `hotReloadRegistry()` y `recommendTool()`.
  - `index.ts` expone 3 tools nuevas: `apolo.context.query`, `apolo.registry.recommend`, `apolo.health.check`.
- **3 tests TypeScript nuevos** (ContextQueryTools): total 35 tests TS + 42 asserts Python = 77 verificaciones.
- **`package.json`** — v2.2.0.
- **`install.sh`** — `EXPECTED_FILES` ampliada a 76 entradas.
- **Absorción externa**: el sistema ahora puede absorber skills de URLs externas, GitHub repos y hubs especializados, no solo locales.

### v2.1.0

- **6 módulos TypeScript nuevos** en `plugin/core/`, `plugin/absorbers/`, `plugin/parallel/`:
  - `runtime-logger.ts` — Log JSON Lines con seq monotónico, pasivo
  - `router.ts` — Router declarativo (carga `routing-rules.json`)
  - `loop-engine-tree.ts` — Árbol de decisión D-NNN + circuit breaker por patrón
  - `micro-test-runner.ts` — Runner de micro-tests (MPs)
  - `mcp-loader.ts` — Absorbedor de MCPs con fallback
  - `hypothesis-runner.ts` — Paralelizador de hipótesis
- **4 JSON schemas estrictos** en `schemas/json/` (draft-07, `additionalProperties: false`):
  - `agent-io.json` — Contrato inputs/outputs de agents
  - `loop-engine-decision.json` — Nodo del árbol de decisión
  - `routing-rules.json` — Reglas de routing declarativo
  - `runtime-audit-log.json` — Entrada del log de auditoría
- **`routing-rules.json`** — 10 reglas declarativas (R-001..R-010) editables sin tocar código
- **`tests/plugin.test.ts`** — 32 tests reales ejecutables con `node --test`
- **`package.json`** — v2.1.0, scripts `test:all`, `test:python`, `clean`
- **`tsconfig.json`** — incluye `tests/**/*.ts` en compilación
- **`install.sh`** — 7 pasos (añade paso 7: tests TypeScript con `node --test`)

### v2.0.0

- Release inicial con 12 módulos TypeScript, 7 schemas YAML, 5 templates, 10 scripts Python, 5 suites Python, panel HTML, CLI `apolo-inspect.sh`, `install.sh`.

---

## Licencia

MIT

---

## Contribuir

1. Fork el repo
2. Crear branch: `git checkout -b feature/mi-feature`
3. Commit: `git commit -m 'Add mi-feature'`
4. Push: `git push origin feature/mi-feature`
5. Pull request

### Antes de hacer PR

```bash
python3 tests/run_all_tests.py
npx tsc && node --test dist/tests/plugin.test.js
npx tsc --noEmit
```

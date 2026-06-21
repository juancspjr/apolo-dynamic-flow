# APOLO Dynamic Flow

> **Plugin de orquestacion de agentes para OpenCode** con flujos dinamicos, recoleccion determinista de evidencia, planes generados por Python, tests automaticos tras cada cambio y absorcion de tools externas (MCPs, skills, plugins, scripts).

[![Tests](https://img.shields.io/badge/tests-37%2F37%20passing-brightgreen)](#10-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)
[![Version](https://img.shields.io/badge/version-2.1.0-blue)](#changelog)

---

## Tabla de contenidos

1. Que es este plugin
2. Prerequisitos
3. Instalacion (3 metodos)
4. Verificacion de la instalacion
5. Integracion con OpenCode
6. Estructura completa del plugin
7. Uso del CLI apolo-inspect.sh
8. Panel de telemetria
9. Configuracion avanzada
10. Tests
11. Troubleshooting
12. Como funciona internamente
13. Documentacion adicional
14. Changelog
15. Licencia

---

## 1. Que es este plugin

`apolo-dynamic-flow` es un plugin TypeScript para OpenCode que Orquesta agentes con:

- **State machine explicita** con transiciones legales y gates por fase (no "planificacion libre").
- **Loop dinamico con circuit breaker adaptativo** - cada fase tiene `max` iteraciones; al agotarse, escala o bloquea (sin loops infinitos).
- **Recoleccion determinista de evidencia** - scripts Python (no el agente) capturan archivos, git diff, simbolos, endpoints, DB queries, screenshots. Producen `EVIDENCE-PACK.yaml` con hash chain.
- **Planes generados por Python** - `generate_plan.py` lee evidence + verdad y produce `DYNAMIC-PLAN.yaml` con topological sort y adaptative gates.
- **Tests automaticos tras cada cambio** - `run_tests.py` se ejecuta tras micro-cambios. Si falla y el cambio fue micro, rollback automatico via `git restore`.
- **Absorcion automatica de tools externas** - descubre MCPs en `opencode.json`, skills en `.opencode/skills/`, plugins en `.opencode/plugin/`, scripts en `scripts/python/`. Verifica salud y registra en `TOOL-REGISTRY.yaml`.
- **Telemetria append-only** + panel HTML para visualizacion en tiempo real.
- **Routing declarativo** - `routing-rules.json` con 10 reglas editables sin tocar codigo TS.
- **Arbol de decision D-NNN** - reemplaza "plan tras plan" por arbol finito con circuit breaker por patron de fallos.
- **Tests TypeScript ejecutables** - 32 tests con `node --test` que validan modulos reales del plugin.

### Problemas que resuelve (vs. plugin viejo)

| Problema | apolo-flow-guardian.ts | apolo-dynamic-flow |
|---|---|---|
| Planes estaticos | Si, no se adaptaban | Planes dinamicos con versionado y adaptative gates |
| Loop infinito "plan tras plan" | Si | Circuit breaker por fase + arbol de decision D-NNN |
| Recoleccion de evidencia | Agente piensa | Scripts Python deterministas |
| Tests tras cambios | No | Automaticos con rollback |
| MCPs absorbidos | No, solo declarados | Auto-descubrimiento + health check + fallback |
| Telemetria | self-audit.log pasivo | telemetry.jsonl + panel HTML + runtime-audit.log |
| Tests del propio plugin | 0 | 5 suites Python + 32 tests TypeScript |
| Routing | Logica opaca en Python | Routing declarativo editable (routing-rules.json) |

---

## 2. Prerequisitos

### Versiones minimas

| Herramienta | Version minima | Verificar | Instalar en Ubuntu |
|---|---|---|---|
| **Node.js** | 18.0.0 | `node --version` | `sudo apt install -y nodejs` |
| **npm** | 9.0.0 | `npm --version` | `sudo apt install -y npm` |
| **Python 3** | 3.10 | `python3 --version` | `sudo apt install -y python3` |
| **curl** | cualquiera | `curl --version` | `sudo apt install -y curl` |
| **git** | cualquiera | `git --version` | `sudo apt install -y git` |

### Dependencias opcionales (recomendadas)

| Paquete | Para que | Instalar |
|---|---|---|
| **PyYAML** | Parser YAML robusto (reemplaza el minimalista) | `pip3 install --user PyYAML` |
| **jsonschema** | Validacion completa de schemas | `pip3 install --user jsonschema` |
| **playwright** | Capturas de pantalla para evidence pack | `npx playwright install chromium` |
| **pytest** | Runner de tests Python del proyecto destino | `pip3 install --user pytest` |

> **Sin estas dependencias opcionales el plugin funciona**, pero con capacidades reducidas. El `install.sh` las instala automaticamente si `pip3` esta disponible.

### Verificar prerequisitos en un comando

```bash
echo "Node: $(node --version 2>/dev/null || echo FALTA)"
echo "npm:  $(npm --version 2>/dev/null || echo FALTA)"
echo "Py:   $(python3 --version 2>/dev/null || echo FALTA)"
echo "curl: $(curl --version 2>/dev/null | head -1 || echo FALTA)"
echo "git:  $(git --version 2>/dev/null || echo FALTA)"
```

## 3. Instalacion (3 metodos)
Metodo A - Clonar repo y correr install.sh (recomendado)
```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
```

El script install.sh hace todo automaticamente en 7 pasos:

    Verifica prerequisitos (node, npm, python3, curl, git)
    Valida que los archivos del plugin esten presentes
    Crea carpetas runtime (.opencode/apolo-dynamic/, plan/active/)
    Instala dependencias npm (typescript, @types/node)
    Instala dependencias Python opcionales (PyYAML, jsonschema)
    Compila TypeScript a dist/
    Corre los 5 suites Python + los 32 tests TypeScript

Salida esperada: INSTALACION COMPLETA - apolo-dynamic-flow v2.1.0
Metodo B - Instalacion manual paso a paso
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

Metodo C - Solo verificar (sin instalar)
```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh --check
```

Opciones de install.sh
```bash
./install.sh                  # instalacion completa
./install.sh --check          # solo verificar prerequisitos
./install.sh --tests          # solo correr tests
./install.sh --no-npm         # saltar npm install
./install.sh --no-python-deps # saltar pip install
./install.sh -h, --help       # mostrar ayuda
```

## 4. Verificacion de la instalacion

Despues de instalar, verifica que todo funciona:
```bash
# 1. Tests Python deben pasar (5/5 suites, 42 asserts)
python3 tests/run_all_tests.py
# Resultado: "ALL 5 TESTS PASSED"

# 2. Tests TypeScript deben pasar (32 tests)
npx tsc && node --test dist/tests/plugin.test.js
# Resultado: "pass 32 / fail 0"

# 3. TypeScript compila sin errores
npx tsc --noEmit
# Resultado: sin output, exit code 0

# 4. CLI funciona
bash scripts/bash/apolo-inspect.sh help
# Resultado: muestra lista de 12 subcomandos

# 5. Absorber tools del propio plugin
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)
# Resultado: "absorcion completa: N nuevas, N total, M conflictos"

# 6. Ver tools registradas
bash scripts/bash/apolo-inspect.sh tools
# Resultado: tabla con todas las tools y sus capabilities

# 7. Inicializar un flow de prueba
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-$(date +%Y%m%d)-TEST
# Resultado: "Flow inicializado"
```

Si los 7 pasos funcionan, el plugin esta listo para usar.

## 5. Integracion con OpenCode

Para que OpenCode cargue el plugin, edita el opencode.json de tu proyecto destino:
Opcion A - Plugin local (recomendado para desarrollo)
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
    },
    "@koderspa/mcp-skills": {
      "type": "local",
      "command": ["npx", "-y", "@koderspa/mcp-skills@latest"],
      "enabled": true
    }
  }
}
```

> IMPORTANTE: plugin debe ser un array de strings (no un objeto). OpenCode rechaza configs con plugin como objeto.

Verificar integracion con OpenCode
```bash
opencode mcp list
```

Si aparece Error: Configuration is invalid, revisa:

     plugin es un array (no un objeto)
     mcp es un objeto (no un array)
     Todos los JSON son validos: python3 -c "import json; json.load(open('opencode.json'))"

Como el agente OpenCode absorbe este plugin

Cuando OpenCode carga el plugin, el archivo plugin/index.ts expone:

    Hooks (eventos del lifecycle de OpenCode):
         tool:execute:before - bloquea mutaciones si el flow esta en estado blocked
         tool:execute:after - registra telemetria de cada tool invocada
         session:start - absorbe tools automaticamente al iniciar sesion

    Tools (invocables por el orquestador):
         apolo.flow.init - inicializa un flow nuevo
         apolo.flow.tick - ejecuta una iteracion del loop dinamico
         apolo.evidence.collect - dispara recoleccion determinista
         apolo.plan.generate - genera plan dinamico desde evidence
         apolo.tests.run - ejecuta tests tras cambios
         apolo.tools.absorb - descubre y registra tools externas

    Commands (invocables por CLI):
         apolo-inspect - inspector de estado con 12 subcomandos

El orquestador de OpenCode puede usar el plugin en cualquier flujo:
```typescript
await tools["apolo.flow.init"]({ flowid: "APOLO-20260620-MI-FLOW" });

while (!done) {
  const result = await tools["apolo.flow.tick"]({ evidence_pack: true });
  if (result.decision === "block") break;
}

await tools["apolo.evidence.collect"]({
  scope: { paths: ["src/handlers/foo.go"], endpoints: ["/api/v1/foo"] },
  invoked_by: "orchestrator"
});

await tools["apolo.plan.generate"]({
  verdad_path: "plan/active/APOLO-20260620-MI/02-VERDAD.yaml"
});

await tools["apolo.tests.run"]({
  trigger: "micro-change",
  scope: { kind: "unit", targets: ["src/handlers/foo.go"], mp_id: "MP-01" },
  rollback_on_fail: true
});
```

## 6. Estructura completa del plugin
```text
apolo-dynamic-flow/
├── install.sh                          # Instalacion automatica (7 pasos)
├── README.md                           # Este archivo
├── ARCHITECTURE.md                     # Diseno detallado
├── MIGRATION-GUIDE.md                  # Migracion desde apolo-flow-guardian.ts
├── ANALYSIS-REPORT.md                  # Analisis del proyecto viejo
├── opencode.json                       # Config OpenCode
├── package.json                        # v2.1.0
├── tsconfig.json                       # Config TypeScript
├── routing-rules.json                  # Routing declarativo (R-001..R-010)
├── .gitignore
│
├── plugin/                             # 18 modulos TypeScript
│   ├── index.ts, types.ts, state-machine.ts, loop-engine.ts
│   ├── block-detector.ts, evidence-collector.ts, plan-generator.ts
│   ├── test-runner.ts, tool-absorber.ts, telemetry.ts, inspector.ts, utils.ts
│   ├── core/
│   │   ├── runtime-logger.ts           # Log JSON Lines con seq monotono
│   │   ├── router.ts                   # Router declarativo
│   │   ├── loop-engine-tree.ts         # Arbol de decision D-NNN
│   │   └── micro-test-runner.ts        # Runner de micro-tests
│   ├── absorbers/
│   │   └── mcp-loader.ts               # Absorbedor MCP con fallback
│   └── parallel/
│       └── hypothesis-runner.ts        # Paralelizador de hipotesis
│
├── schemas/                            # 11 schemas
│   ├── *.schema.yaml (7)               # Schemas YAML de artefactos
│   └── json/                           # JSON schemas estrictos (draft-07)
│       ├── agent-io.json
│       ├── loop-engine-decision.json
│       ├── routing-rules.json
│       └── runtime-audit-log.json
│
├── templates/                          # 5 templates YAML
├── scripts/
│   ├── python/                         # 10 scripts Python
│   └── bash/apolo-inspect.sh           # CLI (12 subcomandos)
├── panel/                              # Panel de telemetria HTML
└── tests/                              # 6 suites (37 tests totales)
    ├── run_all_tests.py + test_*.py (5)
    └── plugin.test.ts                  # 32 tests TS con node --test
```

Total: 56 archivos (sin contar node_modules, .git, runtime artifacts).
## 7. Uso del CLI apolo-inspect.sh
```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [opciones]
```

Subcomandos
| Subcomando | Descripcion |
|---|---|
| init-flow | Inicializa un flow nuevo |
| absorb | Descubre y registra tools externas |
| state | Estado del flow activo |
| tools | Lista tools absorbidas |
| blocks | Lista bloqueos activos |
| telemetry | Stats de telemetria |
| evidence | Evidence pack actual |
| plan | Plan dinamico actual |
| health | Health check de tools |
| all | Resumen completo |
| serve-panel | Levanta panel HTTP (puerto 8765) |
| test | Corre tests del plugin |
| help | Muestra la ayuda |

Opciones globales
| Opcion | Descripcion | Default |
|---|---|---|
| --flowid FLOW | Flow ID a inspeccionar | Detecta de plan/CURRENT.md |
| --repo-root PATH | Raiz del repo | Directorio actual |
| --json | Output en JSON (cuando aplica) | Off |

Variables de entorno
| Variable | Descripcion | Default |
|---|---|---|
| PYTHON | Path a python3 | python3 |
| PORT | Puerto para serve-panel | 8765 |

Ejemplos de uso
```bash
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-20260620-MI-FLOW
bash scripts/bash/apolo-inspect.sh state --flowid APOLO-20260620-MI-FLOW
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
bash scripts/bash/apolo-inspect.sh all --flowid APOLO-20260620-MI-FLOW
```

## 8. Panel de telemetria
```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
# Abrir http://localhost:8765/
```

Tabs del panel
| Tab | Contenido |
|---|---|
| Overview | Estado del flow, metricas globales |
| Timeline | Ultimos 100 eventos de telemetria |
| Loops | Contadores current/max por fase con colores |
| Blocks | Lista de bloqueos activos con resolucion sugerida |
| Tests | Ultimos 20 runs de tests |
| Tools | Tabla de tools absorbidas |
| Tokens | Total de tokens consumidos |

Cambiar el puerto
```bash
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
```

Auto-refresh cada 5 segundos.

## 9. Configuracion avanzada
Circuit breaker

En templates/FLOW-STATE.template.yaml:
```yaml
loops:
  reanclaje: { current: 0, max: 2, last_decision: "" }
  implementation: { current: 0, max: 4, last_decision: "" }
circuit_breaker:
  policy: fail-closed   # fail-closed | fail-open-adaptive
  escalation_path: []
```

Politicas:

     fail-closed (default): al agotar max, bloquea el flow.
     fail-open-adaptive: al agotar max, escala a escalation_path[0].

Routing declarativo

Edita routing-rules.json para cambiar que agent se invoca en cada fase. 10 reglas (R-001..R-010):
```json
{
  "id": "R-001",
  "priority": 10,
  "when": { "phase": "reanclaje", "artifacts_absent": ["00-OBJETIVO.yaml"] },
  "then": { "next_agent": "planner", "reason": "No hay objetivo." }
}
```

Validar schema
```bash
python3 scripts/python/validate_artifact.py   --artifact routing-rules.json   --schema schemas/json/routing-rules.json
```

Exit codes: 0 = valido, 1 = invalido, 2 = error.
Agregar MCPs externos

Edita opencode.json y agrega entradas en mcp:
```json
{
  "mcp": {
    "mi-mcp-personalizado": {
      "type": "local",
      "command": ["npx", "-y", "mi-mcp@latest"],
      "enabled": true
    }
  }
}
```

Despues re-absorber: bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)

## 10. Tests

El plugin tiene 37 tests en 2 categorias.
Correr todos los tests
```bash
# Tests Python (5 suites, 42 asserts)
python3 tests/run_all_tests.py

# Tests TypeScript (32 tests ejecutables)
npx tsc && node --test dist/tests/plugin.test.js

# Ambos con npm
npm run test:all
```

Suites Python (5)
| Suite | Que valida | # asserts |
|---|---|---|
| test_state_machine.py | FSM: transiciones legales, gates | 6 |
| test_loop_engine.py | Loop dinamico, circuit breaker | 8 |
| test_block_detector.py | Deteccion de bloqueos | 7 |
| test_tool_absorber.py | Absorcion de tools externas | 10 |
| test_python_scripts.py | Scripts Python (YAML, hash, generate_plan) | 11 |

Suite TypeScript (32 tests ejecutables)

tests/plugin.test.ts valida modulos reales del plugin con node --test:
| Describe block | Tests | Que valida |
|---|---|---|
| RuntimeLogger | 4 | log JSON Lines, seq monotono, createFlowLogger, pasivo |
| DeclarativeRouter | 5 | routing-rules.json, R-001/R-002/R-008/R-010, fallback |
| LoopEngineTree | 6 | D-001, advance, detectCircuitBreaker |
| MicroTestRunner | 4 | extractTestCommand, runTest |
| McpAbsorber | 7 | detectAvailableMcps, invokeMcp con fallback |
| ParallelHypothesisRunner | 5 | planHypotheses, selectWinner, scoreHypothesis |

Total: 32 tests TS + 42 asserts Python = 74 verificaciones
Tests durante desarrollo
```bash
python3 tests/run_all_tests.py
npx tsc --noEmit && python3 tests/run_all_tests.py
npm run test:all
```

## 11. Troubleshooting
Error: Configuration is invalid at opencode.json

plugin debe ser array, no objeto:
```json
// Incorrecto
"plugin": { "apolo-dynamic-flow": "./plugin/index.ts" }

// Correcto
"plugin": [ "./plugin/index.ts" ]
```

OSError: Address already in use
```bash
fuser -k 8765/tcp
# o usar otro puerto
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel ...
```

Panel devuelve 404

Las rutas en panel/panel.js deben empezar con /:
```javascript
API.statePath = `/plan/active/${flowid}/FLOW-STATE.yaml`;
```

MCPs aparecen como failed

Algunos paquetes npm no existen. Deshabilitar en opencode.json con "enabled": false.
Tests fallan despues de modificar common.py

Instalar PyYAML y reemplazar las funciones en common.py:
```bash
pip3 install --user PyYAML
```

```python
import yaml
def yaml_load(text): return yaml.safe_load(text)
def yaml_dump(obj): return yaml.safe_dump(obj, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

routing-rules.json duplicado al descargar

Hay dos archivos: uno es el de reglas (va en la raiz) y otro es el schema JSON (va en schemas/json/).
```bash
head -c 100 routing-rules.json  # si dice "json-schema.org" es el schema
```

## 12. Como funciona internamente
State machine de fases
```text
reanclaje -> planning-bootstrap -> asr -> verdad -> shaping -> plan-indice
                                                                |
                            cierre-flow <- critical-validation <- mp-validation <- implementation
```

Cada transicion requiere:

    from y to validos (tabla TRANSITIONS en state-machine.ts)
    Gate evaluado antes de transitar (G-REANCLAJE, G-BOOTSTRAP, etc.)
    Artefactos requeridos presentes en state.artifacts

Loop dinamico con circuit breaker
```text
tick() ->
  1. Identificar gate de la fase actual
  2. Evaluar gate con estado + evidence
  3. Actuar segun decision:
     - pass     -> transitar a siguiente fase (reset counter)
     - refine   -> counter++ (si < max, reintentar)
     - escalate -> transitar a escalation_path[0]
     - block    -> transitar a 'blocked' + crear BLOQUEO
  4. Persistir state + emitir telemetria
  5. Detectar bloqueos activos (plan cycles, context overload)
```

Recoleccion determinista de evidencia
```text
apolo.evidence.collect({ scope: {...} })
        |
        v
collect_evidence.py (Python)
        |
        v
- File snapshots (hash SHA256)
- Git diff / git log
- Symbol extraction (Go/TS/Python)
- Endpoint probes (curl)
- DB queries (psql)
- Screenshots (playwright si disponible)
- Schema validation
        |
        v
EVIDENCE-PACK.yaml (con hash_chain + capabilities + degradation_log)
```

Routing declarativo
```text
route(ctx) -> load routing-rules.json
           -> ordenar por prioridad (1 = maxima)
           -> primera regla que matchea
           -> next_agent + reason + circuit_breaker
           -> log al runtime-audit.log
```

Arbol de decision D-NNN
```text
createRootNode(D-001) con 5 branches:
  - test_passes -> advance_phase (terminal)
  - test_fails_retriable -> retry_mp (crea D-002)
  - test_fails_terminal -> raise_blocker (terminal)
  - blocker_persists -> ask_operator (terminal)
  - iteration_exceeded -> circuit_break (terminal)

advance(D-001, condition) -> branch -> si next_node="AUTO", crear D-002

detectCircuitBreaker: 3 fallos misma razon -> true
```

Tests automaticos con rollback
```text
implementer edita archivo
        |
        v
apolo.tests.run({ trigger: "micro-change" })
        |
        v
run_tests.py:
  1. Descubre tests relacionados (pytest/go test/jest)
  2. Ejecuta tests
  3. Parse output (status: pass/fail/skip)
  4. Escribe TEST-RUN.yaml
        |
        v
Si failed && trigger == "micro-change":
  rollback.py:
    - git restore <archivos afectados>
    - Reporta archivos restaurados
```

Absorcion de tools externas
```text
apolo.tools.absorb()
        |
        v
tool-absorber.ts escanea:
  - opencode.json#mcp.* -> registra cada MCP
  - .opencode/skills/*/SKILL.md -> registra cada skill
  - .opencode/plugin/*.ts -> registra cada plugin TS
  - scripts/python/*.py -> registra cada script Python
        |
        v
Para cada tool:
  1. Infiere capabilities por nombre
  2. Verifica salud (test -f para scripts, skip para MCPs externos)
  3. Construye fallback chain
  4. Detecta conflicts (mismas capabilities)
        |
        v
TOOL-REGISTRY.yaml (centralizado)
```

## 13. Documentacion adicional
| Archivo | Contenido |
|---|---|
| ARCHITECTURE.md | Diseno detallado, decisiones tecnicas, diagramas de componentes |
| MIGRATION-GUIDE.md | Migracion desde apolo-flow-guardian.ts paso a paso |
| ANALYSIS-REPORT.md | Analisis del proyecto viejo + justificacion del nuevo |

## 14. Changelog
v2.1.0

     6 modulos TypeScript nuevos en plugin/core/, plugin/absorbers/, plugin/parallel/:
         runtime-logger.ts - Log JSON Lines con seq monotono, pasivo
         router.ts - Router declarativo (carga routing-rules.json)
         loop-engine-tree.ts - Arbol de decision D-NNN + circuit breaker por patron
         micro-test-runner.ts - Runner de micro-tests (MPs)
         mcp-loader.ts - Absorbedor de MCPs con fallback
         hypothesis-runner.ts - Paralelizador de hipotesis
     4 JSON schemas estrictos en schemas/json/ (draft-07, additionalProperties: false):
         agent-io.json - Contrato inputs/outputs de agents
         loop-engine-decision.json - Nodo del arbol de decision
         routing-rules.json - Reglas de routing declarativo
         runtime-audit-log.json - Entrada del log de auditoria
     routing-rules.json - 10 reglas declarativas (R-001..R-010) editables sin tocar codigo
     tests/plugin.test.ts - 32 tests reales ejecutables con node --test
     package.json - v2.1.0, scripts test:all, test:python, clean
     tsconfig.json - incluye tests/**/*.ts en compilacion
     install.sh - 7 pasos (añade paso 7: tests TypeScript con node --test)
     README.md - documenta tests TS, schemas JSON, routing declarativo

v2.0.0

     Release inicial con 12 modulos TypeScript, 7 schemas YAML, 5 templates, 10 scripts Python, 5 suites Python, panel HTML, CLI apolo-inspect.sh, install.sh.

## 15. Licencia

MIT
Contribuir

    Fork el repo
    Crear branch: git checkout -b feature/mi-feature
    Commit: git commit -m 'Add mi-feature'
    Push: git push origin feature/mi-feature
    Pull request

Antes de hacer PR
```bash
python3 tests/run_all_tests.py
npx tsc && node --test dist/tests/plugin.test.js
npx tsc --noEmit
```


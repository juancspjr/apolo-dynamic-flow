# APOLO Dynamic Flow

> **Plugin de orquestación de agentes para OpenCode** con flujos dinámicos, recolección determinista de evidencia, planes generados por Python, tests automáticos tras cada cambio y absorción de tools externas (MCPs, skills, plugins, scripts).

[![Tests](https://img.shields.io/badge/tests-5%2F5%20passing-brightgreen)](tests/)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)

---

## Tabla de contenidos

1. [Qué es este plugin](#1-qué-es-este-plugin)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Instalación (3 métodos)](#3-instalación-3-métodos)
4. [Verificación de la instalación](#4-verificación-de-la-instalación)
5. [Integración con OpenCode](#5-integración-con-opencode)
6. [Estructura completa del plugin](#6-estructura-completa-del-plugin)
7. [Uso del CLI `apolo-inspect.sh`](#7-uso-del-cli-apolo-inspectsh)
8. [Panel de telemetría](#8-panel-de-telemetría)
9. [Configuración avanzada](#9-configuración-avanzada)
10. [Tests](#10-tests)
11. [Troubleshooting](#11-troubleshooting)
12. [Cómo funciona internamente](#12-cómo-funciona-internamente)
13. [Documentación adicional](#13-documentación-adicional)
14. [Licencia](#licencia)

---

## 1. Qué es este plugin

`apolo-dynamic-flow` es un plugin TypeScript para OpenCode que **reemplaza a `apolo-flow-guardian.ts`**. Orquesta agentes con:

- **State machine explícita** con transiciones legales y gates por fase (no "planificación libre").
- **Loop dinámico con circuit breaker adaptativo** — cada fase tiene `max` iteraciones; al agotarse, escala o bloquea (sin loops infinitos).
- **Recolección determinista de evidencia** — scripts Python (no el agente) capturan archivos, git diff, símbolos, endpoints, DB queries, screenshots. Producen `EVIDENCE-PACK.yaml` con hash chain.
- **Planes generados por Python** — `generate_plan.py` lee evidence + verdad y produce `DYNAMIC-PLAN.yaml` con topological sort y adaptative gates.
- **Tests automáticos tras cada cambio** — `run_tests.py` se ejecuta tras micro-cambios. Si falla y el cambio fue micro → rollback automático vía `git restore`.
- **Absorción automática de tools externas** — descubre MCPs en `opencode.json`, skills en `.opencode/skills/`, plugins en `.opencode/plugin/`, scripts en `scripts/python/`. Verifica salud y registra en `TOOL-REGISTRY.yaml`.
- **Telemetría append-only** + panel HTML para visualización en tiempo real.

### Problemas que resuelve (vs. plugin viejo)

| Problema | apolo-flow-guardian.ts | apolo-dynamic-flow |
|---|---|---|
| Planes estáticos | Sí, no se adaptaban | Planes dinámicos con versionado y adaptative gates |
| Loop infinito "plan tras plan" | Sí | Circuit breaker por fase |
| Recolección de evidencia | Agente piensa | Scripts Python deterministas |
| Tests tras cambios | No | Automáticos con rollback |
| MCPs absorbidos | No, solo declarados | Auto-descubrimiento + health check |
| Telemetría | self-audit.log pasivo | telemetry.jsonl + panel HTML |
| Tests del propio plugin | 0 | 5 suites, todas pasan |

---

## 2. Prerrequisitos

### Versiones mínimas

| Herramienta | Versión mínima | Verificar | Instalar en Ubuntu |
|---|---|---|---|
| **Node.js** | 18.0.0 | `node --version` | `sudo apt install -y nodejs` |
| **npm** | 9.0.0 | `npm --version` | `sudo apt install -y npm` |
| **Python 3** | 3.10 | `python3 --version` | `sudo apt install -y python3` |
| **curl** | cualquiera | `curl --version` | `sudo apt install -y curl` |
| **git** | cualquiera | `git --version` | `sudo apt install -y git` |

### Dependencias opcionales (recomendadas)

| Paquete | Para qué | Instalar |
|---|---|---|
| **PyYAML** | Parser YAML robusto (reemplaza el minimalista) | `pip3 install --user PyYAML` |
| **jsonschema** | Validación completa de schemas | `pip3 install --user jsonschema` |
| **playwright** | Capturas de pantalla para evidence pack | `npx playwright install chromium` |
| **pytest** | Runner de tests Python del proyecto destino | `pip3 install --user pytest` |

> **Sin estas dependencias opcionales el plugin funciona**, pero con capacidades reducidas. El `install.sh` las instala automáticamente si `pip3` está disponible.

### Verificar prerrequisitos en un comando

```bash
echo "Node: $(node --version 2>/dev/null || echo 'FALTA')"
echo "npm:  $(npm --version 2>/dev/null || echo 'FALTA')"
echo "Py:   $(python3 --version 2>/dev/null || echo 'FALTA')"
echo "curl: $(curl --version 2>/dev/null | head -1 || echo 'FALTA')"
echo "git:  $(git --version 2>/dev/null || echo 'FALTA')"
```

---

## 3. Instalación (3 métodos)

### Método A — Clonar repo y correr `install.sh` (recomendado)

```bash
# 1. Clonar el repo
git clone https://github.com/tu-usuario/apolo-dynamic-flow.git
cd apolo-dynamic-flow

# 2. Ejecutar install.sh
./install.sh
```

El script `install.sh` hace todo automáticamente:
1. Verifica prerrequisitos (node, npm, python3, curl, git)
2. Valida que los 49 archivos del plugin estén presentes
3. Crea carpetas runtime (`.opencode/apolo-dynamic/`, `plan/active/`)
4. Instala dependencias npm (`typescript`, `@types/node`)
5. Instala dependencias Python opcionales (`PyYAML`, `jsonschema`)
6. Verifica que TypeScript compila sin errores
7. Corre los 5 suites de tests

**Salida esperada**: `✅ INSTALACIÓN COMPLETA — apolo-dynamic-flow v2.0.0`

### Método B — Instalación manual paso a paso

Si prefieres controlar cada paso:

```bash
# 1. Clonar
git clone https://github.com/tu-usuario/apolo-dynamic-flow.git
cd apolo-dynamic-flow

# 2. Crear carpetas runtime
mkdir -p .opencode/apolo-dynamic/screenshots
mkdir -p plan/active

# 3. Instalar dependencias npm
npm install

# 4. (Opcional) Instalar dependencias Python
pip3 install --user PyYAML jsonschema

# 5. Verificar TypeScript compila
npx tsc --noEmit

# 6. Correr tests
python3 tests/run_all_tests.py
```

### Método C — Solo verificar (sin instalar)

```bash
git clone https://github.com/tu-usuario/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh --check
```

Solo verifica prerrequisitos y estructura de archivos. No instala nada.

### Opciones de `install.sh`

```bash
./install.sh                          # instalación completa
./install.sh --check                  # solo verificar prerrequisitos
./install.sh --tests                  # solo correr tests
./install.sh --no-npm                 # saltar npm install
./install.sh --no-python-deps         # saltar pip install
./install.sh -h, --help               # mostrar ayuda
```

---

## 4. Verificación de la instalación

Después de instalar, verifica que todo funciona:

```bash
# 1. Tests deben pasar (5/5)
python3 tests/run_all_tests.py
# → "ALL 5 TESTS PASSED ✓"

# 2. TypeScript compila sin errores
npx tsc --noEmit
# → (sin output, exit code 0)

# 3. CLI funciona
bash scripts/bash/apolo-inspect.sh help
# → muestra lista de 12 subcomandos

# 4. Absorber tools del propio plugin
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)
# → "absorción completa: N nuevas, N total, M conflictos"

# 5. Ver tools registradas
bash scripts/bash/apolo-inspect.sh tools
# → tabla con todas las tools y sus capabilities

# 6. Inicializar un flow de prueba
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-$(date +%Y%m%d)-TEST
# → "✅ Flow inicializado"

# 7. Ver estado del flow
bash scripts/bash/apolo-inspect.sh state --flowid APOLO-$(date +%Y%m%d)-TEST
# → muestra fase, loops, artifacts
```

Si los 7 pasos funcionan, el plugin está listo para usar.

---

## 5. Integración con OpenCode

Para que OpenCode cargue el plugin, edita el `opencode.json` de tu proyecto destino:

### Opción A — Plugin local (recomendado para desarrollo)

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

> **IMPORTANTE**: `plugin` debe ser un **array** de strings (no un objeto). OpenCode rechaza configs con `plugin` como objeto.

### Opción B — Plugin instalado como dependencia npm

Si publicas el plugin en npm:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "apolo-dynamic-flow"
  ]
}
```

### Opción C — Múltiples plugins

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    "./apolo-dynamic-flow/plugin/index.ts",
    "./otros-plugins/mi-plugin.ts"
  ]
}
```

### Verificar integración con OpenCode

```bash
# Debe listar los MCPs sin error de configuración
opencode mcp list
```

Si aparece `Error: Configuration is invalid`, revisa:
- `plugin` es un array (no un objeto)
- `mcp` es un objeto (no un array)
- Todos los JSON son válidos: `python3 -c "import json; json.load(open('opencode.json'))"`

### Cómo el agente OpenCode absorbe este plugin

Cuando OpenCode carga el plugin, el archivo `plugin/index.ts` expone:

1. **Hooks** (eventos del lifecycle de OpenCode):
   - `tool:execute:before` — bloquea mutaciones si el flow está en estado `blocked`
   - `tool:execute:after` — registra telemetría de cada tool invocada
   - `session:start` — absorbe tools automáticamente al iniciar sesión

2. **Tools** (invocables por el orquestador):
   - `apolo.flow.init` — inicializa un flow nuevo
   - `apolo.flow.tick` — ejecuta una iteración del loop dinámico
   - `apolo.evidence.collect` — dispara recolección determinista
   - `apolo.plan.generate` — genera plan dinámico desde evidence
   - `apolo.tests.run` — ejecuta tests tras cambios
   - `apolo.tools.absorb` — descubre y registra tools externas

3. **Commands** (invocables por CLI):
   - `apolo-inspect` — inspector de estado con 12 subcomandos

El orquestador de OpenCode puede usar el plugin en cualquier flujo:

```typescript
// Inicializar un flow
await tools["apolo.flow.init"]({ flowid: "APOLO-20260620-MI-FLOW" });

// Loop principal: tick repetido
while (!done) {
  const result = await tools["apolo.flow.tick"]({ evidence_pack: true });
  if (result.decision === "block") break;
}

// Recolectar evidencia determinista
await tools["apolo.evidence.collect"]({
  scope: { paths: ["src/handlers/foo.go"], endpoints: ["/api/v1/foo"] },
  invoked_by: "orchestrator"
});

// Generar plan dinámico
await tools["apolo.plan.generate"]({
  verdad_path: "plan/active/APOLO-20260620-MI/02-VERDAD.yaml"
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
├── install.sh                          # ← Instalación automática
├── README.md                           # ← Este archivo
├── ARCHITECTURE.md                     # Diseño detallado
├── MIGRATION-GUIDE.md                  # Migración desde apolo-flow-guardian.ts
├── ANALYSIS-REPORT.md                  # Análisis del proyecto viejo + justificación
├── opencode.json                       # Config OpenCode (plugin + MCPs)
├── package.json                        # Dependencias npm (typescript, @types/node)
├── tsconfig.json                       # Config TypeScript
├── .gitignore
│
├── plugin/                             # 12 módulos TypeScript (~3,300 líneas)
│   ├── index.ts                        # Entry point: hooks, tools, commands
│   ├── types.ts                        # Tipos compartidos
│   ├── state-machine.ts                # FSM de fases + gates
│   ├── loop-engine.ts                  # Loop dinámico + circuit breaker
│   ├── block-detector.ts               # Detección activa de bloqueos
│   ├── evidence-collector.ts           # Wrapper TS → collect_evidence.py
│   ├── plan-generator.ts               # Wrapper TS → generate_plan.py
│   ├── test-runner.ts                  # Wrapper TS → run_tests.py + rollback
│   ├── tool-absorber.ts                # Descubrimiento + registro de tools
│   ├── telemetry.ts                    # Eventos append-only
│   ├── inspector.ts                    # CLI de inspección
│   └── utils.ts                        # YAML, hash, fs, time
│
├── schemas/                            # 7 schemas YAML
│   ├── flow-state.schema.yaml          # Estado persistido del flow
│   ├── dynamic-plan.schema.yaml        # Plan dinámico con versionado
│   ├── evidence-pack.schema.yaml       # Evidencia recopilada
│   ├── test-result.schema.yaml         # Resultado de tests
│   ├── tool-registry.schema.yaml       # Registro de tools absorbidas
│   ├── telemetry-event.schema.yaml     # Evento individual de telemetría
│   └── block-log.schema.yaml           # Log de bloqueos
│
├── templates/                          # 5 templates YAML
│   ├── FLOW-STATE.template.yaml
│   ├── DYNAMIC-PLAN.template.yaml
│   ├── EVIDENCE-PACK.template.yaml
│   ├── TEST-RUN.template.yaml
│   └── BLOCK-LOG.template.yaml
│
├── scripts/
│   ├── python/                         # 10 scripts Python (~2,600 líneas)
│   │   ├── common.py                   # Utilidades (YAML, hash, git, paths)
│   │   ├── collect_evidence.py         # Recolector determinista
│   │   ├── generate_plan.py            # Generador de planes dinámicos
│   │   ├── run_tests.py                # Runner de tests
│   │   ├── absorb_mcp.py               # Absorción de tools externas
│   │   ├── validate_artifact.py        # Validador YAML vs schema
│   │   ├── telemetry_aggregator.py     # Agregador de eventos
│   │   ├── inspect_tools.py            # Inspección de TOOL-REGISTRY
│   │   ├── rollback.py                 # Rollback tras test fail
│   │   └── serve_panel.py              # Servidor HTTP del panel
│   └── bash/
│       └── apolo-inspect.sh            # CLI de inspección (12 subcomandos)
│
├── panel/                              # Panel de telemetría HTML
│   ├── index.html                      # 7 tabs: overview, timeline, loops, blocks, tests, tools, tokens
│   ├── panel.css                       # Estilo dark theme
│   └── panel.js                        # Lógica + YAML parser propio
│
└── tests/                              # 5 suites de tests
    ├── run_all_tests.py                # Runner principal
    ├── test_state_machine.py           # FSM: transiciones y gates
    ├── test_loop_engine.py             # Loop + circuit breaker
    ├── test_block_detector.py          # Detección de bloqueos
    ├── test_tool_absorber.py           # Absorción de tools
    └── test_python_scripts.py          # Scripts Python (YAML, hash, generate_plan, etc.)
```

**Total**: 49 archivos (sin contar `node_modules`, `.git`, runtime artifacts).

---

## 7. Uso del CLI `apolo-inspect.sh`

El CLI `apolo-inspect.sh` es la interfaz principal para inspeccionar y administrar el plugin desde la terminal.

### Sintaxis

```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [opciones]
```

### Subcomandos

| Subcomando | Descripción | Ejemplo |
|---|---|---|
| `init-flow` | Inicializa un flow nuevo | `init-flow --flowid APOLO-20260620-MI` |
| `absorb` | Descubre y registra tools externas | `absorb --repo-root $(pwd)` |
| `state` | Estado del flow activo | `state --flowid APOLO-20260620-MI` |
| `tools` | Lista tools absorbidas y capabilities | `tools` |
| `blocks` | Lista bloqueos activos y resueltos | `blocks --flowid APOLO-20260620-MI` |
| `telemetry` | Stats de telemetría | `telemetry --flowid APOLO-20260620-MI` |
| `evidence` | Evidence pack actual | `evidence --flowid APOLO-20260620-MI` |
| `plan` | Plan dinámico actual | `plan --flowid APOLO-20260620-MI` |
| `health` | Health check de todas las tools | `health` |
| `all` | Resumen completo | `all --flowid APOLO-20260620-MI` |
| `serve-panel` | Levanta panel HTTP (puerto 8765) | `serve-panel --flowid APOLO-20260620-MI` |
| `test` | Corre la suite de 5 tests | `test` |
| `help` | Muestra la ayuda | `help` |

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

### Ejemplos de uso

```bash
# Flujo completo de un nuevo flow
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-$(date +%Y%m%d)-MI-FLOW
bash scripts/bash/apolo-inspect.sh state --flowid APOLO-$(date +%Y%m%d)-MI-FLOW
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-$(date +%Y%m%d)-MI-FLOW

# Inspección completa
bash scripts/bash/apolo-inspect.sh all --flowid APOLO-20260620-MI-FLOW

# Output en JSON para scripts
bash scripts/bash/apolo-inspect.sh tools --json
bash scripts/bash/apolo-inspect.sh state --flowid APOLO-20260620-MI-FLOW --json
```

---

## 8. Panel de telemetría

El panel HTML muestra en tiempo real el estado del flow, eventos de telemetría, loops por fase, bloqueos activos, tests, tools absorbidas y consumo de tokens.

### Levantar el panel

```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
```

Salida:

```
Panel disponible en:
  http://localhost:8765/?repo=/home/juan/new_project&flowid=APOLO-20260620-MI-FLOW
Sirviendo desde: /home/juan/new_project
Ctrl+C para detener.
```

Abre **http://localhost:8765/** en el navegador.

### Tabs del panel

| Tab | Contenido |
|---|---|
| **Overview** | Estado del flow, métricas globales, distribuciones por fase y kind |
| **Timeline** | Últimos 100 eventos de telemetría (at, kind, phase, severity, message) |
| **Loops** | Contadores `current/max` por fase con colores (verde/amarillo/rojo) |
| **Blocks** | Lista de bloqueos activos con severidad y resolución sugerida |
| **Tests** | Últimos 20 runs de tests con summary y rollback triggered |
| **Tools** | Tabla de tools absorbidas (status, ID, kind, capabilities) |
| **Tokens** | Total de tokens consumidos y promedio por evento |

### Cambiar el puerto

El puerto default es **8765** (poco común para evitar conflictos). Para cambiarlo:

```bash
# Variable de entorno
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW

# Permanentemente: editar scripts/bash/apolo-inspect.sh y cambiar
# PORT="${PORT:-8765}" por PORT="${PORT:-TU_PUERTO}"
```

### Auto-refresh

El panel consulta los datos cada 5 segundos automáticamente. No necesitas refrescar manualmente.

---

## 9. Configuración avanzada

### Circuit breaker

El circuit breaker controla cuántas iteraciones puede pasar en cada fase antes de escalar o bloquear. Configuración default (en `templates/FLOW-STATE.template.yaml`):

```yaml
loops:
  reanclaje:           { current: 0, max: 2, last_decision: "" }
  planning-bootstrap:  { current: 0, max: 2, last_decision: "" }
  asr:                 { current: 0, max: 2, last_decision: "" }
  verdad:              { current: 0, max: 2, last_decision: "" }
  shaping:             { current: 0, max: 2, last_decision: "" }
  plan-indice:         { current: 0, max: 2, last_decision: "" }
  mp-validation:       { current: 0, max: 2, last_decision: "" }
  implementation:      { current: 0, max: 4, last_decision: "" }
  critical-validation: { current: 0, max: 2, last_decision: "" }

circuit_breaker:
  policy: fail-closed   # fail-closed | fail-open-adaptive
  escalation_path: []   # fases a escalar antes de bloquear
```

**Políticas**:
- `fail-closed` (default): al agotar `max`, bloquea el flow y espera intervención.
- `fail-open-adaptive`: al agotar `max`, escala a `escalation_path[0]` si está definido.

### Personalizar el circuit breaker

Edita `FLOW-STATE.yaml` del flow específico:

```yaml
loops:
  verdad:
    current: 0
    max: 3  # ← permitir 3 iteraciones en vez de 2
    last_decision: ""
```

### Agregar MCPs externos

Edita `opencode.json` y agrega entradas en `mcp`:

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

Después re-absorber:

```bash
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)
```

### Schemas personalizados

Los 7 schemas viven en `schemas/`. Para validar cualquier YAML contra un schema:

```bash
python3 scripts/python/validate_artifact.py \
  --artifact mi-archivo.yaml \
  --schema schemas/flow-state.schema.yaml
```

Exit codes: `0` = válido, `1` = inválido, `2` = error de ejecución.

---

## 10. Tests

### Correr todos los tests

```bash
python3 tests/run_all_tests.py
```

### Suites disponibles

| Suite | Qué valida | # asserts |
|---|---|---|
| `test_state_machine.py` | FSM: transiciones legales, gates, canTransit, evaluateGate | 6 |
| `test_loop_engine.py` | Loop dinámico, circuit breaker, blockAndStay, telemetría | 8 |
| `test_block_detector.py` | Detección de plan cycles, context overload, operator hints | 7 |
| `test_tool_absorber.py` | Absorción de MCPs/skills/plugins/scripts, conflicts, fallback chains | 10 |
| `test_python_scripts.py` | Scripts Python: YAML round-trip, hash, topological sort, generate_plan, collect_evidence | 11 |

**Total**: 5 suites, 42 asserts, todas pasan ✓

### Salida esperada

```
============================================================
  RUNNING: test_state_machine.py
============================================================
=== test_state_machine.py ===
✓ TRANSITIONS cubre todas las fases forward
✓ Todos los gates están definidos
✓ GateResult estructura presente
✓ aggregate() con prioridad block>escalate>refine>pass
✓ canTransit soporta forward, loop y blocked
✓ ALL_PHASES exportado

All tests passed ✓

[... otras suites ...]

============================================================
  ALL 5 TESTS PASSED ✓
```

### Tests durante desarrollo

Si modificas el plugin, corre los tests después de cada cambio:

```bash
# Tests rápidos (solo Python)
python3 tests/run_all_tests.py

# Tests + typecheck TypeScript
npx tsc --noEmit && python3 tests/run_all_tests.py
```

---

## 11. Troubleshooting

### `Error: Configuration is invalid at opencode.json`

**Causa**: `plugin` está como objeto en vez de array.

**Fix**:

```json
// ❌ Incorrecto
"plugin": { "apolo-dynamic-flow": "./plugin/index.ts" }

// ✅ Correcto
"plugin": [ "./plugin/index.ts" ]
```

### `OSError: [Errno 98] Address already in use`

**Causa**: El puerto 8765 está ocupado por otro proceso.

**Fix**:

```bash
# Ver qué lo ocupa
fuser 8765/tcp

# Matarlo
fuser -k 8765/tcp

# O usar otro puerto
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI
```

### `ModuleNotFoundError: No module named 'inspector'`

**Causa**: Versión vieja de `apolo-inspect.sh` que intenta importar TypeScript desde Python.

**Fix**: El `apolo-inspect.sh` actualizado usa scripts Python nativos. Asegúrate de tener la última versión:

```bash
bash scripts/bash/apolo-inspect.sh help
# debe mostrar 12 subcomandos incluyendo init-flow y absorb
```

### `mv: no se puede efectuar 'stat' sobre 'README.md'`

**Causa**: El navegador añadió sufijos `(1)`, `(2)` a archivos descargados.

**Fix**: Renombrar manualmente:

```bash
cd ~/Descargas
mv "README(1).md" "README.md"
mv "index(1).ts" "index.ts"
# etc.
```

### Panel devuelve 404 para todos los endpoints

**Causa**: `panel.js` está usando rutas relativas en vez de absolutas.

**Fix**: Las rutas en `panel/panel.js` deben empezar con `/`:

```javascript
// ✅ Correcto (absoluto desde server root)
API.statePath = `/plan/active/${flowid}/FLOW-STATE.yaml`;

// ❌ Incorrecto (relativo a /panel/)
API.statePath = `plan/active/${flowid}/FLOW-STATE.yaml`;
```

### MCPs aparecen como `failed` en `opencode mcp list`

**Causa**: Los paquetes npm no existen o no se pueden instalar.

**Fix**: Verificar manualmente:

```bash
npx -y @playwright/mcp@latest --version  # debe funcionar
npx -y opencode-fastedit@latest --version  # si falla, el nombre es incorrecto
```

Si un MCP no existe en npm, deshabilítalo en `opencode.json` con `"enabled": false`.

### Tests fallan después de modificar `common.py`

**Causa**: El parser YAML minimalista es frágil. Cualquier cambio puede romper el round-trip.

**Fix**: Instalar PyYAML y reemplazar las funciones en `common.py`:

```bash
pip3 install --user PyYAML
```

Después editar `scripts/python/common.py`:

```python
import yaml

def yaml_load(text):
    return yaml.safe_load(text)

def yaml_dump(obj):
    return yaml.safe_dump(obj, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

---

## 12. Cómo funciona internamente

### State machine de fases

```
reanclaje → planning-bootstrap → asr → verdad → shaping → plan-indice
                                                                ↓
                            cierre-flow ← critical-validation ← mp-validation ← implementation
```

Cada transición requiere:
1. `from` y `to` válidos (tabla `TRANSITIONS` en `state-machine.ts`)
2. Gate evaluado antes de transitar (`G-REANCLAJE`, `G-BOOTSTRAP`, etc.)
3. Artefactos requeridos presentes en `state.artifacts`

### Loop dinámico con circuit breaker

```
┌─ tick() ──────────────────────────────────────────────────┐
│ 1. Identificar gate de la fase actual                     │
│ 2. Evaluar gate con estado + evidence                    │
│ 3. Actuar según decisión:                                 │
│    ├─ pass     → transitar a siguiente fase (reset counter)│
│    ├─ refine   → counter++ (si < max, reintentar)         │
│    ├─ escalate → transitar a escalation_path[0]           │
│    └─ block    → transitar a 'blocked' + crear BLOQUEO    │
│ 4. Persistir state + emitir telemetría                    │
│ 5. Detectar bloqueos activos (plan cycles, context overload)│
└───────────────────────────────────────────────────────────┘
```

### Recolección determinista de evidencia

```
apolo.evidence.collect({ scope: {...} })
        ↓
collect_evidence.py (Python)
        ↓
┌─ Recolectores ──────────────────────────┐
│ • File snapshots (hash SHA256)          │
│ • Git diff / git log                    │
│ • Symbol extraction (Go/TS/Python)      │
│ • Endpoint probes (curl)                │
│ • DB queries (psql)                     │
│ • Screenshots (playwright si disponible)│
│ • Schema validation                     │
└─────────────────────────────────────────┘
        ↓
EVIDENCE-PACK.yaml (con hash_chain + capabilities + degradation_log)
```

### Generación de planes dinámicos

```
apolo.plan.generate({ verdad_path })
        ↓
generate_plan.py lee:
  • EVIDENCE-PACK.yaml
  • 02-VERDAD.yaml (clusters)
        ↓
Aplica heurísticas:
  • Detectar eje dominante por archivo (handler/service/ui/docs)
  • should_split si mezcla ejes
  • estimate_mps por símbolos acoplados
  • Topological sort (Kahn's algorithm)
        ↓
DYNAMIC-PLAN.yaml con:
  • unidades (id, origenverdad, acoplamientos, fronteraconfianza)
  • topological_sort (orden de ejecución)
  • adaptative_gates (triggers dinámicos)
  • rewrite_history (versionado)
```

### Tests automáticos con rollback

```
implementer edita archivo
        ↓
apolo.tests.run({ trigger: "micro-change" })
        ↓
run_tests.py:
  1. Descubre tests relacionados (pytest/go test/jest)
  2. Ejecuta tests
  3. Parse output (status: pass/fail/skip)
  4. Escribe TEST-RUN.yaml
        ↓
Si failed && trigger == "micro-change":
  rollback.py:
    • git restore <archivos afectados>
    • Reporta archivos restaurados
```

### Absorción de tools externas

```
apolo.tools.absorb()
        ↓
tool-absorber.ts escanea:
  • opencode.json#mcp.* → registra cada MCP
  • .opencode/skills/*/SKILL.md → registra cada skill
  • .opencode/plugin/*.ts → registra cada plugin TS
  • scripts/python/*.py → registra cada script Python
        ↓
Para cada tool:
  1. Infiere capabilities por nombre
  2. Verifica salud (test -f para scripts, skip para MCPs externos)
  3. Construye fallback chain
  4. Detecta conflicts (mismas capabilities)
        ↓
TOOL-REGISTRY.yaml (centralizado)
```

---

## 13. Documentación adicional

| Archivo | Contenido |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Diseño detallado, decisiones técnicas, diagramas de componentes, métricas de mejora vs. plugin viejo |
| [`MIGRATION-GUIDE.md`](MIGRATION-GUIDE.md) | Cómo migrar desde `apolo-flow-guardian.ts` paso a paso (8 pasos + verificación) |
| [`ANALYSIS-REPORT.md`](ANALYSIS-REPORT.md) | Análisis del proyecto viejo (skills, agents, commands, plugins, schemas) + justificación del nuevo + sugerencias |

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
# Tests deben pasar
python3 tests/run_all_tests.py

# TypeScript debe compilar
npx tsc --noEmit

# Si modificaste scripts Python, validar YAML round-trip
python3 -c "
import sys; sys.path.insert(0, 'scripts/python')
from common import yaml_load, yaml_dump
data = {'test': ['a', 'b', {'nested': True}]}
assert yaml_load(yaml_dump(data)) == data
print('YAML round-trip OK')
"
```

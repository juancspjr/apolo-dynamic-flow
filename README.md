# APOLO Dynamic Flow

> **Plugin de orquestacion de agentes para OpenCode** — agnostico al lenguaje (HTML, CSS, JS, React, Rust, C++, PHP, TS, Java, Go). Flujos dinamicos, recoleccion determinista de evidencia, planes generados por Python, tests automaticos tras cada cambio, absorcion de tools externas (MCPs, skills, plugins, scripts), analisis de calidad multi-lenguaje (BFS multi-nivel, code quality, test coverage por simbolo, LSP integration).

[![Tests](https://img.shields.io/badge/tests-179%2F179%20passing-brightgreen)](#10-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#15-licencia)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#2-prerequisitos)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#2-prerequisitos)
[![Version](https://img.shields.io/badge/version-3.5.7-blue)](#14-changelog)

---

## Tabla de contenidos

**Manual de Usuario**
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
11. Calidad del analisis (v3.5.7)
12. Agnostico al lenguaje
13. Troubleshooting

**Manual Tecnico**
14. Como funciona internamente
15. Arquitectura de 3 Capas (v3.3.0)
16. El Orquestador Automatico (v3.2.0)
17. UN Comando en Lenguaje Natural (v3.5.3)
18. CLI Router Unificado (v2.9.0)
19. Super Poderes Integrados (v3.5.0)
20. Validadores del Sistema (v3.5.0)
21. Hooks de OpenCode + Auto-hooks (v2.9.0)
22. Post-script Gates (v2.9.0)
23. Configuracion Centralizada apolo-config (v3.1.0)
24. Scaffold v3 con Auto-select U-NN (v3.1.0)
25. Evidence Visual Diff + Replay + Cross-flow (v3.1.0)
26. Seguridad y Honesty (v3.5.0)
27. Capability Assessment (v3.5.7)
28. Changelog (actualizado v3.5.7)
29. Licencia

---

## 1. Que es este plugin

`apolo-dynamic-flow` es un plugin TypeScript para OpenCode que **reemplaza a `apolo-flow-guardian.ts`**. Orquesta agentes con:

- **State machine explicita** con transiciones legales y gates por fase (no "planificacion libre").
- **Loop dinamico con circuit breaker adaptativo** - cada fase tiene `max` iteraciones; al agotarse, escala o bloquea (sin loops infinitos).
- **Recoleccion determinista de evidencia** - scripts Python (no el agente) capturan archivos, git diff, simbolos, endpoints, DB queries, screenshots. Producen `EVIDENCE-PACK.yaml` con hash chain.
- **Planes generados por Python** - `generate_plan.py` lee evidence + verdad y produce `DYNAMIC-PLAN.yaml` con topological sort y adaptative gates.
- **Tests automaticos tras cada cambio** - `run_tests.py` se ejecuta tras micro-cambios. Si falla y el cambio fue micro, rollback automatico via `git restore`.
- **Absorcion automatica de tools externas** - descubre MCPs en `opencode.json`, skills en `.opencode/skills/`, plugins en `.opencode/plugin/`, scripts en `scripts/python/`. Verifica salud y registra en `TOOL-REGISTRY.yaml`.
- **Telemetria append-only** + panel HTML para visualizacion en tiempo real.
- **Routing declarativo** - `routing-rules.json` con 10 reglas editables sin tocar codigo TS.
- **Arbol de decision D-NNN** - reemplaza "plan tras plan" por arbol finito con circuit breaker por patron de fallos.
- **Tests TypeScript ejecutables** - 35 tests con `node --test` que validan modulos reales del plugin.
- **Atomic writes + file locks** (v2.3.0) - escrituras seguras bajo concurrencia.
- **Seguridad operacional** (v2.4.0) - allowlist de origenes, secret detection (11 patrones), hash chain en audit log, sandboxing.
- **Calidad del analisis** (v3.5.7) - BFS multi-nivel en predict_impact, code_quality.py multi-lenguaje, test_coverage por simbolo, LSP integration.

### Problemas que resuelve (vs. plugin viejo)

| Problema | apolo-flow-guardian.ts | apolo-dynamic-flow |
|---|---|---|
| Planes estaticos | Si, no se adaptaban | Planes dinamicos con versionado y adaptative gates |
| Loop infinito "plan tras plan" | Si | Circuit breaker por fase + arbol de decision D-NNN |
| Recoleccion de evidencia | Agente piensa | Scripts Python deterministas |
| Tests tras cambios | No | Automaticos con rollback |
| MCPs absorbidos | No, solo declarados | Auto-descubrimiento + health check + fallback |
| Telemetria | self-audit.log pasivo | telemetry.jsonl + panel HTML + runtime-audit.log |
| Tests del propio plugin | 0 | 5 suites Python + 35 tests TypeScript |
| Routing | Logica opaca en Python | Routing declarativo editable (routing-rules.json) |
| Atomicidad de escrituras | No | Atomic writes + file locks (v2.3.0) |
| Secretos en evidencia | Expuestos | Secret detection + redaccion (v2.4.0) |
| Prediccion de impacto | 1 nivel (solo dependencias directas) | BFS multi-nivel hasta profundidad 5 (v3.5.7) |
| Calidad de codigo | No | bandit + radon + eslint-plugin-security + gosec + cppcheck (v3.5.7) |
| Cobertura por simbolo | No | coverage.py + nyc + go test -cover con heuristicas (v3.5.7) |
| Analisis semantico | No | LSP integration con regex fallback (v3.5.7) |

---

## 2. Prerequisitos

### Versiones minimas

| Herramienta | Version minima | Verificar | Instalar en Ubuntu |
|---|---|---|---|
| **Node.js** | 18.0.0 | `node --version` | `sudo apt install -y nodejs` |
| **npm** | 9.0.0 | `npm --version` | `sudo apt install -y npm` |
| **Python 3** | 3.10 | `python3 --version` | `sudo apt install -y python3` |
| **pip3** | cualquiera | `pip3 --version` | `sudo apt install -y python3-pip` |
| **curl** | cualquiera | `curl --version` | `sudo apt install -y curl` |
| **git** | cualquiera | `git --version` | `sudo apt install -y git` |

### Dependencias requeridas (v2.3.0+)

| Paquete | Para que | Instalar |
|---|---|---|
| **PyYAML** | Parser YAML robusto (reemplaza el minimalista) | `pip3 install --user PyYAML` |
| **jsonschema** | Validacion completa de schemas | `pip3 install --user jsonschema` |

### Dependencias opcionales (v3.5.7 - calidad del analisis)

| Paquete | Para que | Instalar |
|---|---|---|
| **bandit** | Seguridad Python (detecta eval, exec, hardcoded passwords, etc.) | `pip3 install --user bandit` |
| **radon** | Complejidad ciclomatica Python | `pip3 install --user radon` |
| **coverage.py** | Cobertura de tests Python por simbolo | `pip3 install --user coverage pytest` |
| **pytest** | Runner de tests Python (requerido por coverage) | `pip3 install --user pytest` |
| **nyc** | Cobertura de tests JS/TS | `npm install -D nyc` |
| **eslint-plugin-security** | Seguridad JS/TS | `npm install -D eslint-plugin-security` |
| **gosec** | Seguridad Go | `go install github.com/securego/gosec/cmd/gosec@latest` |
| **gocyclo** | Complejidad ciclomatica Go | `go install github.com/fzipp/gocyclo/cmd/gocyclo@latest` |
| **cppcheck** | Seguridad C/C++ | `sudo apt install -y cppcheck` |
| **typescript-language-server** | LSP TypeScript/JavaScript | `npm install -g typescript-language-server typescript` |
| **pylsp** | LSP Python | `pip3 install --user python-lsp-server` |
| **pyright** | LSP Python (alternativa) | `npm install -g pyright` |
| **gopls** | LSP Go | `go install golang.org/x/tools/gopls@latest` |
| **rust-analyzer** | LSP Rust | `rustup component add rust-analyzer` |
| **clangd** | LSP C/C++ | `sudo apt install -y clangd` |
| **intelephense** | LSP PHP | `npm install -g intelephense` |

> **Sin estas dependencias opcionales el plugin funciona**, pero con capacidades reducidas. Los scripts `code_quality.py`, `test_coverage.py` y `lsp_integration.py` degradan gracefully a regex estimation cuando una herramienta no esta disponible, y lo reportan en el campo `degradations` del output.

### Verificar prerequisitos en un comando

```bash
echo "Node: $(node --version 2>/dev/null || echo FALTA)"
echo "npm:  $(npm --version 2>/dev/null || echo FALTA)"
echo "Py:   $(python3 --version 2>/dev/null || echo FALTA)"
echo "curl: $(curl --version 2>/dev/null | head -1 || echo FALTA)"
echo "git:  $(git --version 2>/dev/null || echo FALTA)"
echo "PyYAML: $(python3 -c 'import yaml; print(yaml.__version__)' 2>/dev/null || echo FALTA)"
echo "bandit: $(command -v bandit || echo FALTA)"
echo "radon:  $(command -v radon || echo FALTA)"
echo "coverage: $(command -v coverage || echo FALTA)"
echo "tsserver: $(command -v typescript-language-server || echo FALTA)"
echo "gopls: $(command -v gopls || echo FALTA)"
```

---

## 3. Instalacion (3 metodos)

### Metodo A - Clonar repo y correr install.sh (recomendado)

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
```

El script `install.sh` hace todo automaticamente en 7 pasos:

1. Verifica prerequisitos (node, npm, python3, curl, git)
2. Valida que los archivos del plugin esten presentes
3. Crea carpetas runtime (`.opencode/apolo-dynamic/`, `plan/active/`)
4. Instala dependencias npm (typescript, @types/node)
5. Instala dependencias Python requeridas (PyYAML, jsonschema)
6. Compila TypeScript a `dist/`
7. Corre los 5 suites Python + los 35 tests TypeScript

Salida esperada: `INSTALACION COMPLETA - apolo-dynamic-flow v3.5.7`

### Metodo B - Instalacion manual paso a paso

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
mkdir -p .opencode/apolo-dynamic/screenshots plan/active
npm install
pip3 install --user PyYAML jsonschema
pip3 install --user bandit radon coverage pytest   # opcional, v3.5.7
npx tsc
python3 tests/run_all_tests.py
python3 tests/test_quality.py                       # nuevo en v3.5.7
node --test dist/tests/plugin.test.js
```

### Metodo C - Migrar desde v2.4.x (patch v3.5.7)

Si ya tienes v2.4.x instalado y quieres solo aplicar el patch v3.5.7:

```bash
# Copiar el patch a ~/Descargas
cp -r apolo-v250-patch ~/Descargas/

# Correr migracion
~/migrar_v250.sh

# O desde un ZIP
~/migrar_v250.sh --from-zip ~/Descargas/apolo-v250-patch.zip
```

El script `migrar_v250.sh` mueve 6 archivos (predict_impact.py modificado + 4 scripts nuevos + package.json) y parchea el README quirurgicamente.

### Opciones de install.sh

```bash
./install.sh                  # instalacion completa
./install.sh --check          # solo verificar prerequisitos
./install.sh --tests          # solo correr tests
./install.sh --no-npm         # saltar npm install
./install.sh --no-python-deps # saltar pip install
./install.sh -h, --help       # mostrar ayuda
```

---

## 4. Verificacion de la instalacion

Despues de instalar, verifica que todo funciona:

```bash
# 1. Tests Python deben pasar (5/5 suites, 42 asserts)
python3 tests/run_all_tests.py
# Resultado: "ALL 5 TESTS PASSED"

# 2. Tests TypeScript deben pasar (35 tests)
npx tsc && node --test dist/tests/plugin.test.js
# Resultado: "pass 35 / fail 0"

# 3. Tests de atomicidad (v2.3.0)
python3 tests/test_atomic.py
# Resultado: "ALL ATOMIC TESTS PASSED"

# 4. Tests de seguridad (v2.4.0)
python3 tests/test_security.py
# Resultado: "ALL 12 SECURITY TESTS PASSED"

# 5. Tests de calidad (v3.5.7 - NUEVO)
python3 tests/test_quality.py
# Resultado: "ALL 8 QUALITY TESTS PASSED (v3.5.7)"

# 6. TypeScript compila sin errores
npx tsc --noEmit
# Resultado: sin output, exit code 0

# 7. CLI funciona
bash scripts/bash/apolo-inspect.sh help
# Resultado: muestra lista de 12 subcomandos

# 8. Verificar v3.5.7 - predict_impact con BFS multi-nivel
python3 scripts/python/predict_impact.py --help 2>&1 | head -3
# Resultado: muestra --cascade-depth option

# 9. Verificar v3.5.7 - code_quality multi-lenguaje
python3 scripts/python/code_quality.py --repo-root . --output /tmp/CQ.yaml
cat /tmp/CQ.yaml | head -20
# Resultado: muestra languages_detected, security_findings, etc.

# 10. Verificar v3.5.7 - test_coverage por simbolo
python3 scripts/python/test_coverage.py --repo-root . --output /tmp/TC.yaml
cat /tmp/TC.yaml | head -20
# Resultado: muestra total_symbols, covered_symbols, coverage_percentage
```

Si los 10 pasos funcionan, el plugin esta listo para usar con v3.5.7.

---

## 5. Integracion con OpenCode

Para que OpenCode cargue el plugin, edita el `opencode.json` de tu proyecto destino:

### Opcion A - Plugin local (recomendado para desarrollo)

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

> IMPORTANTE: `plugin` debe ser un array de strings (no un objeto). OpenCode rechaza configs con plugin como objeto.

### Verificar integracion con OpenCode

```bash
opencode mcp list
```

### Como el agente OpenCode absorbe este plugin

Cuando OpenCode carga el plugin, el archivo `plugin/index.ts` expone:

- **Hooks** (eventos del lifecycle de OpenCode):
  - `tool:execute:before` - bloquea mutaciones si el flow esta en estado `blocked`
  - `tool:execute:after` - registra telemetria de cada tool invocada
  - `session:start` - absorbe tools automaticamente al iniciar sesion

- **Tools** (invocables por el orquestador):
  - `apolo.flow.init` - inicializa un flow nuevo
  - `apolo.flow.tick` - ejecuta una iteracion del loop dinamico
  - `apolo.evidence.collect` - dispara recoleccion determinista
  - `apolo.plan.generate` - genera plan dinamico desde evidence
  - `apolo.tests.run` - ejecuta tests tras cambios
  - `apolo.tools.absorb` - descubre y registra tools externas
  - `apolo.context.query` - responde 17 tipos de preguntas (v2.2.0)
  - `apolo.registry.recommend` - recomienda tools con scoring (v2.2.0)
  - `apolo.health.check` - hot reload de tools (v2.2.0)

- **Commands** (invocables por CLI):
  - `apolo-inspect` - inspector de estado con 12 subcomandos

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

---

## 6. Estructura completa del plugin

```text
apolo-dynamic-flow/
├── install.sh                          # Instalacion automatica (7 pasos)
├── README.md                           # Este archivo (v3.5.7)
├── ARCHITECTURE.md                     # Diseno detallado
├── MIGRATION-GUIDE.md                  # Migracion desde apolo-flow-guardian.ts
├── ANALYSIS-REPORT.md                  # Analisis del proyecto viejo
├── opencode.json                       # Config OpenCode
├── package.json                        # v3.5.7
├── tsconfig.json                       # Config TypeScript
├── routing-rules.json                  # Routing declarativo (R-001..R-010)
├── security_config.yaml                # Allowlist + secret patterns (v2.4.0)
├── .gitignore
│
├── plugin/                             # 18 modulos TypeScript
│   ├── index.ts, types.ts, state-machine.ts, loop-engine.ts
│   ├── block-detector.ts, evidence-collector.ts, plan-generator.ts
│   ├── test-runner.ts, tool-absorber.ts, telemetry.ts, inspector.ts, utils.ts
│   ├── core/
│   │   ├── runtime-logger.ts           # Log JSON Lines con seq monotono + hash chain (v2.4.0)
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
│
├── templates/                          # 5 templates YAML
├── scripts/
│   ├── python/                         # 14 scripts Python (v3.5.7)
│   │   ├── common.py                   # Utilidades (YAML, hash, git, paths, atomic writes)
│   │   ├── collect_evidence.py         # Recoleccion + secret redaction (v2.4.0)
│   │   ├── generate_plan.py            # Generacion de DYNAMIC-PLAN
│   │   ├── run_tests.py                # Tests con rollback
│   │   ├── absorb_mcp.py               # Absorcion MCP
│   │   ├── validate_artifact.py        # jsonschema hard (v2.3.0)
│   │   ├── telemetry_aggregator.py     # Stats de telemetria
│   │   ├── inspect_tools.py            # Inspeccion de tools
│   │   ├── rollback.py                 # Rollback via git restore
│   │   ├── index_codebase.py           # Indexador AST (Gap 1, v2.2.0)
│   │   ├── score_evidence.py           # Scoring (Gap 2, v2.2.0)
│   │   ├── predict_impact.py           # BFS multi-nivel (Gap 3, v2.2.0 + v3.5.7)
│   │   ├── scaffold_impl.py            # Andamio (Gap 4, v2.2.0)
│   │   ├── context_query.py            # 17 preguntas (v2.2.0)
│   │   ├── registry_recommend.py       # Recomendacion de tools (v2.2.0)
│   │   ├── health_check.py             # Hot reload (v2.2.0)
│   │   ├── absorb_external_skills.py   # Absorcion externa con allowlist (v2.4.0)
│   │   ├── secret_scanner.py           # Deteccion 11 patrones (v2.4.0)
│   │   ├── code_quality.py             # Multi-lenguaje: bandit, radon, eslint, gosec (v3.5.7 NUEVO)
│   │   ├── test_coverage.py            # Cobertura por simbolo: coverage, nyc, go test (v3.5.7 NUEVO)
│   │   └── lsp_integration.py          # LSP: find-refs, diagnostics, def, hover (v3.5.7 NUEVO)
│   └── bash/
│       └── apolo-inspect.sh           # CLI (12 subcomandos)
├── panel/                              # Panel de telemetria HTML
└── tests/                              # 8 suites de tests (v3.5.7)
    ├── run_all_tests.py                # 5 suites Python agregadas
    ├── test_state_machine.py           # FSM: 6 asserts
    ├── test_loop_engine.py             # Loop dinamico: 8 asserts
    ├── test_block_detector.py          # Bloqueos: 7 asserts
    ├── test_tool_absorber.py           # Absorcion: 10 asserts
    ├── test_python_scripts.py          # Scripts Python: 11 asserts
    ├── test_atomic.py                  # Atomicidad + concurrency (v2.3.0)
    ├── test_security.py                # 12 tests de seguridad (v2.4.0)
    ├── test_quality.py                 # 8 tests de calidad (v3.5.7 NUEVO)
    └── plugin.test.ts                  # 35 tests TS con node --test
```

Total: ~85 archivos (v3.5.7), incluyendo los 4 scripts nuevos de calidad del analisis.

---

## 7. Uso del CLI apolo-inspect.sh

```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [opciones]
```

### Subcomandos

| Subcomando | Descripcion |
|---|---|
| `init-flow` | Inicializa un flow nuevo |
| `absorb` | Descubre y registra tools externas |
| `state` | Estado del flow activo |
| `tools` | Lista tools absorbidas |
| `blocks` | Lista bloqueos activos |
| `telemetry` | Stats de telemetria |
| `evidence` | Evidence pack actual |
| `plan` | Plan dinamico actual |
| `health` | Health check de tools |
| `all` | Resumen completo |
| `serve-panel` | Levanta panel HTTP (puerto 8765) |
| `test` | Corre tests del plugin |
| `help` | Muestra la ayuda |

### Opciones globales

| Opcion | Descripcion | Default |
|---|---|---|
| `--flowid FLOW` | Flow ID a inspeccionar | Detecta de plan/CURRENT.md |
| `--repo-root PATH` | Raiz del repo | Directorio actual |
| `--json` | Output en JSON (cuando aplica) | Off |

### Ejemplos de uso

```bash
bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-20260620-MI-FLOW
bash scripts/bash/apolo-inspect.sh state --flowid APOLO-20260620-MI-FLOW
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
bash scripts/bash/apolo-inspect.sh all --flowid APOLO-20260620-MI-FLOW
```

---

## 8. Panel de telemetria

```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
# Abrir http://localhost:8765/
```

### Tabs del panel

| Tab | Contenido |
|---|---|
| Overview | Estado del flow, metricas globales |
| Timeline | Ultimos 100 eventos de telemetria |
| Loops | Contadores current/max por fase con colores |
| Blocks | Lista de bloqueos activos con resolucion sugerida |
| Tests | Ultimos 20 runs de tests |
| Tools | Tabla de tools absorbidas |
| Tokens | Total de tokens consumidos |

### Cambiar el puerto

```bash
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI-FLOW
```

Auto-refresh cada 5 segundos.

---

## 9. Configuracion avanzada

### Circuit breaker

En `templates/FLOW-STATE.template.yaml`:

```yaml
loops:
  reanclaje: { current: 0, max: 2, last_decision: "" }
  implementation: { current: 0, max: 4, last_decision: "" }
circuit_breaker:
  policy: fail-closed   # fail-closed | fail-open-adaptive
  escalation_path: []
```

Politicas:
- `fail-closed` (default): al agotar `max`, bloquea el flow.
- `fail-open-adaptive`: al agotar `max`, escala a `escalation_path[0]`.

### Routing declarativo

Edita `routing-rules.json` para cambiar que agent se invoca en cada fase. 10 reglas (R-001..R-010):

```json
{
  "id": "R-001",
  "priority": 10,
  "when": { "phase": "reanclaje", "artifacts_absent": ["00-OBJETIVO.yaml"] },
  "then": { "next_agent": "planner", "reason": "No hay objetivo." }
}
```

Validar schema:

```bash
python3 scripts/python/validate_artifact.py \
  --artifact routing-rules.json \
  --schema schemas/json/routing-rules.json
```

Exit codes: 0 = valido, 1 = invalido, 2 = error.

### Allowlist de origenes (v2.4.0)

En `security_config.yaml`:

```yaml
allowed_origins:
  - github://juancspjr/apolo-dynamic-flow/skills/
  - https://raw.githubusercontent.com/juancspjr/

blocked_origins:
  - http://localhost
  - http://127.0.0.1
  - http://169.254.169.254   # AWS metadata endpoint
  - file://
```

### Sandboxing (v2.4.0)

```yaml
sandbox:
  mode: firejail   # firejail | docker | none
  profile: default
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

Despues re-absorber: `bash scripts/bash/apolo-inspect.sh absorb --repo-root $(pwd)`

---

## 10. Tests

El plugin tiene 50+ tests en 4 categorias.

### Correr todos los tests

```bash
# Tests Python (5 suites, 42 asserts)
python3 tests/run_all_tests.py

# Tests de atomicidad (v2.3.0)
python3 tests/test_atomic.py

# Tests de seguridad (v2.4.0)
python3 tests/test_security.py

# Tests de calidad (v3.5.7 - NUEVO)
python3 tests/test_quality.py

# Tests TypeScript (35 tests ejecutables)
npx tsc && node --test dist/tests/plugin.test.js

# Ambos con npm
npm run test:all
```

### Suites Python (5)

| Suite | Que valida | # asserts |
|---|---|---|
| `test_state_machine.py` | FSM: transiciones legales, gates | 6 |
| `test_loop_engine.py` | Loop dinamico, circuit breaker | 8 |
| `test_block_detector.py` | Deteccion de bloqueos | 7 |
| `test_tool_absorber.py` | Absorcion de tools externas | 10 |
| `test_python_scripts.py` | Scripts Python (YAML, hash, generate_plan) | 11 |

### Suite TypeScript (35 tests ejecutables)

`tests/plugin.test.ts` valida modulos reales del plugin con `node --test`:

| Describe block | Tests | Que valida |
|---|---|---|
| RuntimeLogger | 4 | log JSON Lines, seq monotono, createFlowLogger, pasivo |
| DeclarativeRouter | 5 | routing-rules.json, R-001/R-002/R-008/R-010, fallback |
| LoopEngineTree | 6 | D-001, advance, detectCircuitBreaker |
| MicroTestRunner | 4 | extractTestCommand, runTest |
| McpAbsorber | 7 | detectAvailableMcps, invokeMcp con fallback |
| ParallelHypothesisRunner | 5 | planHypotheses, selectWinner, scoreHypothesis |
| ContextQueryTools | 4 | apolo.context.query, 17 preguntas (v2.2.0) |

### Tests de atomicidad (v2.3.0)

Validan que los atomic writes y file locks funcionan bajo concurrencia.

### Tests de seguridad (v2.4.0)

12 tests que validan: deteccion de 6 tipos de secretos (AWS, GitHub, PEM, DB, JWT, password), redaccion, allowlist (permitir/denegar/SSRF), hash chain (valido/manipulado).

### Tests de calidad (v3.5.7 - NUEVO)

8 tests que validan las nuevas capacidades de v3.5.7:

| Test | Que valida |
|---|---|
| 1 | `predict_impact.py`: BFS multi-nivel detecta dependencias a profundidad 3+ |
| 2 | `predict_impact.py`: BFS no entra en loop infinito con ciclos |
| 3 | `code_quality.py`: detecta complejidad ciclomatica alta (>15) |
| 4 | `code_quality.py`: detecta vulnerabilidades (o degrada gracefully) |
| 5 | `test_coverage.py`: identifica simbolos sin cobertura |
| 6 | `lsp_integration.py`: find-references funciona (regex fallback) |
| 7 | `lsp_integration.py`: get_diagnostics funciona (TODO, console.log, print) |
| 8 | `code_quality.py`: degradacion graceful multi-lenguaje |

Total: 8 tests TS + 42 asserts Python + 12 security + 8 quality = 70+ verificaciones.

### Tests durante desarrollo

```bash
python3 tests/run_all_tests.py
npx tsc --noEmit && python3 tests/run_all_tests.py
npm run test:all
```

---

## 11. Calidad del analisis (v3.5.7)

La version 2.5.0 anade 4 capacidades nuevas de analisis de calidad. Todas son **agnosticas al lenguaje** y **degradan gracefully** cuando una herramienta externa no esta disponible.

### 11.1. predict_impact.py - BFS multi-nivel

Antes (v2.4.x): `project_dependency_cascade` solo veia dependencias directas (A → B). Si A importa B que importa C que importa D, el cascade viejo solo detectaba A → B.

Ahora (v3.5.7): BFS multi-nivel hasta profundidad configurable (default 5). Si A importa B que importa C que importa D, el cascade detecta **A → B → C → D**.

```bash
python3 scripts/python/predict_impact.py \
  --plan plan/active/APOLO-.../03-PLAN-INDICE-DYNAMIC.yaml \
  --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \
  --output IMPACT-PREDICTION.yaml \
  --cascade-depth 5    # NUEVO en v3.5.7
```

#### Output nuevo en v3.5.7

```yaml
predictions:
  - mp_id: MP-01
    projections:
      dependency_cascade:
        risk_level: medium       # umbrales nuevos: <5 low, 5-15 medium, 16-30 high, >30 critical
        total_affected_modules: 12
        cascade_depth: 4         # NUEVO: profundidad maxima alcanzada por el BFS
        affected_by_level:       # NUEVO: cuantos archivos afectados a cada nivel
          1: 3
          2: 5
          3: 3
          4: 1
        per_level:               # NUEVO: lista de archivos por nivel (debugging)
          1: [src/handlers/foo.go, src/utils/bar.ts, ...]
          2: [src/api/foo_handler.go, ...]
        per_file:                # dependientes directos (compat con v2.4.x)
          src/handlers/foo.go: [src/api/foo_handler.go, ...]
```

#### Implementacion

- Usa `collections.deque` para BFS eficiente (FIFO).
- Para cada archivo del MP, explora sus dependientes (del `reverse_dependency_graph` del CODE-INDEX).
- Para cada dependiente, explora SUS dependientes (multi-nivel).
- Acumula todos los afectados con su nivel de profundidad.
- `visited` set previene ciclos infinitos.
- Umbrales de riesgo ajustados porque al hacer multi-nivel el numero crece.

### 11.2. code_quality.py - Multi-lenguaje (NUEVO)

Script que corre analisis de calidad de codigo. Agnostico al lenguaje: detecta el lenguaje de cada archivo y aplica el analizador apropiado.

```bash
python3 scripts/python/code_quality.py \
  --repo-root . \
  --output CODE-QUALITY.yaml

# O limitar a archivos especificos:
python3 scripts/python/code_quality.py \
  --repo-root . \
  --files "src/foo.ts,src/bar.py,src/baz.go"
```

#### Analizadores soportados

| Lenguaje | Seguridad | Complejidad ciclomatica |
|---|---|---|
| Python | bandit | radon cc |
| JavaScript/TypeScript | eslint-plugin-security | complexity-report (o regex estimation) |
| Go | gosec | gocyclo |
| Rust | cargo-audit | regex estimation |
| Java | spotbugs | regex estimation |
| C/C++ | cppcheck | regex estimation |
| PHP | psalm | regex estimation |
| HTML/CSS | (no security) | regex estimation |
| Otros | (no soportado) | regex estimation |

#### Output (CODE-QUALITY.yaml)

```yaml
schema_version: "2.5.0"
total_files: 47
languages_detected: [python, typescript, go, cpp]
tools_tried:
  bandit: true
  radon: true
  eslint-plugin-security: false    # no disponible
  gosec: false                      # no disponible
security_findings:
  - tool: bandit
    file: src/insecure.py
    line: 3
    test_id: B102
    severity: HIGH
    message: "Use of eval detected."
complexity_scores:
  - file: src/complex.py
    function: high_complexity_function
    complexity: 21
    rank: D
    tool: radon
    estimated: false
high_complexity_functions:           # complejidad > 15 (necesita refactor)
  - file: src/complex.py
    function: high_complexity_function
    complexity: 21
    rank: D
    recommendation: "refactor 'high_complexity_function' (complejidad 21 > 15)"
degradations:
  - "eslint-plugin-security no disponible — analisis de seguridad para typescript omitido"
  - "gosec no disponible — analisis de seguridad para go omitido"
  - "herramienta nativa de complejidad no disponible para cpp — usando regex-estimation"
recommendations:
  - "Refactorizar 1 funcion(es) con complejidad > 15"
  - "Atender 3 finding(s) de seguridad: {'HIGH': 2, 'MEDIUM': 1}"
  - "Instalar herramientas faltantes para analisis completo: 3 degradacion(es)"
summary:
  total_security_findings: 3
  total_functions_analyzed: 156
  high_complexity_count: 1
  degradation_count: 3
```

### 11.3. test_coverage.py - Cobertura por simbolo (NUEVO)

Diferencia con `run_tests.py` (que solo corre tests): este script analiza **QUE simbolos** estan cubiertos por tests, no solo si los tests pasan.

```bash
python3 scripts/python/test_coverage.py \
  --repo-root . \
  --output TEST-COVERAGE.yaml

# O usar CODE-INDEX.yaml como fuente de simbolos:
python3 scripts/python/test_coverage.py \
  --repo-root . \
  --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
```

#### Integraciones

| Lenguaje | Herramienta | Comando |
|---|---|---|
| Python | coverage.py | `coverage run -m pytest && coverage report --format=json` |
| JavaScript/TypeScript | nyc | `npx nyc --reporter=json npm test` |
| Go | go test -cover | `go test -cover -coverprofile=coverage.out ./...` |
| Otros | heuristica | Convencion de nombres: `test_<name>.py`, `<name>_test.go`, `<name>.test.ts` |

#### Output (TEST-COVERAGE.yaml)

```yaml
schema_version: "2.5.0"
code_index_used: true
coverage_tool_used: "coverage.py"     # o "nyc", "go test -cover", null
dominant_language: "python"
total_symbols: 156
covered_symbols: 89
uncovered_symbols: 67
coverage_percentage: 57.05
critical_uncovered:                   # simbolos exportados sin test (los mas riesgosos)
  - file: src/handlers/foo.py
    name: process_payment
    kind: function
    is_exported: true
    covered: false
    test_files: []
by_file:
  src/handlers/foo.py:
    total_symbols: 12
    covered_symbols: 8
    coverage_pct: 66.67
    associated_tests: [tests/test_foo.py]
degradations:
  - "coverage.py no disponible — usando heuristica por convencion"
recommendations:
  - "Escribir tests para 23 simbolo(s) exportado(s) sin cobertura"
  - "Cobertura actual 57.05% — objetivo minimo 50%"
summary:
  total_symbols: 156
  covered: 89
  uncovered: 67
  critical_uncovered: 23
  coverage_percentage: 57.05
```

### 11.4. lsp_integration.py - LSP + regex fallback (NUEVO)

Script que integra con LSP (Language Server Protocol) para analisis semantico.

```bash
# Modo accion puntual
python3 scripts/python/lsp_integration.py \
  --repo-root . \
  --symbol "init" \
  --action find-references

python3 scripts/python/lsp_integration.py \
  --repo-root . \
  --file plugin/index.ts \
  --action diagnostics

python3 scripts/python/lsp_integration.py \
  --repo-root . \
  --symbol "process_payment" \
  --action go-to-definition

# Modo analisis completo
python3 scripts/python/lsp_integration.py \
  --repo-root . \
  --output LSP-ANALYSIS.yaml
```

#### LSPs soportados

| Lenguaje | LSP | Deteccion |
|---|---|---|
| TypeScript/JavaScript | typescript-language-server | `command -v typescript-language-server` |
| Python | pylsp o pyright | `command -v pylsp \|\| command -v pyright` |
| Go | gopls | `command -v gopls` |
| Rust | rust-analyzer | `command -v rust-analyzer` |
| Java | jdtls | `command -v jdtls` |
| C/C++ | clangd | `command -v clangd` |
| PHP | intelephense | `command -v intelephense` |

#### Funciones publicas

- `find_references(symbol, repo_root, file_hint=None)` - lista archivos+lineas donde se usa el simbolo
- `get_diagnostics(file_path, repo_root)` - errores/warnings de un archivo
- `go_to_definition(symbol, repo_root, file_hint=None)` - donde se define un simbolo
- `get_hover(symbol, repo_root, file_hint=None)` - documentacion de un simbolo

#### Degradacion graceful

Si un LSP no esta disponible, el script usa regex para buscar el simbolo en todos los archivos del mismo lenguaje. El regex usa `\b` (word boundaries) para reducir falsos positivos.

El output reporta que metodo se uso (`method: "regex"` o `method: "lsp:gopls"`), para que el usuario sepa si el resultado es preciso (LSP) o heuristico (regex).

### 11.5. test_quality.py - Tests de calidad (NUEVO)

8 tests que validan las 4 nuevas capacidades de v3.5.7. Resilientes: si una herramienta externa no esta instalada, el test pasa verificando que la degradacion es graceful.

```bash
python3 tests/test_quality.py
# Resultado: "ALL 8 QUALITY TESTS PASSED (v3.5.7)"
```

El test instala un stub de `common.py` si no esta disponible, para poder correr aisladamente del plugin migrado. Esto permite validar la logica de los scripts sin depender del `common.py` real (que vive en `scripts/python/` en el plugin migrado).

---

## 12. Agnostico al lenguaje

`apolo-dynamic-flow` es **agnostico al lenguaje**. Soporta:

- **HTML** - deteccion por extension `.html`/`.htm`, analisis de complejidad por regex
- **CSS** - deteccion por extension `.css`/`.scss`/`.less`, analisis por regex
- **JavaScript** - deteccion por extension `.js`/`.jsx`/`.mjs`/`.cjs`, seguridad con eslint-plugin-security
- **React** (JSX/TSX) - deteccion por extension `.jsx`/`.tsx`, soporte en security y coverage
- **TypeScript** - deteccion por extension `.ts`/`.tsx`, LSP con typescript-language-server
- **Python** - deteccion por extension `.py`, seguridad con bandit, complejidad con radon, coverage con coverage.py
- **Go** - deteccion por extension `.go`, seguridad con gosec, complejidad con gocyclo, coverage con go test -cover
- **Rust** - deteccion por extension `.rs`, LSP con rust-analyzer
- **C/C++** - deteccion por extension `.c`/`.cc`/`.cpp`/`.cxx`/`.h`/`.hpp`, seguridad con cppcheck, LSP con clangd
- **Java** - deteccion por extension `.java`/`.kt`, LSP con jdtls
- **PHP** - deteccion por extension `.php`, LSP con intelephense
- **Otros** (Ruby, Swift, C#) - deteccion por extension, analisis por regex

### Como funciona la deteccion

Cada script nuevo de v3.5.7 tiene un mapa `EXTENSION_TO_LANGUAGE` que normaliza la extension del archivo a un lenguaje. A partir de ahi, despacha al analizador apropiado (si esta disponible) o degrada a regex fallback.

```python
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "java",
    ".c": "cpp", ".cc": "cpp", ".cpp": "cpp",
    ".h": "cpp", ".hpp": "cpp",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".cs": "csharp",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".less": "css",
}
```

### Directorios excluidos del analisis

Para evitar ruido, los scripts excluyen:

- `node_modules`, `.git`, `dist`, `build`, `vendor`
- `.next`, `__pycache__`, `.cache`, `.opencode`
- `target` (Rust), `.venv`, `venv`, `env` (Python)
- `.pytest_cache`, `coverage`, `.nyc_output`

---

## 13. Troubleshooting

### Error: Configuration is invalid at opencode.json

`plugin` debe ser array, no objeto:

```json
// Incorrecto
"plugin": { "apolo-dynamic-flow": "./plugin/index.ts" }

// Correcto
"plugin": [ "./plugin/index.ts" ]
```

### OSError: Address already in use

```bash
fuser -k 8765/tcp
# o usar otro puerto
PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel ...
```

### Panel devuelve 404

Las rutas en `panel/panel.js` deben empezar con `/`:

```javascript
API.statePath = `/plan/active/${flowid}/FLOW-STATE.yaml`;
```

### MCPs aparecen como failed

Algunos paquetes npm no existen. Deshabilitar en `opencode.json` con `"enabled": false`.

### Tests fallan despues de modificar common.py

Instalar PyYAML y reemplazar las funciones en `common.py`:

```bash
pip3 install --user PyYAML
```

```python
import yaml
def yaml_load(text): return yaml.safe_load(text)
def yaml_dump(obj): return yaml.safe_dump(obj, default_flow_style=False, sort_keys=False, allow_unicode=True)
```

### routing-rules.json duplicado al descargar

Hay dos archivos: uno es el de reglas (va en la raiz) y otro es el schema JSON (va en `schemas/json/`).

```bash
head -c 100 routing-rules.json  # si dice "json-schema.org" es el schema
```

### v3.5.7: code_quality.py reporta "degradations" para todo

Si `code_quality.py` reporta todas las herramientas como no disponibles:

```bash
# Verificar que herramientas estan instaladas
command -v bandit radon coverage gosec gocyclo cppcheck

# Instalar las que falten (Python):
pip3 install --user bandit radon coverage pytest

# Instalar las que falten (Node):
npm install -D eslint-plugin-security nyc

# Instalar las que falten (Go):
go install github.com/securego/gosec/cmd/gosec@latest
go install github.com/fzipp/gocyclo/cmd/gocyclo@latest

# Instalar las que falten (sistema):
sudo apt install -y cppcheck
```

El script funciona sin ninguna herramienta instalada (usa regex fallback), pero con todas instaladas produce analisis mucho mas precisos.

### v3.5.7: test_coverage.py reporta 0% de cobertura

Si `test_coverage.py` reporta 0% a pesar de tener tests:

```bash
# Verificar que coverage.py esta instalado
command -v coverage

# Si no, instalarlo:
pip3 install --user coverage pytest

# Verificar que los tests pasan primero:
python3 -m pytest tests/

# Si coverage no funciona, el script usa heuristica por convencion de nombres.
# Asegurate de que tus tests siguen las convenciones:
#   Python:   test_<module>.py o <module>_test.py
#   JS/TS:    <module>.test.js o <module>.spec.ts
#   Go:       <module>_test.go
```

### v3.5.7: lsp_integration.py siempre usa regex

Si `lsp_integration.py` siempre reporta `method: "regex"` en vez de `method: "lsp:..."`:

```bash
# Verificar LSPs instalados
command -v typescript-language-server
command -v pylsp pyright
command -v gopls
command -v rust-analyzer
command -v clangd

# Instalar los que falten:
npm install -g typescript-language-server typescript
pip3 install --user python-lsp-server
# o:  npm install -g pyright
go install golang.org/x/tools/gopls@latest
rustup component add rust-analyzer
sudo apt install -y clangd
```

El regex fallback funciona, pero el LSP es mucho mas preciso (encuentra referencias reales, no coincidencias de texto).

### v3.5.7: predict_impact.py cascade_depth siempre es 1

Si `cascade_depth` siempre es 1, es porque el `reverse_dependency_graph` del CODE-INDEX solo tiene dependencias directas. Esto es normal si el codebase es pequeno. Para verificar que el BFS funciona con multi-nivel:

```bash
# Crear un repo de prueba con cadena A -> B -> C -> D
mkdir /tmp/test-cascade
cd /tmp/test-cascade
# (crear archivos y CODE-INDEX con cadena)
python3 /path/to/predict_impact.py --plan ... --code-index ... --cascade-depth 5
# cascade_depth deberia ser >= 3 si la cadena existe
```

### v3.5.7: test_quality.py falla con "No module named 'common'"

Si los tests fallan con este error, es porque `test_quality.py` no encuentra `common.py`:

```bash
# Opcion A: correr desde el plugin migrado (recomendado)
cd ~/new_project
python3 tests/test_quality.py

# Opcion B: si common.py esta en otro path, ajustar PYTHONPATH
PYTHONPATH=~/new_project/scripts/python python3 tests/test_quality.py
```

El test instala un stub de `common.py` automaticamente si no lo encuentra, pero el stub no tiene todas las funciones del real. Para tests completos, correr desde el plugin migrado.

---


---

## 14. Como funciona internamente

### State machine de fases

```text
reanclaje -> planning-bootstrap -> asr -> verdad -> shaping -> plan-indice
                                                                |
                            cierre-flow <- critical-validation <- mp-validation <- implementation
```

Cada transicion requiere:
- `from` y `to` validos (tabla TRANSITIONS en state-machine.ts)
- Gate evaluado antes de transitar (G-REANCLAJE, G-BOOTSTRAP, etc.)
- Artefactos requeridos presentes en state.artifacts

### Loop dinamico con circuit breaker

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

### Recoleccion determinista de evidencia

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

### Generacion de plan dinamico

```text
generate_plan.py --method hybrid
    → Lee EVIDENCE-PACK + EVIDENCE-SCORE
    → Clustering por componente (usando CODE-INDEX)
    → Para cada cluster: crea unidad U-NNN, tipo de cambio, MP estimados
    → Topological sort por dependencias
    → Adaptative gates (5 reglas: split-unit, escalate, block, etc.)
    → DYNAMIC-PLAN.yaml
```

### Routing declarativo

```text
route(ctx) -> load routing-rules.json
           -> ordenar por prioridad (1 = maxima)
           -> primera regla que matchea
           -> next_agent + reason + circuit_breaker
           -> log al runtime-audit.log
```

### Arbol de decision D-NNN

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

### Tests automaticos con rollback

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

### Absorcion de tools externas

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

---

## 15. Arquitectura de 3 Capas (v3.3.0)

APOLO es UN sistema con 3 capas que trabajan juntas:

```
┌─────────────────────────────────────────────────┐
│  CAPA 3: INTELIGENCIA (v2.6-v3.5)              │
│  Self-healing | Semantic search | LLM bridge   │
│  Cross-flow learning | Visual diff | Replay    │
│  Script generator | Dynamic invoker            │
│  apolo_natural | Escape hatch | Guided recovery│
├─────────────────────────────────────────────────┤
│  CAPA 2: DETERMINISTA (v2.0-v2.5)              │
│  AST index | BFS impact | Code quality         │
│  Test coverage | LSP | Vulnerability scanner   │
│  Code smells | Full audit                      │
├─────────────────────────────────────────────────┤
│  CAPA 1: INFRAESTRUCTURA (v2.0-v2.4)          │
│  State machine | Loop engine | Evidence pack   │
│  Hash chain | Atomic writes | Allowlist + SSRF │
│  Auto-hooks | Post-script gates | Quality gates│
└─────────────────────────────────────────────────┘
```

**Como se unifican**: el orquestador (`apolo_orchestrator.py`) invoca scripts de las 3 capas en orden, pasando datos entre ellos. La data fluye: `cross_flow → score → decision_loop → plan → scaffold → gates → EXECUTE → visual_diff → replay → knowledge`.

---

## 16. El Orquestador Automatico (v3.2.0-v3.5.2)

### UN comando = TODO el ciclo

```bash
apolo "implementar JWT auth en plugin/index.ts"
# o
python3 scripts/python/apolo_orchestrator.py run --flowid APOLO-X --goal "implementar JWT auth" --yes
```

### 11 fases automaticas

| Fase | Que hace | Pausa? |
|------|----------|--------|
| 1. init | health_check + cross_flow recommendations | No |
| 2. index | index_codebase + cross_language + summarize | No |
| 3. collect | user_input_collector + collect_evidence + secret_scanner | Si (scope) |
| 4. score | score_evidence + apolo_config threshold + baseline capture | Si (score < threshold) |
| 5. plan | agent_decision_loop elige method + generate_plan + mp_prioritizer | No |
| 6. impact | predict_impact BFS multi-nivel | No |
| 7. scaffold | agent_decision_loop elige strategy + scaffold_v3 NATIVO + post_script_gates | No |
| 8. implement | force_quality_gates + EXECUTE scaffold commands + visual diff + smart_rollback on fail | Si (agent) |
| 9. test | run_tests + force_quality_gates BLOQUEA | Si (tests fallan) |
| 10. validate | force_quality_gates all + cross_flow_learning analyze | No |
| 11. complete | agent_honesty_enforcer + feedback + pre_commit_hooks + multi_agent merge | No |

### Integraciones nativas en el orquestador (v3.5.2)

- **Directiva 1**: data_flow_validator automatico despues de cada fase
- **Directiva 2**: agent_honesty_enforcer nativo en fase 11 (BLOQUEA si dishonest)
- **Directiva 3**: escape hatch limits verificados ANTES de ofrecer
- **Directiva 5**: scaffold_v3 vinculado nativamente (import directo, no subprocess)

### Persistencia

- `ORCHESTRATOR-STATE.yaml`: estado entre pausas
- `ORCHESTRATOR-REPORT.yaml`: reporte final consolidado

---

## 17. UN Comando en Lenguaje Natural (v3.5.3)

```bash
apolo "implementar JWT auth en plugin/index.ts"
apolo "analizar seguridad del codigo"
apolo "verificar que todo funciona"
apolo "auditoria completa"
apolo "que codigo no tiene tests"
apolo "crear un script para validar schemas"
apolo "diagnosticar el error TypeError en full_audit"
apolo "revertir los cambios que fallaron"
apolo "que fase sigue"
```

El sistema entiende 30+ intenciones y ejecuta el comando correcto. Si no reconoce la intencion, autogenera un script adaptado via `script_dynamic_invoker`.

---

## 18. CLI Router Unificado (v2.9.0)

```bash
bash scripts/bash/apolo_cli_router.sh <command> [args]
# o si esta en PATH:
apolo <command> [args]
```

### Comandos disponibles (65+)

**VALIDACION:**
- `apolo verify-flow` — verifica TODOS los super poderes
- `apolo validate-integration` — valida handoffs
- `apolo validate-dataflow` — verifica flujo de data
- `apolo verify-honesty` — previene autoengaño
- `apolo static-analyze` — dependencias circulares
- `apolo hooks-check` — hooks OpenCode (7 capas)
- `apolo gates-check` — valida YAML contra gates
- `apolo quality-check` — force quality gates
- `apolo full-test` — test exhaustivo (179 tests)
- `apolo quick-test` — test rapido (11 tests, ~15s)

**FLOW LIFECYCLE:**
- `apolo run` — UN comando = TODO el ciclo
- `apolo continue` — continua pausado
- `apolo init/collect/score/plan/impact/scaffold/scaffold-v3`

**ANALISIS:**
- `apolo index/quality/coverage/vulnerability/smells/full-audit/lsp/cross-language/summarize`

**INTELIGENCIA:**
- `apolo self-heal/gen-tests/semantic-search/refactor/llm`

**EXPERIENCIA:**
- `apolo feedback/docs/debug/context/recommend/health/onboard`

**HOOKS:**
- `apolo hooks-init/hooks-list/hooks-trigger/hooks-status/gates-init/escape-hatch/recover/self-heal`

**MULTI-AGENT:**
- `apolo multi-agent/rollback/prioritize/pre-commit/classify-scripts/invoke-script/config`

**ECOSISTEMA:**
- `apolo inspect/panel/github-actions/templates/gen-code/gen-doc`

---

## 19. Super Poderes Integrados (v3.5.0)

| Super poder | Script | Que hace |
|---|---|---|
| **apolo_natural** | apolo_natural.py | UN comando lenguaje natural (30+ intents) |
| **orquestador** | apolo_orchestrator.py | 11 fases automaticas |
| **agent_decision_loop** | agent_decision_loop.py | Evalua opciones, escoge la excelente |
| **scaffold_v3** | scaffold_v3.py | Auto-select U-NN + files concretos + commands |
| **evidence_visual_diff** | evidence_visual_diff.py | Baseline vs broken vs post-fix |
| **evidence_replay** | evidence_replay.py | Replay bug paso a paso |
| **cross_flow_learning** | cross_flow_learning.py | Aprende de flows anteriores |
| **force_quality_gates** | force_quality_gates.py | 7 gates que BLOQUEAN |
| **smart_rollback** | smart_rollback.py | Revertir SOLO archivos que fallaron |
| **mp_prioritizer** | mp_prioritizer.py | Reordena MPs por telemetria |
| **multi_agent_coordinator** | multi_agent_coordinator.py | 2+ agentes en paralelo |
| **agent_escape_hatch** | agent_escape_hatch.py | 5 tipos de escape con justificacion |
| **guided_recovery** | guided_recovery.py | 8 tipos de error diagnosticados |
| **self_healing_loop** | self_healing_loop.py | Auto-repara fallas seguras |
| **script_generator** | script_generator.py | Agente crea scripts nuevos |
| **script_classifier** | script_classifier.py | Clasifica 70 scripts |
| **script_dynamic_invoker** | script_dynamic_invoker.py | Invoca dinamicamente + autogenera |
| **user_input_collector** | user_input_collector.py | Pausa para input del usuario |
| **hooks_validator** | hooks_validator.py | 7 capas de hooks OpenCode |
| **auto_hooks** | auto_hooks.py | 19 triggers automaticos |
| **post_script_gates** | post_script_gates.py | 15 gates validan YAML |
| **apolo_config** | apolo_config.py | Thresholds configurables |
| **flow_verifier** | flow_verifier.py | Verifica TODOS los super poderes |
| **integration_validator** | integration_validator.py | 16 handoffs validados |
| **data_flow_validator** | data_flow_validator.py | 7 artefactos en orden |
| **agent_honesty_enforcer** | agent_honesty_enforcer.py | 5 claims verificados |
| **static_analyzer** | static_analyzer.py | Dependencias circulares |
| **pre_commit_hooks** | pre_commit_hooks.py | Hooks de git antes de commit |
| **feedback_loop** | feedback_loop.py | Feedback del usuario |
| **interactive_docs** | interactive_docs.py | Busqueda TF-IDF de docs |
| **debug_mode** | debug_mode.py | Breakpoints en state machine |
| **integration_validation** | integration_validation.py | E2E real del flow |
| **vulnerability_scanner** | vulnerability_scanner.py | CVE: safety/npm audit/pip-audit/govulncheck/cargo audit |
| **code_smells** | code_smells.py | long methods/god classes/deep nesting/duplication/dead code |
| **full_audit** | full_audit.py | 11 pasos, score A-F |
| **self_healing** | self_healing.py | Aprende de telemetria |
| **semantic_search** | semantic_search.py | TF-IDF + embeddings |
| **refactor_engine** | refactor_engine.py | Code smells -> refactoring |
| **llm_bridge** | llm_bridge.py | MiniMax/OpenAI compatible |
| **code_generator** | code_generator.py | 8 lenguajes |
| **doc_generator** | doc_generator.py | README sections, API docs |
| **project_templates** | project_templates.py | 8 frameworks |
| **onboarding** | onboarding.py | Wizard interactivo |
| **github_actions** | github_actions.py | Genera workflows CI/CD |

---

## 20. Validadores del Sistema (v3.5.0)

5 validadores trabajan en conjunto:

```
1. static_analyzer       — dependencias circulares (ANTES de ejecutar)
2. integration_validator — handoffs entre scripts (output -> input)
3. data_flow_validator   — artefactos en orden (automatico tras cada fase)
4. flow_verifier         — cada script funciona (sin falsos positivos)
5. agent_honesty_enforcer — claims del agente tienen evidencia (fase 11)
```

---

## 21. Hooks de OpenCode + Auto-hooks (v2.9.0)

### Verificacion del mecanismo de hooks

```bash
python3 scripts/python/hooks_validator.py --repo-root .
```

Verifica 7 capas: binary, opencode.json, plugin cargado, plugin compilado, hooks registrados, MCPs, test funcional.

### Auto-hooks: 19 triggers automaticos

| Trigger | Scripts ejecutados |
|---|---|
| `phase-complete:init` | health_check.py |
| `phase-complete:plan-indice` | cross_language + summarize_functions |
| `evidence:collected` | secret_scanner |
| `phase-complete:verdad` | code_quality + vulnerability_scanner |
| `scaffold:produced` | code_smells |
| `phase-complete:reanclaje` | test_coverage |
| `test:failed` | self_healing |
| `evidence:broken-captured` | evidence_replay bug |
| `evidence:post-fix-captured` | evidence_visual_diff compare |
| `flow:completed` | cross_flow_learning analyze |
| `scaffold:v3-produced` | post_script_gates check |
| `orchestrator:phase-start` | force_quality_gates check |
| `orchestrator:phase-complete` | force_quality_gates check |
| `agent:decision-proposed` | agent_decision_loop decide |
| `agent:script-needed` | script_generator create |
| `orchestrator:needs-input` | user_input_collector ask |
| ... | (19 total) |

---

## 22. Post-script Gates (v2.9.0)

15 gates validan contenido YAML despues de cada script:

| Script | Que valida | on_fail |
|---|---|---|
| `collect_evidence.py` | items (min 1) + hash_chain (min 64) | block |
| `score_evidence.py` | score (0-1) + metrics dict | warn |
| `generate_plan.py` | unidades (min 1) + topological_sort | block |
| `predict_impact.py` | predictions list | warn |
| `scaffold_impl.py` | files_to_create + files_to_modify | warn |
| `scaffold_v3.py` | files_to_create + commands + selection | block |
| `index_codebase.py` | files (min 1) | block |
| `code_quality.py` | total_files | warn |
| `test_coverage.py` | coverage_percentage (0-100) | warn |
| `vulnerability_scanner.py` | total_findings + tools_used | warn |
| `code_smells.py` | summary dict | warn |
| `full_audit.py` | summary.final_score + summary.grade | warn |
| `evidence_visual_diff.py` | snapshot_id + phase + files | warn |
| `evidence_replay.py` | total_events | warn |
| `cross_flow_learning.py` | flows_analyzed + patterns | warn |

---

## 23. Configuracion Centralizada apolo-config (v3.1.0)

```bash
# Ver configuracion
apolo config show

# Cambiar threshold
apolo config set --key gates.verdad.min_score --value 0.7

# Validar
apolo config validate
```

Configura: gates por fase, circuit breaker, scoring weights, BFS, code smells, scaffold_v3, cross_flow_learning, evidence_visual_diff, evidence_replay, auto_hooks, post_script_gates.

---

## 24. Scaffold v3 con Auto-select U-NN (v3.1.0)

```bash
# Auto-select U-NN (no requiere --unit-id)
apolo scaffold-v3 --plan plan.yaml --code-index ci.yaml --output sf.yaml --flowid APOLO-X

# Estrategias: topological_first (default), highest_impact, lowest_risk
```

Genera `files_to_create` concretos con templates + `commands` accionables (mkdir, create files, run tests, git commit).

---

## 25. Evidence Visual Diff + Replay + Cross-flow (v3.1.0)

### Evidence visual diff
```bash
apolo visual-diff capture --flowid X --phase baseline --files src/app.ts
apolo visual-diff capture --flowid X --phase broken --files src/app.ts
apolo visual-diff capture --flowid X --phase post-fix --files src/app.ts
apolo visual-diff compare --flowid X --output VISUAL-DIFF-REPORT.yaml
```

### Evidence replay
```bash
apolo evidence-replay timeline --flowid X
apolo evidence-replay bug --flowid X --verbose
apolo evidence-replay patterns --repo-root .
```

### Cross-flow learning
```bash
apolo cross-flow analyze --repo-root .
apolo cross-flow recommend --flowid X --phase verdad
apolo cross-flow similar --flowid X
```

---

## 26. Seguridad y Honesty (v3.5.0)

**El agente esta AMARRADO:**
- `force_quality_gates` bloquea si tests fallan o evidence invalida
- `agent_honesty_enforcer` bloquea si claims sin evidencia (fase 11)
- `post_script_gates` valida contenido YAML, no solo exit code
- `data_flow_validator` verifica artefactos despues de cada fase

**Pero esta GUIADO:**
- `agent_escape_hatch` ofrece salidas seguras con justificacion (limite 2-5 por tipo)
- `guided_recovery` diagnostica errores y propone fix command
- `self_healing_loop` auto-repara fallas seguras
- `apolo_natural` entiende lenguaje natural (30+ intents)

**El agente NO puede:**
- Declarar "done" sin ORCHESTRATOR-REPORT (honesty_enforcer bloquea)
- Declarar "tests_pass" sin eventos de test en telemetry
- Declarar "implemented" sin archivos en disco
- Modificar el FLUJO del orquestador (solo el PRODUCTO)
- Abusar de escape hatches (limite verificado antes de ofrecer)

---

## 27. Capability Assessment (v3.5.7)

### Resumen

```text
Capacidades implementadas: 179
Gaps identificados:         7
Cobertura de capacidades:   96%
```

### 8 Dimensiones

#### Dimension 1: Comprension de Codigo (6/6)
- [x] Indexacion AST | LSP integration | BFS multi-nivel | Busqueda semantica | Cross-language | Function summaries

#### Dimension 2: Generacion de Codigo (6/6)
- [x] Andamio | Gen tests | Refactoring | Code gen | Doc gen | Project templates

#### Dimension 3: Calidad y Seguridad (8/8)
- [x] Code quality | Coverage | Secret detection | Allowlist+SSRF | CVE scan | Code smells | Dead code | Full audit

#### Dimension 4: Orquestacion de Agentes (10/10)
- [x] State machine | Arbol D-NNN | Routing | Paralelizador | Self-healing | Auto-hooks | Post-script gates | Multi-agent | Smart rollback | MP prioritizer

#### Dimension 5: Evidencia y Decision (8/8)
- [x] Recoleccion hibrida | Scoring | Hash chain | E2E validation | Hooks validator | Visual diff | Replay | Cross-flow learning

#### Dimension 6: Infraestructura (5/8)
- [x] PyYAML | jsonschema | Atomic writes | Tool registry | CLI router
- [ ] GAP: Multi-nodo | Cache distribuido | Modo offline

#### Dimension 7: Experiencia (7/7)
- [x] Panel HTML | Context query | Registry recommend | Onboarding | Feedback loop | Interactive docs | Debug mode

#### Dimension 8: Ecosistema (2/6)
- [x] GitHub Actions | Pre-commit hooks
- [ ] GAP: Prometheus/Grafana | Multi-project | npm publish | VS Code extension

---

## 28. Changelog (actualizado v3.5.7)

### v3.5.7 — Fix post_script_gates + static_analyzer + README restaurado
### v3.5.6 — Fix integration_validator (0 fails)
### v3.5.5 — Fix 6 tests con grep patterns robustos
### v3.5.4 — Fix lsp_integration + static_analyzer + quick test
### v3.5.3 — UN comando lenguaje natural + fix dependencia circular
### v3.5.2 — 5 directivas: data_flow auto + honesty nativo + escape limits + classifier + scaffold nativo
### v3.5.1 — Escape hatch + guided recovery + self-healing loop
### v3.5.0 — Validadores: integration + dataflow + honesty + static + fix flow_verifier
### v3.4.0 — 4 GAPs: multi-agent, smart rollback, mp prioritizer, pre-commit hooks
### v3.3.0 — Orquestador REESCRITO (USA todos los super poderes)
### v3.2.0 — Orquestador automatico + decision loop + script gen + quality gates
### v3.1.0 — Config + Scaffold v3 + Visual diff + Replay + Cross-flow
### v2.9.0 — Hooks validator + auto-hooks + post-script gates + CLI router
### v2.8.1 — Fix full_audit + Feedback + Docs + Debug + Integration validation
### v2.8.0 — Vulnerability scanner + Code smells + Dead code + Full audit
### v2.7.0 — Cross-language + Function summaries + Code gen + Doc gen + Templates + Onboarding + GitHub Actions
### v2.6.0 — Self-healing + Test gen + Semantic search + Refactoring + LLM
### v2.5.0 — Atomic writes + Allowlist + Secret detection + Hash chain + BFS multi-nivel
### v2.4.0 — Code quality + Test coverage + LSP integration
### v2.3.0 — BFS multi-nivel + umbrales ajustados
### v2.2.0 — Code index + Score + Impact + Scaffold + Context query
### v2.1.0 — Core modules + routing declarativo + arbol D-NNN + tests TS
### v2.0.0 — Release inicial

| Version | Tests | Capability | Cambios principales |
|---|---|---|---|
| v2.0.0 | 40 | 30% | Release inicial |
| v2.6.0 | 84 | 75% | Self-healing + semantic search |
| v2.9.0 | 133 | 90% | Hooks + auto-hooks + gates |
| v3.2.0 | 160+ | 97% | Orquestador automatico |
| v3.5.0 | 170+ | 98% | Validadores de integracion |
| v3.5.3 | 178+ | 98% | UN comando natural |
| **v3.5.7** | **179** | **96%** | **0 fails + README restaurado** |

---

## 29. Licencia

MIT

### Contribuir

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
bash apolo-full-test.sh
python3 scripts/python/hooks_validator.py --repo-root .
python3 scripts/python/flow_verifier.py verify --repo-root .
```

---

> **APOLO Dynamic Flow v3.5.7** — UN sistema unificado. UN comando. 179 tests, 0 fails.
> El agente esta AMARRADO pero GUIADO. 70 scripts Python. 65+ comandos en CLI router.
> 19 auto-hooks + 15 post-script gates + 7 force quality gates.
> Todas las integraciones son automaticas en el flujo del orquestador.

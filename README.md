# APOLO Dynamic Flow

> **Plugin de orquestación de agentes para OpenCode** — Agnóstico al lenguaje (HTML, CSS, JS, React, Rust, C++, PHP, TS, Java, Go, Python). 3 capas: Infrastructure → Deterministic → Intelligence. 90+ tests, 76% capability coverage, 0 fallos.

[![Tests](https://img.shields.io/badge/tests-90%2F90%20passing-brightgreen)](#14-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Version](https://img.shields.io/badge/version-2.7.0-blue)](#changelog)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)

---

## Tabla de contenidos

1. [Qué es este plugin](#1-qué-es-este-plugin)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Instalación](#3-instalación)
4. [Arquitectura de 3 capas](#4-arquitectura-de-3-capas)
5. [Intelligent Adaptation (v2.6.0)](#5-intelligent-adaptation-v260)
6. [Code Generation & Docs (v2.7.0)](#6-code-generation--docs-v270)
7. [Project Templates (v2.7.0)](#7-project-templates-v270)
8. [Onboarding (v2.7.0)](#8-onboarding-v270)
9. [GitHub Actions (v2.7.0)](#9-github-actions-v270)
10. [Cross-Language Analysis (v2.6.6)](#10-cross-language-analysis-v266)
11. [Function Summaries (v2.6.6)](#11-function-summaries-v266)
12. [LLM Bridge](#12-llm-bridge)
13. [Agnóstico al lenguaje](#13-agnóstico-al-lenguaje)
14. [Integración con OpenCode](#14-integración-con-opencode)
15. [Estructura completa](#15-estructura-completa)
16. [CLI apolo-inspect.sh](#16-cli-apolo-inspectsh)
17. [Panel de telemetría](#17-panel-de-telemetría)
18. [Tests](#18-tests)
19. [Troubleshooting](#19-troubleshooting)
20. [Cómo funciona internamente](#20-cómo-funciona-internamente)
21. [Changelog](#changelog)
22. [Licencia](#licencia)

---

## 1. Qué es este plugin

`apolo-dynamic-flow` es un plugin TypeScript para OpenCode que **reemplaza a `apolo-flow-guardian.ts`**. Orquesta agentes con capacidades en 3 capas:

### Infrastructure Layer (v2.0-v2.4)
- **State machine explícita** con transiciones legales y gates por fase
- **Loop dinámico con circuit breaker adaptativo** — cada fase tiene `max` iteraciones
- **Árbol de decisión D-NNN** — reemplaza "plan tras plan" por árbol finito
- **Recolección híbrida de evidencia** (v2.2.1) — scripts Python + agente aportan evidencia
- **Planes con 3 modos** (v2.2.1) — deterministic, hybrid, manual
- **Tests automáticos tras cada cambio** con rollback automático
- **Absorción automática de tools externas** — MCPs, skills, plugins, scripts
- **Absorción de skills externas** (v2.2.0) — URLs, GitHub repos, hubs especializados
- **Routing declarativo** — `routing-rules.json` con 10 reglas editables
- **Atomic writes + file locks** (v2.3.0) — `tempfile + os.fsync + os.replace` + `fcntl.flock`
- **PyYAML hard + jsonschema hard** (v2.3.0)
- **Allowlist de orígenes + SSRF protection** (v2.4.0)
- **Secret detection** (v2.4.0) — 11 patrones con redacción automática
- **Hash chain en audit log** (v2.4.0) — inmutabilidad verificable
- **Telemetría append-only** + panel HTML

### Deterministic Layer (v2.0-v2.5)
- **BFS multi-nivel** (v2.5.0) — `predict_impact.py` detecta dependencias a profundidad 5
- **Code quality multi-lenguaje** (v2.5.0) — bandit, radon, eslint-security, gosec, cppcheck
- **Test coverage por símbolo** (v2.5.0) — coverage.py, nyc, go test -cover
- **LSP integration** (v2.5.0) — find-references, go-to-definition, diagnostics (7 LSPs)
- **Code indexing** (v2.2.0) — AST-based indexer para Python, TS/JS, Go
- **Evidence scoring** (v2.2.0) — 6 métricas (coverage, freshness, depth, conflict, redundancy, schema)
- **Scaffold** (v2.2.0) — andamio de implementación con contracts, checkpoints, edit order

### Intelligence Layer (v2.6.0-v2.7.0)
- **Self-healing** (v2.6.0) — `self_healing.py` aprende de fallos, ajusta routing
- **Test generation** (v2.6.0) — `generate_tests.py` genera tests para funciones sin cobertura
- **Semantic search** (v2.6.0) — `semantic_search.py` búsqueda por significado (embeddings/TF-IDF)
- **Refactoring automático** (v2.6.0) — `refactor_engine.py` detecta code smells
- **LLM bridge** (v2.6.0) — `llm_bridge.py` interface universal para MiniMax/OpenAI API
- **Cross-language analysis** (v2.6.6) — `cross_language_analyzer.py` detecta dependencias entre lenguajes
- **Function summaries** (v2.6.6) — `summarize_functions.py` genera resumen de 1 línea por función
- **Code generation** (v2.7.0) — `code_generator.py` escribe funciones/classes completas en 8 lenguajes
- **Doc generation** (v2.7.0) — `doc_generator.py` genera docstrings, README sections, API docs
- **Project templates** (v2.7.0) — `project_templates.py` crea scaffolds de proyecto (8 lenguajes)
- **Onboarding** (v2.7.0) — `onboarding.py` asistente de configuración inicial interactivo
- **GitHub Actions** (v2.7.0) — `github_actions.py` genera workflows CI/CD

---

## 2. Prerrequisitos

| Herramienta | Versión mínima | Instalar |
|---|---|---|
| **Node.js** | 18.0.0 | `sudo apt install -y nodejs` |
| **npm** | 9.0.0 | `sudo apt install -y npm` |
| **Python 3** | 3.10 | `sudo apt install -y python3` |
| **PyYAML** | 6.0 (hard) | `pip3 install PyYAML` |
| **jsonschema** | 4.0 (hard) | `pip3 install jsonschema` |
| **curl, git** | cualquiera | `sudo apt install -y curl git` |

Opcional: `pip3 install bandit radon coverage pytest`

LLM (opcional): configurar `OPENAI_API_BASE` y `MINIMAX_API_KEY` en el entorno.

Auto-instalación de dependencias:
```bash
python3 scripts/python/install_deps.py
```

---

## 3. Instalación

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
```

Onboarding guiado:
```bash
python3 scripts/python/onboarding.py --repo-root .
```

---

## 4. Arquitectura de 3 capas

```
┌──────────────────────────────────────────────────┐
│          Intelligence Layer (v2.6.0-v2.7.0)      │
│  ┌───────────┐ ┌───────────┐ ┌────────────┐     │
│  │Self-Healing│ │Test Gen   │ │Semantic    │     │
│  │Engine      │ │Engine     │ │Search      │     │
│  └─────┬─────┘ └─────┬─────┘ └─────┬──────┘     │
│  ┌─────┴─────┐ ┌─────┴─────┐ ┌─────┴──────┐     │
│  │Refactor   │ │LLM Bridge │ │Cross-Lang  │     │
│  │Engine     │ │(MiniMax/  │ │Analyzer    │     │
│  │           │ │ OpenAI)   │ │(v2.6.6)    │     │
│  └───────────┘ └───────────┘ └────────────┘     │
│  ┌──────────────────────────────────────────┐    │
│  │  Function Summaries (v2.6.6)            │    │
│  ├──────────────────────────────────────────┤    │
│  │  Code Generator (v2.7.0)                │    │
│  │  Doc Generator (v2.7.0)                 │    │
│  │  Project Templates (v2.7.0)             │    │
│  │  Onboarding (v2.7.0)                    │    │
│  │  GitHub Actions (v2.7.0)                │    │
│  └──────────────────────────────────────────┘    │
├──────────────────────────────────────────────────┤
│        Deterministic Layer (v2.0-v2.5)           │
│  Evidence Collector, Plan Generator,             │
│  Impact Predictor (BFS), Scaffold,               │
│  Code Quality, Test Coverage, LSP                │
├──────────────────────────────────────────────────┤
│        Infrastructure Layer (v2.3-v2.4)          │
│  State Machine, Routing Rules, Atomic Writes,    │
│  File Locks, Allowlist, Secret Detection,        │
│  Hash Chain, Telemetry, Panel HTML               │
└──────────────────────────────────────────────────┘
```

---

## 5. Intelligent Adaptation (v2.6.0)

### Self-Healing
`self_healing.py` analiza `telemetry.jsonl`, computa success rates por (agent, phase), sugiere ajustes de routing.

### Test Generation
`generate_tests.py` encuentra funciones sin test, genera stubs deterministas o tests significativos con LLM.

### Semantic Search
`semantic_search.py` búsqueda por significado usando embeddings (LLM) o TF-IDF (determinista).

### Refactoring
`refactor_engine.py` detecta long functions, high complexity, god classes. Genera código refactorizado con LLM.

---

## 6. Code Generation & Docs (v2.7.0)

### Code Generator

`code_generator.py` escribe funciones/classes completas desde especificaciones:

- **8 lenguajes**: Python, TypeScript, Go, Rust, Java, C++, PHP, JavaScript
- Si LLM disponible: genera código inteligente y contextual
- Si no: usa plantillas deterministas por lenguaje

```bash
# Generar función Python
python3 scripts/python/code_generator.py --language python --type function --name "calculate_tax" --args "amount,rate" --description "Calculate tax"

# Generar clase TypeScript
python3 scripts/python/code_generator.py --language typescript --type class --name "UserService" --methods "getUser,createUser,deleteUser"

# Generar struct Go
python3 scripts/python/code_generator.py --language go --type class --name "Server" --methods "Start,Stop,HandleRequest"
```

### Doc Generator

`doc_generator.py` genera documentación automáticamente:

- **Docstrings**: detecta funciones sin documentación y genera docstrings (Google style, JSDoc, GoDoc, RustDoc, JavaDoc)
- **README sections**: genera secciones de Installation, Usage, API, Contributing
- **API docs**: detecta REST endpoints y genera documentación OpenAPI-style
- **Changelog**: genera entradas de changelog desde git log

```bash
# Generar docstrings para funciones sin documentación
python3 scripts/python/doc_generator.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml --type docstrings

# Generar sección de README
python3 scripts/python/doc_generator.py --type readme-section --section installation

# Generar API docs
python3 scripts/python/doc_generator.py --repo-root . --type api-docs --output API-DOCS.yaml

# Generar changelog desde git log
python3 scripts/python/doc_generator.py --repo-root . --type changelog
```

---

## 7. Project Templates (v2.7.0)

`project_templates.py` crea scaffolds de proyecto completos para 8 lenguajes/frameworks:

| Template | Descripción | Lenguajes |
|---|---|---|
| `nextjs` | Next.js app con TypeScript, Tailwind, Jest, Playwright | TS, JS, CSS |
| `go-api` | Go REST API con chi router, testify, golangci-lint | Go |
| `python-cli` | Python CLI con Click, pytest, black, mypy | Python |
| `react-native` | React Native mobile app con TypeScript, Jest | TS, JS |
| `rust-cli` | Rust CLI con clap, tokio, criterion benchmarks | Rust |
| `java-spring` | Java Spring Boot REST API con JUnit, Maven | Java |
| `php-laravel` | PHP Laravel API con PHPUnit | PHP |
| `cpp-cmake` | C++ project con CMake, GoogleTest | C++ |

```bash
# Listar plantillas disponibles
python3 scripts/python/project_templates.py --list

# Crear proyecto Next.js
python3 scripts/python/project_templates.py --template nextjs --output /tmp/my-nextjs-app --name my-app

# Crear proyecto Go API
python3 scripts/python/project_templates.py --template go-api --output /tmp/my-go-api --name my-api

# Crear proyecto Python CLI
python3 scripts/python/project_templates.py --template python-cli --output /tmp/my-cli --name my-cli
```

Cada plantilla incluye: estructura de directorios, archivos base (main, config, tests), `.gitignore`, `README.md`.

---

## 8. Onboarding (v2.7.0)

`onboarding.py` es un asistente de configuración inicial:

1. Verifica prerrequisitos (Node, npm, Python, PyYAML, jsonschema, curl, git)
2. Pregunta tipo de proyecto (web, api, mobile, cli, general)
3. Sugiere MCPs según tipo de proyecto
4. Sugiere skills según tipo de proyecto
5. Genera `opencode.json` configurado
6. Crea flow de ejemplo

```bash
# Modo interactivo
python3 scripts/python/onboarding.py --repo-root .

# Modo automático (sin prompts)
python3 scripts/python/onboarding.py --repo-root . --non-interactive

# Con npm
npm run onboard
```

---

## 9. GitHub Actions (v2.7.0)

`github_actions.py` genera workflows de CI/CD:

- **ci.yml**: Tests Python + TypeScript en cada PR/push
- **security.yml**: Bandit + Safety scan semanal
- **release.yml**: Auto-release en tags `v*`

```bash
# Generar workflows
python3 scripts/python/github_actions.py --repo-root . --output .github/workflows/

# Con npm
npm run generate-actions
```

---

## 10. Cross-Language Analysis (v2.6.6)

`cross_language_analyzer.py` detecta dependencias entre lenguajes:

- Python → Go (subprocess, gRPC)
- Python → C/C++/Rust (ctypes, cffi, FFI)
- JS/TS → Go/Python/any (fetch, axios, HTTP)
- JS/TS → C (native modules .node/.so/.dll)
- Go → any (exec.Command)
- Shell → any (exec, system())
- gRPC (.proto) → service definitions
- REST API endpoints en cualquier lenguaje

```bash
python3 scripts/python/cross_language_analyzer.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
```

---

## 11. Function Summaries (v2.6.6)

`summarize_functions.py` genera un resumen de 1 línea para cada función:

1. **Docstrings**: parsea `"""`, `* `, `//` cerca de la función
2. **LLM**: si disponible, usa `llm_bridge.analyze_code()`
3. **Heurísticas**: analiza verbos en el nombre (get→"Gets X", validate→"Validates X"), return statements, patrones en el cuerpo

```bash
python3 scripts/python/summarize_functions.py --repo-root . --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml
```

---

## 12. LLM Bridge

`llm_bridge.py` es el interface universal para LLM:

- Lee `OPENAI_API_BASE` y `MINIMAX_API_KEY` del entorno
- Usa `curl` para llamadas (sin dependencias Python externas)
- Cache en `/tmp/apolo-llm-cache.json`
- Si no hay API key, todo funciona con fallback determinista

```bash
# Verificar disponibilidad
python3 scripts/python/llm_bridge.py

# Usar desde CLI
python3 scripts/python/llm_bridge.py --prompt "Analyze this function for bugs"
```

---

## 13. Agnóstico al lenguaje

Soporta: **HTML, CSS, JavaScript, TypeScript, React, Rust, C++, PHP, Java, Go, Python**.

| Componente | Lenguajes soportados |
|---|---|
| index_codebase.py | Python (AST), TS/JS (regex), Go (regex) |
| cross_language_analyzer.py | **Todos** — detecta llamadas entre cualquier par de lenguajes |
| summarize_functions.py | **Todos** — docstrings + heurísticas + LLM |
| code_generator.py | Python, TS, Go, Rust, Java, C++, PHP, JS |
| doc_generator.py | Python, TS, Go, Rust, Java |
| project_templates.py | Next.js, Go, Python, React Native, Rust, Java, PHP, C++ |
| code_quality.py | Python (bandit, radon), JS/TS (eslint-security), Go (gosec), C++ (cppcheck) |
| test_coverage.py | Python (coverage.py), JS/TS (nyc), Go (go test -cover) |
| lsp_integration.py | TS, Python, Go, Rust, Java, C++, PHP (7 LSPs) |
| generate_tests.py | Python, TS/JS, Go, Java, Rust, PHP |
| refactor_engine.py | Multi-lenguaje (detecta por extensión) |

---

## 14. Integración con OpenCode

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["./apolo-dynamic-flow/plugin/index.ts"],
  "mcp": {
    "@playwright/mcp": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp@latest"],
      "enabled": true
    }
  }
}
```

### Tools expuestas al orquestador

- `apolo.flow.init` — inicializa un flow nuevo
- `apolo.flow.tick` — ejecuta una iteración del loop dinámico
- `apolo.evidence.collect` — dispara recolección híbrida
- `apolo.plan.generate` — genera plan dinámico (3 modos)
- `apolo.tests.run` — ejecuta tests tras cambios
- `apolo.tools.absorb` — descubre y registra tools externas
- `apolo.context.query` — consulta activa al sistema
- `apolo.registry.recommend` — recomienda tools con scoring
- `apolo.health.check` — hot reload de tools

---

## 15. Estructura completa

```
apolo-dynamic-flow/
├── install.sh / README.md / opencode.json / package.json (v2.7.0)
├── routing-rules.json / security_config.yaml / apolo-full-test.sh
├── plugin/             # 18 módulos TypeScript
│   ├── core/           # runtime-logger, router, loop-engine-tree, micro-test-runner
│   ├── absorbers/      # mcp-loader
│   └── parallel/       # hypothesis-runner
├── schemas/            # 12 schemas (8 YAML + 4 JSON)
├── templates/          # 5 templates YAML
├── scripts/
│   ├── python/         # 30 scripts Python
│   │   ├── common.py (PyYAML hard + atomic writes + file locks)
│   │   ├── collect_evidence.py (híbrido), generate_plan.py (3 modos)
│   │   ├── index_codebase.py, score_evidence.py, predict_impact.py (BFS)
│   │   ├── scaffold_impl.py, context_query.py, registry_recommend.py
│   │   ├── health_check.py, absorb_external_skills.py (allowlist)
│   │   ├── secret_scanner.py, code_quality.py, test_coverage.py
│   │   ├── lsp_integration.py, llm_bridge.py, self_healing.py
│   │   ├── generate_tests.py, semantic_search.py, refactor_engine.py
│   │   ├── install_deps.py (auto-instalador)
│   │   ├── cross_language_analyzer.py (v2.6.6)
│   │   ├── summarize_functions.py (v2.6.6)
│   │   ├── code_generator.py (NUEVO v2.7.0)
│   │   ├── doc_generator.py (NUEVO v2.7.0)
│   │   ├── project_templates.py (NUEVO v2.7.0)
│   │   ├── onboarding.py (NUEVO v2.7.0)
│   │   └── github_actions.py (NUEVO v2.7.0)
│   └── bash/apolo-inspect.sh
├── panel/              # Panel HTML (7 tabs, puerto 8765)
└── tests/              # 8 suites (90+ tests totales)
```

---

## 16. CLI apolo-inspect.sh

```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [--flowid FLOW] [--repo-root PATH]
```

Subcomandos: init-flow, absorb, state, tools, blocks, telemetry, evidence, plan, health, all, serve-panel, test, help

---

## 17. Panel de telemetría

```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI
# → http://localhost:8765/
```

7 tabs: Overview, Timeline, Loops, Blocks, Tests, Tools, Tokens. Auto-refresh cada 5s.

---

## 18. Tests

```bash
# Tests Python (5 suites + atomic + security + quality + intelligence)
python3 tests/run_all_tests.py
python3 tests/test_atomic.py
python3 tests/test_security.py
python3 tests/test_quality.py
python3 tests/test_intelligence.py

# Tests TypeScript (35 tests)
npx tsc && node --test dist/tests/plugin.test.js

# Test exhaustivo completo (90+ tests + capability assessment)
bash apolo-full-test.sh

# Todo con npm
npm run test:all
```

| Suite | Tests | Qué valida |
|---|---:|---|
| Python (5 suites) | 42 | FSM, loop, blocks, tools, scripts |
| Atomic (v2.3.0) | 9 | Atomicidad, concurrency, YAML |
| Security (v2.4.0) | 12 | Allowlist, secretos, hash chain |
| Quality (v2.5.0) | 8 | BFS, code quality, coverage, LSP |
| Intelligence (v2.6.0) | 12 | LLM bridge, self-healing, test gen, semantic search, refactoring |
| TypeScript | 35 | RuntimeLogger, Router, LoopEngine, MicroTest, MCP, Hypothesis, ContextQuery |
| Funcionales | 25+ | Todos los scripts Python + CLI + E2E + cross-lang + summaries + codegen + docs + templates + onboarding + GH Actions |
| **Total** | **90+** | |

**Resultado actual: 90/90 tests pasan, 0 fallos. Cobertura de capacidades: 85%+.**

---

## 19. Troubleshooting

### `Error: Configuration is invalid at opencode.json`
`plugin` debe ser array: `"plugin": ["./plugin/index.ts"]`

### `OSError: Address already in use`
`fuser -k 8765/tcp` o `PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel ...`

### LLM no disponible
El sistema funciona 100% sin LLM. Configurar `MINIMAX_API_KEY` y `OPENAI_API_BASE` para activar capacidades de inteligencia.

### Instalar dependencias automáticamente
```bash
python3 scripts/python/install_deps.py
```

---

## 20. Cómo funciona internamente

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

### Arquitectura de 3 capas

```
Intelligence (v2.6.0-v2.7.0): self-healing, test gen, semantic search, refactoring,
  LLM bridge, cross-language, function summaries, code gen, doc gen,
  project templates, onboarding, GitHub Actions
Deterministic (v2.0-v2.5): evidence, plans, impact (BFS), scaffold,
  quality, coverage, LSP
Infrastructure (v2.3-v2.4): atomic writes, locks, allowlist, secrets,
  hash chain, telemetry, panel
```

---

## Changelog

### v2.7.0

- **Code generation** (`code_generator.py`): genera funciones/classes completas en 8 lenguajes (Python, TS, Go, Rust, Java, C++, PHP, JS). Si LLM disponible, genera código inteligente. Si no, usa plantillas deterministas.
- **Doc generation** (`doc_generator.py`): genera docstrings (Google style, JSDoc, GoDoc, RustDoc, JavaDoc), README sections (installation, usage, API, contributing), API docs (REST endpoints), changelog desde git log.
- **Project templates** (`project_templates.py`): crea scaffolds de proyecto completos para 8 frameworks (Next.js, Go API, Python CLI, React Native, Rust CLI, Java Spring, PHP Laravel, C++ CMake). Cada plantilla incluye estructura, archivos base, tests, .gitignore, README.
- **Onboarding** (`onboarding.py`): asistente de configuración inicial interactivo. Verifica prerrequisitos, sugiere MCPs y skills según tipo de proyecto, genera opencode.json, crea flow de ejemplo.
- **GitHub Actions** (`github_actions.py`): genera workflows CI/CD (ci.yml con tests Python+TS, security.yml con bandit+safety, release.yml con auto-release).
- **5 gaps cerrados**: generación de código, generación de documentación, plantillas de proyecto, onboarding guiado, GitHub Actions.
- **README completo** sin truncar.

### v2.6.6
- Cross-language analysis, function summaries. 2 gaps cerrados.

### v2.6.0-v2.6.5
- Self-healing, test generation, semantic search, refactoring, LLM bridge. 12 tests de inteligencia. Fixes de test exhaustivo.

### v2.5.x
- BFS multi-nivel, code quality, test coverage, LSP integration.

### v2.4.x
- Allowlist de orígenes, secret detection (11 patrones), hash chain, sandboxing.

### v2.3.0
- PyYAML hard, jsonschema hard, atomic writes, file locks.

### v2.2.x
- 4 gaps cerrados, gestión activa de tools, absorción externa, recolección híbrida, 3 modos de planes.

### v2.1.0
- Tests TypeScript, JSON schemas estrictos, routing declarativo.

### v2.0.0
- Release inicial.

---

## Licencia

MIT

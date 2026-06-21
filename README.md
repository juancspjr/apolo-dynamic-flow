# APOLO Dynamic Flow

> **Plugin de orquestación de agentes para OpenCode** con flujos dinámicos, recolección híbrida de evidencia, planes con 3 modos, tests automáticos, absorción de tools externas, routing declarativo, atomic writes, file locks, allowlist, secret detection, hash chain, multi-level impact prediction, code quality, test coverage, LSP, self-healing, test generation, semantic search, refactoring, LLM bridge, **cross-language analysis y function summaries** (v2.6.6).

[![Tests](https://img.shields.io/badge/tests-84%2F84%20passing-brightgreen)](#13-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Version](https://img.shields.io/badge/version-2.6.6-blue)](#changelog)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)

---

## Tabla de contenidos

1. [Qué es este plugin](#1-qué-es-este-plugin)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Instalación](#3-instalación)
4. [Arquitectura de 3 capas](#4-arquitectura-de-3-capas)
5. [Intelligent Adaptation (v2.6.0)](#5-intelligent-adaptation-v260)
6. [Cross-Language Analysis (v2.6.6)](#6-cross-language-analysis-v266)
7. [Function Summaries (v2.6.6)](#7-function-summaries-v266)
8. [LLM Bridge](#8-llm-bridge)
9. [Agnóstico al lenguaje](#9-agnóstico-al-lenguaje)
10. [Integración con OpenCode](#10-integración-con-opencode)
11. [Estructura completa](#11-estructura-completa)
12. [CLI apolo-inspect.sh](#12-cli-apolo-inspectsh)
13. [Panel de telemetría](#13-panel-de-telemetría)
14. [Tests](#14-tests)
15. [Troubleshooting](#15-troubleshooting)
16. [Changelog](#changelog)
17. [Licencia](#licencia)

---

## 1. Qué es este plugin

`apolo-dynamic-flow` es un plugin TypeScript para OpenCode que **reemplaza a `apolo-flow-guardian.ts`**. Orquesta agentes con:

- **State machine explícita** con transiciones legales y gates por fase.
- **Loop dinámico con circuit breaker adaptativo** — cada fase tiene `max` iteraciones.
- **Árbol de decisión D-NNN** — reemplaza "plan tras plan" por árbol finito.
- **Recolección híbrida de evidencia** (v2.2.1) — scripts Python + agente aportan evidencia.
- **Planes con 3 modos** (v2.2.1) — deterministic, hybrid, manual.
- **Tests automáticos tras cada cambio** con rollback automático.
- **Absorción automática de tools externas** — MCPs, skills, plugins, scripts.
- **Absorción de skills externas** (v2.2.0) — URLs, GitHub repos, hubs especializados.
- **Routing declarativo** — `routing-rules.json` con 10 reglas editables.
- **Atomic writes + file locks** (v2.3.0) — `tempfile + os.fsync + os.replace` + `fcntl.flock`.
- **PyYAML hard + jsonschema hard** (v2.3.0).
- **Allowlist de orígenes + SSRF protection** (v2.4.0).
- **Secret detection** (v2.4.0) — 11 patrones con redacción automática.
- **Hash chain en audit log** (v2.4.0) — inmutabilidad verificable.
- **BFS multi-nivel** (v2.5.0) — `predict_impact.py` detecta dependencias a profundidad 5.
- **Code quality multi-lenguaje** (v2.5.0) — bandit, radon, eslint-security, gosec, cppcheck.
- **Test coverage por símbolo** (v2.5.0) — coverage.py, nyc, go test -cover.
- **LSP integration** (v2.5.0) — find-references, go-to-definition, diagnostics (7 LSPs).
- **Self-healing** (v2.6.0) — `self_healing.py` aprende de fallos, ajusta routing.
- **Test generation** (v2.6.0) — `generate_tests.py` genera tests para funciones sin cobertura.
- **Semantic search** (v2.6.0) — `semantic_search.py` búsqueda por significado (embeddings/TF-IDF).
- **Refactoring automático** (v2.6.0) — `refactor_engine.py` detecta code smells.
- **LLM bridge** (v2.6.0) — `llm_bridge.py` interface universal para MiniMax/OpenAI API.
- **Cross-language analysis** (v2.6.6) — `cross_language_analyzer.py` detecta dependencias entre lenguajes.
- **Function summaries** (v2.6.6) — `summarize_functions.py` genera resumen de 1 línea por función.

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

---

## 3. Instalación

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
```

---

## 4. Arquitectura de 3 capas

```
┌──────────────────────────────────────────────────┐
│          Intelligence Layer (v2.6.0-v2.6.6)      │
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
Analiza `telemetry.jsonl`, computa success rates por (agent, phase), sugiere ajustes de routing.

### Test Generation
Encuentra funciones sin test, genera stubs deterministas o tests significativos con LLM.

### Semantic Search
Búsqueda por significado usando embeddings (LLM) o TF-IDF (determinista).

### Refactoring
Detecta long functions, high complexity, god classes. Genera código refactorizado con LLM.

---

## 6. Cross-Language Analysis (v2.6.6)

`cross_language_analyzer.py` detecta dependencias entre lenguajes:

- **Python → Go**: subprocess, gRPC
- **Python → C/C++/Rust**: ctypes, cffi, FFI
- **JS/TS → Go/Python/any**: fetch, axios, HTTP requests
- **JS/TS → C**: native modules (.node, .so, .dll)
- **Go → any**: exec.Command
- **Shell → any**: exec, system()
- **gRPC**: .proto service definitions → clientes/servidores
- **REST API**: endpoints en cualquier lenguaje

```bash
python3 scripts/python/cross_language_analyzer.py \
  --repo-root . \
  --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \
  --output CROSS-LANGUAGE-MAP.yaml
```

Genera `CROSS-LANGUAGE-MAP.yaml` con:
- `adjacency_matrix`: mapa de qué lenguaje llama a cuál
- `critical_nodes`: lenguajes que dependen de 2+ otros
- `calls`: lista de todas las llamadas cross-lenguaje detectadas

---

## 7. Function Summaries (v2.6.6)

`summarize_functions.py` genera un resumen de 1 línea para cada función:

**Si LLM disponible**: usa `llm_bridge.analyze_code()` para generar resúmenes inteligentes.

**Si no (determinista)**: usa heurísticas:
1. Parsea docstrings (Python `"""`, JS `* `, Go `//`)
2. Analiza verbos en el nombre (get, set, create, delete, validate, parse, etc.)
3. Analiza `return` statements para inferir propósito
4. Analiza patrones en el cuerpo (SQL, HTTP, file I/O, loops, conditionals)

```bash
python3 scripts/python/summarize_functions.py \
  --repo-root . \
  --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \
  --output FUNCTION-SUMMARIES.yaml
```

Ejemplos de resúmenes generados:
- `init_flow` → "Initializes flow state"
- `validate_email` → "Validates email"
- `get_user_by_id` → "Gets user by id from source"
- `process_payment` → "Processes payment data"

---

## 8. LLM Bridge

`llm_bridge.py` es el interface universal para LLM:

- Lee `OPENAI_API_BASE` y `MINIMAX_API_KEY` del entorno
- Usa `curl` para llamadas (sin dependencias Python externas)
- Cache en `/tmp/apolo-llm-cache.json`
- Si no hay API key, todo funciona con fallback determinista

---

## 9. Agnóstico al lenguaje

Soporta: **HTML, CSS, JavaScript, TypeScript, React, Rust, C++, PHP, Java, Go, Python**.

| Componente | Lenguajes soportados |
|---|---|
| index_codebase.py | Python (AST), TS/JS (regex), Go (regex) |
| cross_language_analyzer.py | **Todos** — detecta llamadas entre cualquier par de lenguajes |
| summarize_functions.py | **Todos** — docstrings + heurísticas + LLM |
| code_quality.py | Python (bandit, radon), JS/TS (eslint-security), Go (gosec), C++ (cppcheck) |
| test_coverage.py | Python (coverage.py), JS/TS (nyc), Go (go test -cover) |
| lsp_integration.py | TS, Python, Go, Rust, Java, C++, PHP (7 LSPs) |
| generate_tests.py | Python, TS/JS, Go, Java, Rust, PHP |
| refactor_engine.py | Multi-lenguaje (detecta por extensión) |

---

## 10. Integración con OpenCode

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

---

## 11. Estructura completa

```
apolo-dynamic-flow/
├── install.sh / README.md / opencode.json / package.json (v2.6.6)
├── routing-rules.json / security_config.yaml / apolo-full-test.sh
├── plugin/             # 18 módulos TypeScript
│   ├── core/           # runtime-logger, router, loop-engine-tree, micro-test-runner
│   ├── absorbers/      # mcp-loader
│   └── parallel/       # hypothesis-runner
├── schemas/            # 12 schemas (8 YAML + 4 JSON)
├── templates/          # 5 templates YAML
├── scripts/
│   ├── python/         # 25 scripts Python
│   │   ├── common.py (PyYAML hard + atomic writes + file locks)
│   │   ├── collect_evidence.py (híbrido), generate_plan.py (3 modos)
│   │   ├── index_codebase.py, score_evidence.py, predict_impact.py (BFS)
│   │   ├── scaffold_impl.py, context_query.py, registry_recommend.py
│   │   ├── health_check.py, absorb_external_skills.py (allowlist)
│   │   ├── secret_scanner.py, code_quality.py, test_coverage.py
│   │   ├── lsp_integration.py, llm_bridge.py, self_healing.py
│   │   ├── generate_tests.py, semantic_search.py, refactor_engine.py
│   │   ├── install_deps.py (auto-instalador)
│   │   ├── cross_language_analyzer.py (NUEVO v2.6.6)
│   │   └── summarize_functions.py (NUEVO v2.6.6)
│   └── bash/apolo-inspect.sh
├── panel/              # Panel HTML (7 tabs, puerto 8765)
└── tests/              # 8 suites (84+ tests totales)
```

---

## 12. CLI apolo-inspect.sh

```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [--flowid FLOW] [--repo-root PATH]
```

Subcomandos: init-flow, absorb, state, tools, blocks, telemetry, evidence, plan, health, all, serve-panel, test, help

---

## 13. Panel de telemetría

```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI
# → http://localhost:8765/
```

7 tabs: Overview, Timeline, Loops, Blocks, Tests, Tools, Tokens. Auto-refresh cada 5s.

---

## 14. Tests

```bash
# Tests Python (5 suites + atomic + security + quality + intelligence)
python3 tests/run_all_tests.py
python3 tests/test_atomic.py
python3 tests/test_security.py
python3 tests/test_quality.py
python3 tests/test_intelligence.py

# Tests TypeScript (35 tests)
npx tsc && node --test dist/tests/plugin.test.js

# Test exhaustivo completo (84+ tests + capability assessment)
bash apolo-full-test.sh
```

| Suite | Tests | Qué valida |
|---|---:|---|
| Python (5 suites) | 42 | FSM, loop, blocks, tools, scripts |
| Atomic (v2.3.0) | 9 | Atomicidad, concurrency, YAML |
| Security (v2.4.0) | 12 | Allowlist, secretos, hash chain |
| Quality (v2.5.0) | 8 | BFS, code quality, coverage, LSP |
| Intelligence (v2.6.0) | 12 | LLM bridge, self-healing, test gen, semantic search, refactoring |
| TypeScript | 35 | RuntimeLogger, Router, LoopEngine, MicroTest, MCP, Hypothesis, ContextQuery |
| Funcionales (v2.6.6) | 20 | Todos los scripts Python + CLI + E2E |
| **Total** | **84+** | |

**Resultado actual: 84/84 tests pasan, 0 fallos. Cobertura de capacidades: 76%.**

---

## 15. Troubleshooting

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

## Changelog

### v2.6.6

- **Cross-language analysis** (`cross_language_analyzer.py`): detecta dependencias entre lenguajes (Python→Go, JS→Go, Python→C, gRPC, REST, FFI). Genera `CROSS-LANGUAGE-MAP.yaml` con matriz de adyacencia y nodos críticos.
- **Function summaries** (`summarize_functions.py`): genera resumen de 1 línea por función. Si LLM disponible usa análisis inteligente. Si no, usa heurísticas deterministas (docstrings, verbos en nombre, return statements, patrones en cuerpo).
- **2 gaps cerrados**: "Comprensión cross-lenguaje" y "Resumen automático de funciones".
- **84/84 tests pasan**, 0 fallos. Cobertura de capacidades: 76%.
- **README completo** con todas las secciones actualizadas.

### v2.6.5
- Rewrite completo de apolo-full-test.sh con todos los fixes integrados.

### v2.6.4
- Fix verify_hash_chain: Path() en vez de str.

### v2.6.3
- Fix test_hash_chain.py syntax. Fix code_quality test resilience.

### v2.6.2
- Fix FASE 6 (--flowid). Auto-instalador de dependencias (install_deps.py).

### v2.6.1
- Fix hash chain test. Fix FASE 8.5. Fix priorización. README completo.

### v2.6.0
- Self-healing, test generation, semantic search, refactoring, LLM bridge. 12 tests de inteligencia.

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

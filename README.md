# APOLO Dynamic Flow

> **Plugin de orquestación de agentes para OpenCode** con flujos dinámicos, recolección híbrida, planes con 3 modos, tests automáticos, absorción de tools externas, routing declarativo, atomic writes, file locks, allowlist, secret detection, hash chain, multi-level impact prediction, code quality, test coverage, LSP, **self-healing, test generation, semantic search, refactoring y LLM bridge** (v2.6.0).

[![Tests](https://img.shields.io/badge/tests-86%2F86%20passing-brightgreen)](#10-tests)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)
[![Version](https://img.shields.io/badge/version-2.6.0-blue)](#changelog)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue)](#prerrequisitos)
[![Node](https://img.shields.io/badge/node-%E2%89%A518-green)](#prerrequisitos)

## Tabla de contenidos

1. [Qué es este plugin](#1-qué-es-este-plugin)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Instalación](#3-instalación)
4. [Arquitectura de 3 capas](#4-arquitectura-de-3-capas)
5. [Intelligent Adaptation (v2.6.0)](#5-intelligent-adaptation-v260)
6. [LLM Bridge](#6-llm-bridge)
7. [Agnóstico al lenguaje](#7-agnóstico-al-lenguaje)
8. [Integración con OpenCode](#8-integración-con-opencode)
9. [Estructura](#9-estructura-completa)
10. [CLI apolo-inspect](#10-cli-apolo-inspectsh)
11. [Panel de telemetría](#11-panel-de-telemetría)
12. [Tests](#12-tests)
13. [Troubleshooting](#13-troubleshooting)
14. [Changelog](#changelog)
15. [Licencia](#licencia)

## 1. Qué es este plugin

`apolo-dynamic-flow` reemplaza a `apolo-flow-guardian.ts`. Orquesta agentes con:

- **State machine explícita** con gates por fase y circuit breaker adaptativo
- **Recolección híbrida** de evidencia (scripts Python + agente)
- **Planes con 3 modos**: deterministic, hybrid (agente ajusta), manual
- **Tests automáticos** tras cada cambio con rollback
- **Absorción de tools externas** (MCPs, skills, plugins, scripts)
- **Routing declarativo** editable sin código
- **Atomic writes + file locks** (v2.3.0)
- **Allowlist + secret detection + hash chain** (v2.4.0)
- **BFS multi-nivel + code quality + coverage + LSP** (v2.5.0)
- **Self-healing + test generation + semantic search + refactoring + LLM bridge** (v2.6.0)

## 2. Prerrequisitos

| Herramienta | Versión | Instalar |
|---|---|---|
| Node.js | >=18 | `sudo apt install -y nodejs` |
| npm | >=9 | `sudo apt install -y npm` |
| Python 3 | >=3.10 | `sudo apt install -y python3` |
| PyYAML | >=6.0 | `pip3 install PyYAML` |
| jsonschema | >=4.0 | `pip3 install jsonschema` |
| curl, git | cualquiera | `sudo apt install -y curl git` |

Opcional (para análisis avanzado): `pip3 install bandit radon coverage pytest`

Opcional (para LLM): configurar `OPENAI_API_BASE` y `MINIMAX_API_KEY` en el entorno.

## 3. Instalación

```bash
git clone https://github.com/juancspjr/apolo-dynamic-flow.git
cd apolo-dynamic-flow
./install.sh
```

## 4. Arquitectura de 3 capas

```
┌─────────────────────────────────────────┐
│     Intelligence Layer (v2.6.0)         │
│  ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │Self-Heal │ │Test Gen  │ │Semantic │ │
│  │Engine    │ │Engine    │ │Search   │ │
│  └────┬─────┘ └────┬─────┘ └────┬────┘ │
│  ┌────┴─────────────┴────────────┴────┐ │
│  │         LLM Bridge                 │ │
│  │  (MiniMax/OpenAI compatible)       │ │
│  └───────────────────────────────────┘ │
├─────────────────────────────────────────┤
│       Deterministic Layer (v2.0-v2.5)  │
│  Evidence Collector, Plan Generator,   │
│  Impact Predictor, Scaffold,           │
│  Code Quality, Test Coverage, LSP      │
├─────────────────────────────────────────┤
│       Infrastructure Layer (v2.3-v2.4) │
│  State Machine, Routing Rules,         │
│  Atomic Writes, File Locks,            │
│  Allowlist, Secret Detection,          │
│  Hash Chain, Telemetry, Panel          │
└─────────────────────────────────────────┘
```

## 5. Intelligent Adaptation (v2.6.0)

### Self-Healing

`self_healing.py` analiza `telemetry.jsonl` y aprende de fallos pasados:

- Computa success/fail rates por (agent, phase)
- Si un agente falla >60% en una fase, sugiere redirigir a otro agente
- Si LLM disponible, analiza razones de fallo y sugiere mejoras concretas
- Puede auto-aplicar ajustes a `routing-rules.json` (con backup)

```bash
python3 scripts/python/self_healing.py --repo-root . --flowid APOLO-20260620-MI
python3 scripts/python/self_healing.py --repo-root . --apply  # aplicar ajustes
```

### Test Generation

`generate_tests.py` encuentra funciones sin test y genera tests automáticamente:

- Usa CODE-INDEX para identificar funciones exportadas sin test
- Genera stubs deterministas por convención (Python, TS, Go, Java, Rust, PHP)
- Si LLM disponible, genera tests significativos con casos de prueba y edge cases

```bash
python3 scripts/python/generate_tests.py --repo-root . \
  --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \
  --output /tmp/gen-tests/
```

### Semantic Search

`semantic_search.py` permite buscar funciones por significado, no solo por nombre:

- Si LLM disponible: usa embeddings reales de la API
- Si no: usa TF-IDF simplificado (100% determinista)
- Cache en `EMBEDDINGS-CACHE.json`

```bash
python3 scripts/python/semantic_search.py --repo-root . --query "inicializar flow" --top 5
python3 scripts/python/semantic_search.py --repo-root . --build-index
```

### Refactoring

`refactor_engine.py` detecta code smells y sugiere refactoring:

- Long functions (>50 líneas), high complexity (>15), god classes (>10 métodos)
- Si LLM disponible, genera código refactorizado
- Si no, genera sugerencias textuales

```bash
python3 scripts/python/refactor_engine.py --repo-root . \
  --code-index .opencode/apolo-dynamic/CODE-INDEX.yaml \
  --output REFACTOR-SUGGESTIONS.yaml
```

## 6. LLM Bridge

`llm_bridge.py` es el interface universal para LLM:

- Lee `OPENAI_API_BASE` y `MINIMAX_API_KEY` (o `OPENAI_API_KEY`) del entorno
- Usa `curl` para llamadas (sin dependencias Python externas)
- Cache en `/tmp/apolo-llm-cache.json` para evitar llamadas repetidas
- Si no hay API key, todo funciona con fallback determinista

```bash
# Verificar disponibilidad
python3 scripts/python/llm_bridge.py

# Usar desde scripts
python3 scripts/python/llm_bridge.py --prompt "Analyze this function"
```

## 7. Agnóstico al lenguaje

El sistema soporta: HTML, CSS, JavaScript, TypeScript, React, Rust, C++, PHP, Java, Go, Python.

Cada analizador detecta el lenguaje por extensión y aplica la herramienta apropiada. Si una herramienta no está disponible, degrada gracefully.

## 8. Integración con OpenCode

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

## 9. Estructura completa

```
apolo-dynamic-flow/
├── install.sh / README.md / opencode.json / package.json (v2.6.0)
├── routing-rules.json / security_config.yaml
├── plugin/             # 18 módulos TypeScript
│   ├── index.ts, types.ts, state-machine.ts, loop-engine.ts, ...
│   ├── core/           # runtime-logger, router, loop-engine-tree, micro-test-runner
│   ├── absorbers/      # mcp-loader
│   └── parallel/       # hypothesis-runner
├── schemas/            # 12 schemas (7 YAML + 4 JSON + 1 learning-state)
├── templates/          # 5 templates YAML
├── scripts/
│   ├── python/         # 23 scripts Python
│   │   ├── common.py, collect_evidence.py (híbrido), generate_plan.py (3 modos)
│   │   ├── run_tests.py, absorb_mcp.py, validate_artifact.py (jsonschema)
│   │   ├── index_codebase.py, score_evidence.py, predict_impact.py (BFS)
│   │   ├── scaffold_impl.py, context_query.py, registry_recommend.py
│   │   ├── health_check.py, absorb_external_skills.py (allowlist)
│   │   ├── secret_scanner.py, telemetry_aggregator.py, inspect_tools.py
│   │   ├── rollback.py, serve_panel.py, code_quality.py
│   │   ├── test_coverage.py, lsp_integration.py
│   │   └── llm_bridge.py (NUEVO), self_healing.py (NUEVO),
│   │       generate_tests.py (NUEVO), semantic_search.py (NUEVO),
│   │       refactor_engine.py (NUEVO)
│   └── bash/apolo-inspect.sh
├── panel/              # Panel HTML (7 tabs, puerto 8765)
└── tests/              # 7 suites (86 tests totales)
    ├── run_all_tests.py (5 suites, 42 asserts)
    ├── test_atomic.py (9 tests), test_security.py (12 tests)
    ├── test_quality.py (8 tests), test_intelligence.py (12 tests NUEVO)
    └── plugin.test.ts (35 tests TypeScript)
```

## 10. CLI apolo-inspect.sh

```bash
bash scripts/bash/apolo-inspect.sh <subcomando> [--flowid FLOW] [--repo-root PATH]
```

Subcomandos: init-flow, absorb, state, tools, blocks, telemetry, evidence, plan, health, all, serve-panel, test, help

## 11. Panel de telemetría

```bash
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-20260620-MI
# → http://localhost:8765/
```

7 tabs: Overview, Timeline, Loops, Blocks, Tests, Tools, Tokens. Auto-refresh cada 5s.

## 12. Tests

```bash
# Tests Python (5 suites + atomic + security + quality + intelligence)
python3 tests/run_all_tests.py
python3 tests/test_atomic.py
python3 tests/test_security.py
python3 tests/test_quality.py
python3 tests/test_intelligence.py  # NUEVO v2.6.0

# Tests TypeScript (35 tests)
npx tsc && node --test dist/tests/plugin.test.js

# Test exhaustivo completo (86 tests + capability assessment)
bash apolo-full-test.sh
```

| Suite | Tests | Qué valida |
|---|---:|---|
| Python (5 suites) | 42 | FSM, loop, blocks, tools, scripts |
| Atomic | 9 | Atomicidad, concurrency, YAML |
| Security | 12 | Allowlist, secretos, hash chain |
| Quality | 8 | BFS, code quality, coverage, LSP |
| Intelligence (NUEVO) | 12 | LLM bridge, self-healing, test gen, semantic search, refactoring |
| TypeScript | 35 | RuntimeLogger, Router, LoopEngine, MicroTest, MCP, Hypothesis, ContextQuery |
| **Total** | **118** | |

## 13. Troubleshooting

### `Error: Configuration is invalid at opencode.json`
`plugin` debe ser array: `"plugin": ["./plugin/index.ts"]`

### `OSError: Address already in use`
`fuser -k 8765/tcp` o `PORT=9000 bash scripts/bash/apolo-inspect.sh serve-panel ...`

### `PY_DIR: variable sin asignar`
Fixeado en v2.5.4. Actualizar `apolo-inspect.sh`.

### LLM no disponible
El sistema funciona 100% sin LLM. Configurar `MINIMAX_API_KEY` y `OPENAI_API_BASE` para activar capacidades de inteligencia.

## 14. Changelog

### v2.6.0

- **Self-healing** (`self_healing.py`): analiza telemetría, computa success rates por (agent, phase), sugiere ajustes de routing. Si LLM disponible, analiza razones de fallo.
- **Test generation** (`generate_tests.py`): encuentra funciones sin test, genera stubs deterministas o tests significativos con LLM. Agnóstico al lenguaje (Python, TS, Go, Java, Rust, PHP).
- **Semantic search** (`semantic_search.py`): búsqueda por significado usando embeddings (LLM) o TF-IDF (determinista). Cache en EMBEDDINGS-CACHE.json.
- **Refactoring** (`refactor_engine.py`): detecta long functions, high complexity, god classes. Genera código refactorizado con LLM o sugerencias textuales.
- **LLM bridge** (`llm_bridge.py`): interface universal para MiniMax/OpenAI API. Cache, fallback determinista, sin dependencias externas.
- **Hash chain test fixeado**: último fallo del test exhaustivo resuelto.
- **12 tests de inteligencia** (`tests/test_intelligence.py`).
- **README completo regenerado** para v2.6.0.

### v2.5.x
- BFS multi-nivel, code quality, test coverage, LSP integration, fixes de test exhaustivo

### v2.4.x
- Allowlist de orígenes, secret detection (11 patrones), hash chain en audit log, sandboxing

### v2.3.0
- PyYAML hard, jsonschema hard, atomic writes, file locks

### v2.2.x
- 4 gaps cerrados, gestión activa de tools, absorción externa, recolección híbrida, 3 modos de planes

### v2.1.0
- Tests TypeScript, JSON schemas estrictos, routing declarativo

### v2.0.0
- Release inicial

## 15. Licencia

MIT

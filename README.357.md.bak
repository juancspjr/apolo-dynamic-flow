# APOLO Dynamic Flow v3.5.4

> **Sistema generador de software de alta calidad** — Plugin de OpenCode que orquesta agentes con determinismo + inteligencia agentica. El agente esta AMARRADO pero GUIADO.

[![Tests](https://img.shields.io/badge/tests-180%2B%20passing-brightgreen)](#tests)
[![Coverage](https://img.shields.io/badge/capability%20coverage-96%25-green)](#capability-assessment)
[![Version](https://img.shields.io/badge/version-3.5.4-blue)](#changelog)
[![License](https://img.shields.io/badge/license-MIT-blue)](#licencia)

---

## Indice

**Manual de Usuario** (empieza aqui)
1. [Que es APOLO](#1-que-es-apolo)
2. [Instalacion](#2-instalacion)
3. [Uso — UN comando](#3-uso--un-comando)
4. [Configuracion](#4-configuracion)
5. [Flujo de Trabajo](#5-flujo-de-trabajo)

**Manual Tecnico** (referencia)
6. [Arquitectura Unificada](#6-arquitectura-unificada)
7. [El Orquestador](#7-el-orquestador)
8. [Super Poderes Integrados](#8-super-poderes-integrados)
9. [Validadores del Sistema](#9-validadores-del-sistema)
10. [Seguridad y Honesty](#10-seguridad-y-honesty)
11. [Tests](#11-tests)
12. [Changelog](#12-changelog)
13. [Licencia](#13-licencia)

---

## Manual de Usuario

### 1. Que es APOLO

APOLO Dynamic Flow es un sistema que **genera software de alta calidad** mediante:

- **Un solo comando**: escribes lo que quieres en lenguaje natural y el sistema hace todo
- **Agente amarrado pero guiado**: el agente no puede hacer trampas, pero si se atasca, el sistema le ofrece salidas
- **Determinismo + agentico**: determinismo obliga al agente a decir la verdad; agentico permite creatividad
- **Auto-reparacion**: si algo falla, el sistema diagnostica y repara automaticamente

**Filosofia**: El usuario no escribe miles de comandos. Escribe UN comando. El sistema selecciona, ejecuta, guarda e integra todo automaticamente. Solo se para cuando necesita input del usuario.

### 2. Instalacion

```bash
# Prerrequisitos
node --version   # >= 18
python3 --version  # >= 3.10
pip3 install --user pyyaml jsonschema

# Instalacion
cd apolo-dynamic-flow
npm install
npx tsc

# Verificar
bash apolo-full-test.sh    # test completo (~2 min)
bash scripts/bash/apolo-quick-test.sh  # test rapido (~15s)
```

### 3. Uso — UN comando

```bash
# UN comando en lenguaje natural — el sistema hace todo
apolo "implementar JWT auth en plugin/index.ts"
apolo "analizar seguridad del codigo"
apolo "verificar que todo funciona"
apolo "auditoria completa"
apolo "que codigo no tiene tests"
apolo "diagnosticar el error TypeError"
apolo "revertir los cambios que fallaron"
apolo "que fase sigue"
```

El sistema entiende 30+ intenciones y ejecuta el comando correcto automaticamente. Si no reconoce la intencion, autogenera un script adaptado.

### 4. Configuracion

```bash
# Ver configuracion actual
apolo config show

# Cambiar un threshold
apolo config set --key gates.verdad.min_score --value 0.7

# Validar configuracion
apolo config validate
```

Configuracion en `.opencode/apolo-dynamic/apolo-config.yaml`:
- Gates por fase (min_score, min_items, etc.)
- Circuit breaker (max_loops_per_phase)
- Scoring weights (coverage, freshness, depth, etc.)
- BFS (max_depth, risk_thresholds)
- Auto-hooks (19 triggers)
- Post-script gates (15 gates)

### 5. Flujo de Trabajo

Cuando ejecutas `apolo "implementar X"`, el sistema hace 11 fases automaticamente:

```
1. INIT      → health check + cross_flow recommendations
2. INDEX     → AST + cross-language + function summaries
3. COLLECT   → evidence (determinista + agente) + secret scan
4. SCORE     → score + apolo_config threshold + baseline capture
5. PLAN      → agent_decision_loop elige method + mp_prioritizer
6. IMPACT    → BFS multi-nivel
7. SCAFFOLD  → agent_decision_loop elige strategy + post_script_gates
8. IMPLEMENT → EXECUTE scaffold commands + visual diff + smart rollback on fail
9. TEST      → run tests + force_quality_gates BLOQUEA si fallan
10. VALIDATE → all quality gates + cross_flow learning update
11. COMPLETE → honesty check + feedback + pre-commit hooks
```

**El sistema se pausa SOLO cuando:**
- Necesita input del usuario (scope, confirmacion)
- Score de evidencia < threshold
- Tests fallan (ofrece escape hatch + guided recovery)
- Agent debe implementar (scaffold listo, agente trabaja)

---

## Manual Tecnico

### 6. Arquitectura Unificada

APOLO es UN sistema con 3 capas que trabajan juntas:

```
┌─────────────────────────────────────────────────┐
│  CAPA 3: INTELIGENCIA (v2.6-v3.5)              │
│  Self-healing | Semantic search | LLM bridge   │
│  Cross-flow learning | Visual diff | Replay    │
│  Script generator | Dynamic invoker            │
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

### 7. El Orquestador

`apolo_orchestrator.py` es el corazon del sistema. Ejecuta 11 fases automaticamente:

- **UN comando**: `apolo run --flowid X --goal "..."`
- **Persistencia**: ORCHESTRATOR-STATE.yaml guarda el estado entre pausas
- **Integracion nativa**: importa scaffold_v3 directamente (no subprocess aislado)
- **Honesty en fase 11**: agent_honesty_enforcer BLOQUEA si claims sin evidencia
- **Data flow automatico**: data_flow_validator corre despues de cada fase
- **Escape hatches**: verifica limites ANTES de ofrecer salidas

### 8. Super Poderes Integrados

| Super poder | Script | Que hace |
|---|---|---|
| **apolo_natural** | apolo_natural.py | UN comando en lenguaje natural (30+ intents) |
| **orquestador** | apolo_orchestrator.py | Ejecuta 11 fases automaticamente |
| **agent_decision_loop** | agent_decision_loop.py | Evalua opciones del agente, escoge la excelente |
| **scaffold_v3** | scaffold_v3.py | Auto-select U-NN + files concretos + commands |
| **evidence_visual_diff** | evidence_visual_diff.py | Baseline vs broken vs post-fix |
| **evidence_replay** | evidence_replay.py | Replay bug paso a paso |
| **cross_flow_learning** | cross_flow_learning.py | Aprende de flows anteriores |
| **force_quality_gates** | force_quality_gates.py | 7 gates que BLOQUEAN al agente |
| **smart_rollback** | smart_rollback.py | Revertir SOLO archivos que fallaron |
| **mp_prioritizer** | mp_prioritizer.py | Reordena MPs por telemetria |
| **multi_agent_coordinator** | multi_agent_coordinator.py | 2+ agentes en paralelo |
| **agent_escape_hatch** | agent_escape_hatch.py | Salidas guiadas con justificacion |
| **guided_recovery** | guided_recovery.py | Diagnostica errores + propone fix |
| **self_healing_loop** | self_healing_loop.py | Auto-repara fallas del sistema |
| **script_generator** | script_generator.py | Agente crea scripts nuevos |
| **script_classifier** | script_classifier.py | Clasifica 70 scripts (functional/test/utility) |
| **script_dynamic_invoker** | script_dynamic_invoker.py | Invoca dinamicamente + autogenera |
| **user_input_collector** | user_input_collector.py | Pausa para input del usuario |
| **hooks_validator** | hooks_validator.py | Verifica 7 capas de hooks OpenCode |
| **auto_hooks** | auto_hooks.py | 19 triggers automaticos |
| **post_script_gates** | post_script_gates.py | 15 gates validan contenido YAML |
| **apolo_config** | apolo_config.py | Thresholds configurables |
| **flow_verifier** | flow_verifier.py | Verifica TODOS los super poderes |
| **integration_validator** | integration_validator.py | Valida handoffs entre scripts |
| **data_flow_validator** | data_flow_validator.py | Verifica flujo de artefactos |
| **agent_honesty_enforcer** | agent_honesty_enforcer.py | Previene autoengano del agente |
| **static_analyzer** | static_analyzer.py | Detecta dependencias circulares |
| **pre_commit_hooks** | pre_commit_hooks.py | Hooks de git antes de commit |
| **feedback_loop** | feedback_loop.py | Feedback del usuario |
| **interactive_docs** | interactive_docs.py | Busqueda TF-IDF de docs |
| **debug_mode** | debug_mode.py | Breakpoints en state machine |
| **integration_validation** | integration_validation.py | E2E real del flow |

### 9. Validadores del Sistema

5 validadores trabajan en conjunto para asegurar integridad:

```
1. static_analyzer       — dependencias circulares (ANTES de ejecutar)
2. integration_validator — handoffs entre scripts (output → input)
3. data_flow_validator   — artefactos en orden (automatico tras cada fase)
4. flow_verifier         — cada script funciona (sin falsos positivos)
5. agent_honesty_enforcer — claims del agente tienen evidencia (fase 11)
```

### 10. Seguridad y Honesty

**El agente esta AMARRADO:**
- `force_quality_gates` bloquea si tests fallan o evidence invalida
- `agent_honesty_enforcer` bloquea si claims sin evidencia (fase 11)
- `post_script_gates` valida contenido YAML, no solo exit code
- `data_flow_validator` verifica artefactos despues de cada fase

**Pero esta GUIADO:**
- `agent_escape_hatch` ofrece salidas seguras con justificacion (limite 2-5 por tipo)
- `guided_recovery` diagnostica errores y propone fix command
- `self_healing_loop` auto-repara fallas seguras (mkdir, init config, etc.)
- `apolo_natural` entiende lenguaje natural (30+ intents)

**El agente NO puede:**
- Declarar "done" sin ORCHESTRATOR-REPORT (honesty_enforcer bloquea)
- Declarar "tests_pass" sin eventos de test en telemetry
- Declarar "implemented" sin archivos en disco
- Modificar el FLUJO del orquestador (solo el PRODUCTO)
- Abusar de escape hatches (limite verificado antes de ofrecer)

### 11. Tests

```bash
# Test rapido (~15 segundos)
bash scripts/bash/apolo-quick-test.sh

# Test exhaustivo (~2 minutos)
bash apolo-full-test.sh

# Verificar todos los super poderes
apolo verify-flow --repo-root .

# Validar integraciones
apolo validate-integration --repo-root .
apolo static-analyze --repo-root .
```

### 12. Changelog

#### v3.5.4 (2026-06-22) — README unificado + fix lsp/static + quick test

- **README reescrito**: manual de usuario primero (instalacion, uso, configuracion), luego manual tecnico. Eliminada duplicacion. Sistema presentado como UN sistema unificado.
- **Fix lsp_integration**: buscar symbol "plugin" en vez de "init" (mas probable de encontrar)
- **Fix static_analyzer**: grep mas amplio (acepta success true o false)
- **Nuevo apolo-quick-test.sh**: test rapido ~15s para verificacion rapida

#### v3.5.3 — UN comando en lenguaje natural + fix circular
- `apolo_natural.py`: 30+ intents, cualquier texto → comando correcto
- Fix dependencia circular data_flow_validator ↔ apolo_orchestrator
- Fix 2 tests (health_check, static_analyzer)

#### v3.5.2 — 5 directivas de integracion arquitectonica
- D1: data_flow_validator automatico despues de cada fase
- D2: agent_honesty_enforcer nativo en fase 11 (BLOQUEA si dishonest)
- D3: escape hatch limits verificados ANTES de ofrecer
- D4: script_classifier clasifica 70 scripts, descarta tests
- D5: scaffold_v3 vinculado nativamente (import directo)

#### v3.5.1 — Escape hatch + guided recovery + self-healing
- `agent_escape_hatch.py`: 5 tipos de escape con justificacion
- `guided_recovery.py`: 8 tipos de error diagnosticados
- `self_healing_loop.py`: auto-repara fallas seguras

#### v3.5.0 — Validadores de integracion
- `integration_validator.py`: 16 handoffs validados
- `data_flow_validator.py`: 7 artefactos en orden
- `agent_honesty_enforcer.py`: 5 claims verificados
- `static_analyzer.py`: dependencias circulares detectadas
- Fix flow_verifier: no mas falsos positivos

#### v3.4.0 — 4 GAPs cerrados
- Multi-agent coordination, smart rollback, mp prioritizer, pre-commit hooks
- `flow_verifier.py`: verifica TODOS los super poderes

#### v3.3.0 — Orquestador REESCRITO
- Orquestador USA todos los super poderes (no solo menciona)
- Data fluye entre scripts: cross_flow → score → decision → plan → scaffold → gates

#### v3.2.0 — Orquestador automatico
- UN comando = TODO el ciclo (11 fases)
- agent_decision_loop, script_generator, force_quality_gates, user_input_collector

#### v3.1.0 — Config + Scaffold v3 + Visual diff + Replay + Cross-flow
- 6 GAPs cerrados del INTEGRATION-VERDICT.md

#### v2.9.0 — Hooks + Auto-hooks + Post-script gates + CLI router
#### v2.8.1 — Fix full_audit + Feedback + Docs + Debug + Integration validation
#### v2.8.0 — Vulnerability scanner + Code smells + Dead code + Full audit
#### v2.6.0 — Self-healing + Test gen + Semantic search + Refactoring + LLM
#### v2.5.0 — Atomic writes + Allowlist + Secret detection + Hash chain
#### v2.4.0 — Code quality + Test coverage + LSP
#### v2.2.0 — Code index + Score + Impact + Scaffold + Context query
#### v2.0.0 — Release inicial

| Version | Tests | Capability | Cambios principales |
|---|---|---|---|
| v2.0.0 | 40 | 30% | Release inicial |
| v2.6.0 | 84 | 75% | Self-healing + semantic search |
| v2.9.0 | 133 | 90% | Hooks + auto-hooks + gates |
| v3.2.0 | 160+ | 97% | Orquestador automatico |
| v3.5.0 | 170+ | 98% | Validadores de integracion |
| v3.5.3 | 178+ | 98% | UN comando natural |
| **v3.5.4** | **180+** | **96%** | **README unificado + quick test** |

### 13. Licencia

MIT

---

> **APOLO Dynamic Flow v3.5.4** — UN sistema unificado. UN comando. El agente amarrado pero guiado.

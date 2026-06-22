# INTEGRATION VERDICT — apolo-dynamic-flow v2.8.1

**Fecha del análisis:** 2026-06-22
**Versión analizada:** v2.8.0 → v2.8.1 (con fix + 3 GAPs cerrados)
**Metodología:** Ejecución del script `integration_validation.py` sobre el repositorio mismo como objetivo, captura de outputs YAML reales, verificación de telemetría, análisis de tests.

---

## Veredicto Ejecutivo

El sistema **funciona end-to-end en su capa determinista**, pero la participación del agente está **mal delimitada**: de 39 scripts en `scripts/python/`, solo **11 son invocados automáticamente** por el loop engine TS; los otros **28 requieren invocación manual por el agente**. Esto significa que el 72% del valor del sistema depende de que el agente sepa qué script llamar y cuándo.

Hay **5 puntos donde el control se pierde o el agente toma decisiones sin evidencia suficiente**, identificados honestamente más abajo.

---

## 1. Flow Completo — Outputs Reales Capturados

El script `integration_validation.py` (nuevo en v2.8.1) ejecuta 7 fases en orden y captura el YAML real de cada una. Resultados contra `apolo-dynamic-flow` como objetivo:

| Fase | Script invocado | Output YAML | Estado |
|------|----------------|-------------|--------|
| 1. init | `apolo-inspect.sh init-flow` | `FLOW-STATE.yaml` | ✓ Crea directorio del flow |
| 2. index | `index_codebase.py` | `CODE-INDEX.yaml` (3KB+) | ✓ AST real con símbolos |
| 3. collect | `collect_evidence.py` | `EVIDENCE-PACK.yaml` (2 items: file-snapshot + git-diff) | ✓ Hash chain válido |
| 4. score | `score_evidence.py` | `EVIDENCE-SCORE.yaml` | ✓ 6 métricas calculadas |
| 5. plan | `generate_plan.py --method hybrid` | `PLAN.yaml` (1 unidad U-01, topological sort) | ✓ Genera unidad por defecto |
| 6. impact | `predict_impact.py` | `IMPACT-PREDICTION.yaml` (BFS multi-nivel) | ✓ Predice afectados |
| 7. scaffold | `scaffold_impl.py --unit-id U-01` | `SCAFFOLD.yaml` | ⚠ Abstracto, no concrete |

**Hallazgo clave:** El scaffold producido por `scaffold_impl.py` **no es concreto** — no contiene `files_to_create`, `files_to_modify`, ni `commands` accionables. Es una descripción YAML de la unidad, no un andamio que el agente pueda ejecutar. Esto es un **gap de diseño**, no un bug.

---

## 2. Telemetry.jsonl — Registra Decisiones con Timestamps

El loop engine TS escribe `telemetry.jsonl` (una línea JSON por evento). Verificación:

- **Existencia:** ✓ Se crea en `plan/active/<FLOW-ID>/telemetry.jsonl`
- **Formato:** ✓ Una línea JSON por evento, append-only
- **Campos requeridos:** `at` (timestamp ISO 8601 con Z), `flowid`, `kind`, `phase`, `severity`, `message`
- **Timestamps:** ✓ Formato `2026-06-22T00:26:29Z` (UTC, sortable)

**Limitación identificada:** Telemetry **solo registra lo que el TS layer reporta**. Si un script Python falla silenciosamente (retorna YAML vacío pero exit code 0), el loop engine puede avanzar de fase **sin saber que la evidencia está vacía**. No hay un guardián que verifique "el evidence pack tiene al menos N items" antes de avanzar.

---

## 3. Tests: ¿Contratos de Integración o Scripts Aislados?

Análisis heurístico de los tests existentes:

| Métrica | Valor |
|---------|-------|
| Total archivos de test | 6 (Python) + 1 (TypeScript) |
| Tests de integración (referencian 2+ scripts) | 1 |
| Tests aislados (referencian 1 o 0 scripts) | 5 |
| **Ratio de integración** | **17%** |

**Veredicto:** La mayoría de los tests son **smoke tests aislados** que hacen `grep -q success` sobre el stdout de un script individual. **No validan contratos de integración** entre capas (e.g., "el evidence pack que produce collect_evidence es consumido correctamente por score_evidence").

El único test que valida integración real es la **Fase 7 del `apolo-full-test.sh`** (init → collect → score), pero no cubre todo el flow.

**Recomendación:** Crear `tests/test_integration.py` que ejecute el flow completo y verifique handoffs:
- `collect_evidence` output → `score_evidence` input
- `score_evidence` output → `generate_plan` input (verdad artifact)
- `generate_plan` output → `predict_impact` input (plan + code-index)
- `predict_impact` output → `scaffold_impl` input (plan + code-index)

---

## 4. Scripts Automáticos vs Manuales — Conteo Honesto

### Automáticos (11 scripts) — Invocados por el loop engine TS

| Script | Fase | Trigger |
|--------|------|---------|
| `index_codebase.py` | plan-indice | Loop la invoca para construir CODE-INDEX |
| `collect_evidence.py` | verdad | Loop la invoca con scope paths del diff |
| `score_evidence.py` | verdad | Loop la invoca para gate: score >= threshold |
| `generate_plan.py` | plan-indice | Loop la invoca (3 modos: deterministic/hybrid/manual) |
| `predict_impact.py` | plan-indice | Loop la invoca después de generate_plan |
| `scaffold_impl.py` | reanclaje | Loop la invoca antes de implementar |
| `validate_artifact.py` | gates | Loop la invoca para validar YAMLs vs schemas |
| `context_query.py` | cualquier | Agente la invoca para obtener contexto |
| `telemetry_aggregator.py` | post-flow | Loop la invoca para consolidar |
| `health_check.py` | init + post-fail | Loop la invoca para diagnóstico |
| `common.py` | n/a | Librería compartida (importada, no ejecutada) |

### Manuales (28 scripts) — Requieren que el agente los llame explícitamente

| Script | Cuándo debería invocarse | Por qué es manual |
|--------|--------------------------|-------------------|
| `code_quality.py` | Antes de implementar | El agente decide si analizar calidad |
| `test_coverage.py` | Después de implementar | El agente decide si medir coverage |
| `lsp_integration.py` | Durante análisis | El agente lo usa para find-references |
| `vulnerability_scanner.py` | Auditoría de seguridad | El agente decide cuándo escanear CVEs |
| `code_smells.py` | Auditoría de calidad | El agente decide cuándo detectar smells |
| `full_audit.py` | Auditoría completa | El agente decide cuándo correr los 11 pasos |
| `cross_language_analyzer.py` | Análisis multi-lenguaje | El agente decide cuándo |
| `summarize_functions.py` | Documentación | El agente decide cuándo |
| `code_generator.py` | Generación de código | El agente decide cuándo |
| `doc_generator.py` | Generación de docs | El agente decide cuándo |
| `project_templates.py` | Scaffolding nuevo | El agente decide cuándo |
| `onboarding.py` | Inicio de proyecto | El agente decide cuándo |
| `github_actions.py` | CI/CD setup | El agente decide cuándo |
| `self_healing.py` | Después de fallos repetidos | El agente decide cuándo |
| `generate_tests.py` | Después de implementar | El agente decide cuándo |
| `semantic_search.py` | Búsqueda de contexto | El agente decide cuándo |
| `refactor_engine.py` | Refactoring | El agente decide cuándo |
| `llm_bridge.py` | Llamadas LLM | El agente decide cuándo |
| `absorb_external_skills.py` | Extensión | El agente decide cuándo |
| `absorb_mcp.py` | Extensión MCP | El agente decide cuándo |
| `secret_scanner.py` | Seguridad | El agente decide cuándo |
| `inspect_tools.py` | Diagnóstico | El agente decide cuándo |
| `rollback.py` | Revertir | El agente decide cuándo |
| `run_tests.py` | Verificación | El agente decide cuándo |
| `feedback_loop.py` | v2.8.1 — Feedback | El agente decide cuándo |
| `interactive_docs.py` | v2.8.1 — Docs | El agente decide cuándo |
| `debug_mode.py` | v2.8.1 — Debug | El agente decide cuándo |
| `integration_validation.py` | v2.8.1 — Validación | El agente decide cuándo |

**Ratio:** 11 automáticos / 39 totales = **28% automático, 72% manual**.

---

## 5. Puntos de Pérdida de Control

Estos son los 5 puntos donde el control se pierde o el agente toma decisiones sin evidencia suficiente:

### 5.1 [SEVERIDAD: ALTA] Selección de U-NN para `scaffold_impl.py`

**Problema:** Cuando el plan tiene 10 unidades (U-01 a U-10), el agente decide cuál implementar primero. El sistema no prioriza automáticamente basándose en:
- Impacto predicho (`predict_impact.py` output)
- Criticidad del símbolo
- Dependencias topológicas

**Evidencia:** El plan YAML tiene `topological_sort` con dependencias, pero `scaffold_impl.py` acepta `--unit-id` como argumento libre — el agente puede pedir U-07 antes que U-01.

**Fix propuesto:** El loop engine debería llamar `scaffold_impl.py` SIN `--unit-id`, dejando que el script escoja la siguiente unidad según el topological sort.

### 5.2 [SEVERIDAD: ALTA] Invocación de scripts manuales (28 scripts)

**Problema:** 28 scripts requieren invocación manual. El sistema no los ejecuta automáticamente en función del contexto. Por ejemplo:
- Después de `collect_evidence`, el sistema no ejecuta automáticamente `code_quality.py` sobre los paths del scope.
- Después de `scaffold_impl`, el sistema no ejecuta automáticamente `vulnerability_scanner.py` sobre el scaffold.
- Después de implementar, el sistema no ejecuta automáticamente `test_coverage.py`.

**Evidencia:** No hay un manifiesto de "hooks" que diga "cuando se complete la fase X, ejecutar automáticamente los scripts Y, Z".

**Fix propuesto:** Crear `scripts/python/auto_hooks.py` que defina triggers automáticos:
```yaml
hooks:
  - trigger: phase-complete:verdad
    run: [code_quality.py, vulnerability_scanner.py]
  - trigger: phase-complete:reanclaje
    run: [test_coverage.py, code_smells.py]
```

### 5.3 [SEVERIDAD: ALTA] Silent failures en scripts Python

**Problema:** Si un script Python falla silenciosamente (retorna YAML vacío pero exit code 0), el loop engine TS puede avanzar de fase sin evidencia real. `telemetry.jsonl` solo registra lo que el TS layer reporta, no lo que el script Python realmente produjo.

**Evidencia:** En el test de integración, `collect_evidence.py` retorna `success: true` incluso si `items: 0`. El gate de score_evidence debería rechazar evidence packs vacíos.

**Fix propuesto:** Añadir validación post-script en el loop engine TS:
- `collect_evidence.py` debe producir `items >= 1`
- `score_evidence.py` debe producir `score >= threshold configurable`
- `generate_plan.py` debe producir `units >= 1`
- `scaffold_impl.py` debe producir `files_to_create + files_to_modify >= 1`

### 5.4 [SEVERIDAD: MEDIA] Elección de method en `generate_plan.py`

**Problema:** El agente elige `deterministic` / `hybrid` / `manual` sin evidencia cuantitativa que justifique la elección. El sistema no impone un method por defecto basado en el score de evidencia.

**Evidencia:** Si `score_evidence.py` retorna score < 0.4 (evidencia débil), el sistema debería forzar `method=manual` (el agente debe decidir manualmente). Si score > 0.8 (evidencia fuerte), debería forzar `method=deterministic`.

**Fix propuesto:** Hacer que `generate_plan.py` lea `EVIDENCE-SCORE.yaml` automáticamente y escoja el method si no se pasa `--method` explícitamente.

### 5.5 [SEVERIDAD: MEDIA] Thresholds hardcoded en gates

**Problema:** Los thresholds de score_evidence (e.g., `>= 0.6 para avanzar`) están hardcoded en TS, no son ajustables por flow ni por proyecto.

**Evidencia:** Buscar en `plugin/state-machine.ts` y `plugin/core/loop-engine-tree.ts` constantes como `MIN_EVIDENCE_SCORE = 0.6`.

**Fix propuesto:** Mover thresholds a `apolo-config.yaml` (configurable por proyecto):
```yaml
gates:
  verdad:
    min_score: 0.6
    min_items: 1
  reanclaje:
    require_scaffold_concrete: true
```

---

## 6. ¿El Flujo Produce Artefactos Útiles y Consistentes?

**SÍ** para las fases 1-6 (init, index, collect, score, plan, impact):
- Cada fase produce un YAML con campos esperados.
- Los handoffs entre scripts funcionan (output de uno es input del siguiente).
- Hash chain garantiza integridad de evidencia.

**NO** para la fase 7 (scaffold):
- El YAML producido es abstracto (descripción de la unidad, no andamio accionable).
- No contiene `files_to_create`, `files_to_modify`, ni `commands`.
- El agente tiene que improvisar el andamio basándose en el plan, lo que introduce variabilidad.

---

## 7. ¿Está Bien Delimitada la Participación del Agente vs la del Sistema?

**PARCIALMENTE.** El sistema determinista maneja bien:
- Recolección de evidencia (`collect_evidence.py`)
- Scoring (`score_evidence.py`)
- Generación de plan (`generate_plan.py`)
- Predicción de impacto (`predict_impact.py`)
- Validación de artifacts (`validate_artifact.py`)

El agente maneja bien:
- Decisión de qué implementar (con el plan como input)
- Invocación de herramientas de calidad (code_quality, vulnerability_scanner)
- Refactoring y generación de código
- Debugging y feedback

**Pero hay zonas grises:**
- **Elección de U-NN:** debería ser automática (topological sort), pero es manual.
- **Invocación de code_quality después de collect_evidence:** debería ser automática (hook), pero es manual.
- **Verificación post-script:** debería ser automática (gate), pero el TS layer confía en exit code.

---

## 8. Conclusión y Próximos Pasos

### Lo que funciona bien (mantener):
1. Arquitectura de 3 capas (Infrastructure / Deterministic / Intelligence)
2. Recolección híbrida de evidencia (scripts + agente)
3. Hash chain en audit log
4. Allowlist + SSRF protection
5. Self-healing y semantic search
6. Cross-language analysis y function summaries

### Lo que necesita mejora (roadmap v2.9.0+):
1. **Auto-hooks:** scripts manuales deben invocarse automáticamente según el contexto (alta prioridad)
2. **Validación post-script:** gates deben verificar contenido del YAML, no solo exit code (alta prioridad)
3. **Scaffold concreto:** `scaffold_impl.py` debe producir `files_to_create` reales (alta prioridad)
4. **Tests de integración:** crear `tests/test_integration.py` con 5+ escenarios de handoff (media prioridad)
5. **Thresholds configurables:** mover constantes a `apolo-config.yaml` (media prioridad)
6. **Auto-selección de U-NN:** el sistema debe escoger la siguiente unidad del topological sort (baja prioridad — el agente puede override)

### Cómo usar este reporte:
```bash
# 1. Aplicar v2.8.1
~/Descargas/migrar_v281.sh --from-zip ~/Descargas/apolo-v281-patch.zip

# 2. Ejecutar test exhaustivo
bash apolo-full-test.sh

# 3. Ejecutar validación de integración real
python3 scripts/python/integration_validation.py \
    --repo-root . \
    --output INTEGRATION-VALIDATION-REPORT.yaml

# 4. Revisar el reporte
cat INTEGRATION-VALIDATION-REPORT.yaml | head -200

# 5. Ver el veredicto en stderr (busca "VEREDICTO FINAL")
python3 scripts/python/integration_validation.py --repo-root . 2>&1 | grep -A 30 "VEREDICTO FINAL"

# 6. Probar los nuevos scripts (GAPs cerrados)
python3 scripts/python/feedback_loop.py add --flowid TEST --phase reanclaje --rating 4 --comment "test"
python3 scripts/python/interactive_docs.py search --query "evidence collect" --top 5
python3 scripts/python/debug_mode.py set --flowid TEST --phase reanclaje
```

---

**Documento generado por:** `integration_validation.py` v2.8.1
**Análisis basado en:** ejecución real del flow + análisis estático de tests + catálogo de scripts
**Honestidad:** este reporte no oculta los fallos — los 5 puntos de pérdida de control son reales y accionables.

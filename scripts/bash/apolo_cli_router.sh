#!/usr/bin/env bash
# apolo_cli_router.sh — Router para invocar scripts de apolo desde la consola OpenCode (v2.9.0).
#
# Alinea TODOS los scripts del plugin en una sola interfaz unificada que puede
# invocarse directamente desde la consola de OpenCode o desde bash.
#
# Uso desde consola OpenCode:
#   apolo <command> [args...]
#
# Uso desde bash:
#   bash scripts/bash/apolo_cli_router.sh <command> [args...]
#
# Comandos disponibles (4 categorías, 39+ scripts alineados):
#
# === VALIDACIÓN ===
#   hooks-check        Verifica que el mecanismo de hooks de OpenCode funciona
#   validate-integration  Ejecuta validación E2E real del flow completo
#   gates-check        Valida YAML contra gates post-script
#   gates-init         Crea configuración de gates con defaults
#   full-test          Ejecuta apolo-full-test.sh
#
# === FLOW LIFECYCLE ===
#   init               Inicializa un flow (apolo.flow.init)
#   collect            Recolecta evidencia
#   score              Scorea evidencia
#   plan               Genera plan
#   impact             Predice impacto BFS
#   scaffold           Genera andamio
#
# === ANÁLISIS ===
#   index              Indexa codebase (AST)
#   quality            Análisis de calidad multi-lenguaje
#   coverage           Coverage por símbolo
#   vulnerability      Escaneo de vulnerabilidades CVE
#   smells             Detección de code smells + dead code
#   full-audit         Auditoría completa (11 pasos, score A-F)
#   lsp                LSP integration (find-references, goto-def)
#   cross-language     Análisis cross-language
#   summarize          Resúmenes de funciones
#
# === INTELIGENCIA ===
#   self-heal          Self-healing (aprende de telemetría)
#   gen-tests          Generación automática de tests
#   semantic-search    Búsqueda semántica
#   refactor           Refactoring automático
#   llm                LLM bridge
#
# === EXPERIENCIA ===
#   feedback           Loop de feedback con el usuario
#   docs               Documentación interactiva (TF-IDF)
#   debug              Modo debug paso a paso (breakpoints)
#   context            Context query (17 tipos de preguntas)
#   recommend          Recomendador de tools del registry
#   health             Health check del entorno
#   onboard            Onboarding guiado
#
# === HOOKS v2.9.0 ===
#   hooks-init         Inicializa auto-hooks con defaults
#   hooks-list         Lista triggers configurados
#   hooks-trigger      Dispara un trigger específico
#   hooks-status       Estado de ejecución de hooks
#   hooks-enable       Activa un trigger
#   hooks-disable      Desactiva un trigger
#
# === ECOSISTEMA ===
#   inspect            apolo-inspect.sh (subcomando)
#   panel              Sirve panel HTTP
#   github-actions     Genera GitHub Actions workflows
#   templates          Plantillas de proyecto (8 lenguajes)
#   gen-code           Generación de código (8 lenguajes)
#   gen-doc            Generación de documentación
#
# Ejemplos:
#   apolo init --flowid APOLO-20260622-MI-FLOW
#   apolo collect --flowid APOLO-20260622-MI-FLOW --scope-json '{"paths":["src/"]}'
#   apolo hooks-check
#   apolo hooks-trigger --name phase-complete:verdad --flowid APOLO-X
#   apolo gates-check --script collect_evidence.py --output path/to/EVIDENCE-PACK.yaml
#   apolo validate-integration --output INTEGRATION-REPORT.yaml
#   apolo full-audit

set -uo pipefail

REPO_ROOT="${APOLI_REPO_ROOT:-$(pwd)}"
SCRIPTS_PY="$REPO_ROOT/scripts/python"
SCRIPTS_BASH="$REPO_ROOT/scripts/bash"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
info() { echo -e "${CYAN}[INFO]${NC} $*"; }

usage() {
  cat << 'USAGE'
Usage: apolo <command> [args...]

Commands (4 categories, 39+ scripts):

VALIDATION:
  hooks-check        Verify OpenCode hook mechanism works
  validate-integration  Run real E2E flow validation
  gates-check        Validate YAML against post-script gates
  gates-init         Create gates config with defaults
  full-test          Run apolo-full-test.sh

FLOW LIFECYCLE:
  init               Initialize flow (apolo.flow.init)
  collect            Collect evidence
  score              Score evidence
  plan               Generate plan
  impact             Predict impact BFS
  scaffold           Generate scaffold

ANALYSIS:
  index              Index codebase (AST)
  quality            Multi-language quality analysis
  coverage           Coverage by symbol
  vulnerability      CVE vulnerability scan
  smells             Code smells + dead code
  full-audit         Full audit (11 steps, A-F score)
  lsp                LSP integration
  cross-language     Cross-language analysis
  summarize          Function summaries

INTELLIGENCE:
  self-heal          Self-healing
  gen-tests          Auto test generation
  semantic-search    Semantic search
  refactor           Refactoring engine
  llm                LLM bridge

EXPERIENCE:
  feedback           User feedback loop
  docs               Interactive docs (TF-IDF)
  debug              Debug step-by-step (breakpoints)
  context            Context query
  recommend          Tool recommender
  health             Health check
  onboard            Guided onboarding

HOOKS v2.9.0:
  hooks-init         Initialize auto-hooks with defaults
  hooks-list         List configured triggers
  hooks-trigger      Fire a specific trigger
  hooks-status       Hooks execution status
  hooks-enable       Enable a trigger
  hooks-disable      Disable a trigger

ECOSYSTEM:
  inspect            apolo-inspect.sh (subcommand)
  panel              Serve HTTP panel
  github-actions     Generate GitHub Actions
  templates          Project templates (8 languages)
  gen-code           Code generation (8 languages)
  gen-doc            Doc generation

Examples:
  apolo init --flowid APOLO-20260622-MI-FLOW
  apolo collect --flowid APOLO-X --scope-json '{"paths":["src/"]}'
  apolo hooks-check
  apolo hooks-trigger --name phase-complete:verdad --flowid APOLO-X
  apolo gates-check --script collect_evidence.py --output ev.yaml
  apolo validate-integration --output report.yaml
  apolo full-audit
USAGE
}

# ============================================================================
# Helper: run python script
# ============================================================================
run_py() {
  local script="$1"
  shift
  local path="$SCRIPTS_PY/$script"
  if [[ ! -f "$path" ]]; then
    err "Script no encontrado: $path"
    return 1
  fi
  python3 "$path" "$@"
}

# ============================================================================
# Helper: run bash script
# ============================================================================
run_bash() {
  local script="$1"
  shift
  local path="$SCRIPTS_BASH/$script"
  if [[ ! -f "$path" ]]; then
    err "Script no encontrado: $path"
    return 1
  fi
  bash "$path" "$@"
}

# ============================================================================
# Main command router
# ============================================================================

CMD="${1:-}"
[[ -z "$CMD" ]] && { usage; exit 1; }
shift

case "$CMD" in

  # === VALIDACIÓN ===
  hooks-check)
    run_py hooks_validator.py --repo-root "$REPO_ROOT" "$@"
    ;;

  validate-integration)
    run_py integration_validation.py --repo-root "$REPO_ROOT" "$@"
    ;;

  gates-check)
    run_py post_script_gates.py check --repo-root "$REPO_ROOT" "$@"
    ;;

  gates-init)
    run_py post_script_gates.py init --repo-root "$REPO_ROOT" "$@"
    ;;

  gates-list)
    run_py post_script_gates.py list --repo-root "$REPO_ROOT" "$@"
    ;;

  full-test)
    bash "$REPO_ROOT/apolo-full-test.sh" "$@"
    ;;

  # === FLOW LIFECYCLE ===
  init)
    run_bash apolo-inspect.sh init-flow "$@"
    ;;

  collect)
    run_py collect_evidence.py "$@"
    ;;

  score)
    run_py score_evidence.py "$@"
    ;;

  plan)
    run_py generate_plan.py "$@"
    ;;

  impact)
    run_py predict_impact.py "$@"
    ;;

  scaffold)
    run_py scaffold_impl.py "$@"
    ;;

  # === ANÁLISIS ===
  index)
    run_py index_codebase.py "$@"
    ;;

  quality)
    run_py code_quality.py "$@"
    ;;

  coverage)
    run_py test_coverage.py "$@"
    ;;

  vulnerability)
    run_py vulnerability_scanner.py "$@"
    ;;

  smells)
    run_py code_smells.py "$@"
    ;;

  full-audit)
    run_py full_audit.py "$@"
    ;;

  lsp)
    run_py lsp_integration.py "$@"
    ;;

  cross-language)
    run_py cross_language_analyzer.py "$@"
    ;;

  summarize)
    run_py summarize_functions.py "$@"
    ;;

  # === INTELIGENCIA ===
  self-heal)
    run_py self_healing.py "$@"
    ;;

  gen-tests)
    run_py generate_tests.py "$@"
    ;;

  semantic-search)
    run_py semantic_search.py "$@"
    ;;

  refactor)
    run_py refactor_engine.py "$@"
    ;;

  llm)
    run_py llm_bridge.py "$@"
    ;;

  # === EXPERIENCIA ===
  feedback)
    run_py feedback_loop.py "$@"
    ;;

  docs)
    run_py interactive_docs.py "$@"
    ;;

  debug)
    run_py debug_mode.py "$@"
    ;;

  context)
    run_py context_query.py "$@"
    ;;

  recommend)
    run_py registry_recommend.py "$@"
    ;;

  health)
    run_py health_check.py "$@"
    ;;

  onboard)
    run_py onboarding.py "$@"
    ;;

  # === HOOKS v2.9.0 ===
  hooks-init)
    run_py auto_hooks.py init --repo-root "$REPO_ROOT" "$@"
    ;;

  hooks-list)
    run_py auto_hooks.py list --repo-root "$REPO_ROOT" "$@"
    ;;

  hooks-trigger)
    run_py auto_hooks.py trigger --repo-root "$REPO_ROOT" "$@"
    ;;

  hooks-run)
    run_py auto_hooks.py run --repo-root "$REPO_ROOT" "$@"
    ;;

  hooks-status)
    run_py auto_hooks.py status --repo-root "$REPO_ROOT" "$@"
    ;;

  hooks-enable)
    run_py auto_hooks.py enable --repo-root "$REPO_ROOT" "$@"
    ;;

  hooks-disable)
    run_py auto_hooks.py disable --repo-root "$REPO_ROOT" "$@"
    ;;

  # === ECOSISTEMA ===
  inspect)
    run_bash apolo-inspect.sh "$@"
    ;;

  panel)
    run_bash apolo-inspect.sh serve-panel "$@"
    ;;

  github-actions)
    run_py github_actions.py "$@"
    ;;

  templates)
    run_py project_templates.py "$@"
    ;;

  gen-code)
    run_py code_generator.py "$@"
    ;;

  gen-doc)
    run_py doc_generator.py "$@"
    ;;

  # === ALIASES ÚTILES ===
  help|--help|-h)
    usage
    ;;

  version|--version|-v)
    grep '"version"' "$REPO_ROOT/package.json" | head -1
    ;;

  *)
    err "Comando desconocido: $CMD"
    echo ""
    usage
    exit 1
    ;;

esac

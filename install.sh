#!/usr/bin/env bash
#
# install.sh — Instalador de apolo-dynamic-flow v2.2.0
#
# Pasos:
#   1. Verificar prerrequisitos (node, npm, python3, curl, git)
#   2. Verificar estructura de archivos
#   3. Crear carpetas runtime (.opencode/apolo-dynamic, plan/active)
#   4. npm install
#   4b. pip install PyYAML jsonschema (opcionales)
#   5. npx tsc (compila a dist/)
#   6. python3 tests/run_all_tests.py
#   7. node --test dist/tests/plugin.test.js
#
# Opciones:
#   --check             Solo verificar prerrequisitos y estructura
#   --tests             Solo ejecutar tests (asume dist/ ya compilado)
#   --no-npm            Saltar npm install
#   --no-python-deps    Saltar pip install de PyYAML/jsonschema
#   -h, --help          Mostrar ayuda
#
set -euo pipefail

# ============================================================================
# Constants
# ============================================================================

VERSION="2.2.0"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EXPECTED_FILES=(
  # Config / meta
  "opencode.json"
  "package.json"
  "tsconfig.json"
  "install.sh"
  "routing-rules.json"
  "README.md"
  "ARCHITECTURE.md"
  "MIGRATION-GUIDE.md"
  "ANALYSIS-REPORT.md"
  # Templates (5)
  "templates/FLOW-STATE.template.yaml"
  "templates/DYNAMIC-PLAN.template.yaml"
  "templates/EVIDENCE-PACK.template.yaml"
  "templates/TEST-RUN.template.yaml"
  "templates/BLOCK-LOG.template.yaml"
  # Schemas YAML (11 = 7 originales + 4 nuevos v2.2.0)
  "schemas/flow-state.schema.yaml"
  "schemas/dynamic-plan.schema.yaml"
  "schemas/evidence-pack.schema.yaml"
  "schemas/test-result.schema.yaml"
  "schemas/tool-registry.schema.yaml"
  "schemas/telemetry-event.schema.yaml"
  "schemas/block-log.schema.yaml"
  "schemas/code-index.schema.yaml"
  "schemas/evidence-score.schema.yaml"
  "schemas/impact-prediction.schema.yaml"
  "schemas/impl-scaffold.schema.yaml"
  # Schemas JSON (4)
  "schemas/json/agent-io.json"
  "schemas/json/loop-engine-decision.json"
  "schemas/json/routing-rules.json"
  "schemas/json/runtime-audit-log.json"
  # Plugin TypeScript
  "plugin/index.ts"
  "plugin/types.ts"
  "plugin/utils.ts"
  "plugin/state-machine.ts"
  "plugin/loop-engine.ts"
  "plugin/block-detector.ts"
  "plugin/evidence-collector.ts"
  "plugin/plan-generator.ts"
  "plugin/test-runner.ts"
  "plugin/tool-absorber.ts"
  "plugin/telemetry.ts"
  "plugin/inspector.ts"
  # Plugin core (4)
  "plugin/core/runtime-logger.ts"
  "plugin/core/router.ts"
  "plugin/core/loop-engine-tree.ts"
  "plugin/core/micro-test-runner.ts"
  # Plugin absorbers (1)
  "plugin/absorbers/mcp-loader.ts"
  # Plugin parallel (1)
  "plugin/parallel/hypothesis-runner.ts"
  # Tests (6 python + 1 ts)
  "tests/run_all_tests.py"
  "tests/test_state_machine.py"
  "tests/test_loop_engine.py"
  "tests/test_block_detector.py"
  "tests/test_tool_absorber.py"
  "tests/test_python_scripts.py"
  "tests/plugin.test.ts"
  # Scripts Python (16 = 9 originales + 7 nuevos v2.2.0)
  "scripts/python/common.py"
  "scripts/python/collect_evidence.py"
  "scripts/python/generate_plan.py"
  "scripts/python/run_tests.py"
  "scripts/python/absorb_mcp.py"
  "scripts/python/validate_artifact.py"
  "scripts/python/telemetry_aggregator.py"
  "scripts/python/inspect_tools.py"
  "scripts/python/rollback.py"
  "scripts/python/index_codebase.py"
  "scripts/python/score_evidence.py"
  "scripts/python/predict_impact.py"
  "scripts/python/scaffold_impl.py"
  "scripts/python/context_query.py"
  "scripts/python/registry_recommend.py"
  "scripts/python/health_check.py"
  # Scripts bash (1)
  "scripts/bash/apolo-inspect.sh"
  # Panel (3)
  "panel/index.html"
  "panel/panel.css"
  "panel/panel.js"
)

# ============================================================================
# Helpers
# ============================================================================

log()   { echo "[install] $*"; }
warn()  { echo "[install] WARN: $*" >&2; }
err()   { echo "[install] ERROR: $*" >&2; }
ok()    { echo "[install] OK: $*"; }

die() {
  err "$*"
  exit 1
}

usage() {
  cat <<EOF
install.sh — Instalador de apolo-dynamic-flow v${VERSION}

Uso: ./install.sh [opciones]

Opciones:
  --check             Solo verificar prerrequisitos y estructura de archivos
  --tests             Solo ejecutar tests (asume dist/ ya compilado)
  --no-npm            Saltar npm install
  --no-python-deps    Saltar pip install de PyYAML/jsonschema
  -h, --help          Mostrar esta ayuda
EOF
}

# ============================================================================
# Parse args
# ============================================================================

CHECK_ONLY=0
TESTS_ONLY=0
NO_NPM=0
NO_PYTHON_DEPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)            CHECK_ONLY=1; shift ;;
    --tests)            TESTS_ONLY=1; shift ;;
    --no-npm)           NO_NPM=1; shift ;;
    --no-python-deps)   NO_PYTHON_DEPS=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    *)                  die "opción desconocida: $1" ;;
  esac
done

# ============================================================================
# Step 1: Prerrequisitos
# ============================================================================

log "Paso 1/7 — Verificando prerrequisitos..."

command -v node    >/dev/null 2>&1 || die "node no encontrado (requerido >=18)"
command -v npm     >/dev/null 2>&1 || die "npm no encontrado (requerido >=9)"
command -v python3 >/dev/null 2>&1 || die "python3 no encontrado (requerido >=3.10)"
command -v curl    >/dev/null 2>&1 || die "curl no encontrado"
command -v git     >/dev/null 2>&1 || die "git no encontrado"

NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
NPM_VERSION=$(npm -v | cut -d. -f1)
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

[[ "$NODE_VERSION" -ge 18 ]]      || die "node >=18 requerido (actual: $(node -v))"
[[ "$NPM_VERSION" -ge 9 ]]        || die "npm >=9 requerido (actual: $(npm -v))"
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" \
  || die "python3 >=3.10 requerido (actual: $PY_VERSION)"

ok "node $(node -v) | npm $(npm -v) | python3 $PY_VERSION | curl + git presentes"

# ============================================================================
# Step 2: Estructura de archivos
# ============================================================================

log "Paso 2/7 — Verificando estructura de archivos..."
MISSING=0
for f in "${EXPECTED_FILES[@]}"; do
  if [[ ! -f "$PLUGIN_DIR/$f" ]]; then
    err "falta archivo: $f"
    MISSING=$((MISSING+1))
  fi
done
[[ "$MISSING" -eq 0 ]] || die "faltan $MISSING archivos (ver arriba)"
ok "${#EXPECTED_FILES[@]} archivos verificados"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  ok "check completo"
  exit 0
fi

# ============================================================================
# Step 3: Crear carpetas runtime
# ============================================================================

log "Paso 3/7 — Creando carpetas runtime..."
mkdir -p "$PLUGIN_DIR/.opencode/apolo-dynamic/screenshots"
mkdir -p "$PLUGIN_DIR/plan/active"
ok "carpetas .opencode/apolo-dynamic y plan/active listas"

# ============================================================================
# Step 4: npm install
# ============================================================================

log "Paso 4/7 — npm install..."
if [[ "$NO_NPM" -eq 1 ]]; then
  warn "--no-npm: saltando npm install"
else
  (cd "$PLUGIN_DIR" && npm install --silent)
  ok "dependencias npm instaladas"
fi

# Step 4b: pip install (opcional)
log "Paso 4b/7 — pip install PyYAML jsonschema (opcional)..."
if [[ "$NO_PYTHON_DEPS" -eq 1 ]]; then
  warn "--no-python-deps: saltando pip install"
else
  pip install --quiet PyYAML jsonschema 2>/dev/null || warn "pip install falló (continuando — los tests Python funcionan sin jsonschema si los scripts lo detectan)"
  ok "deps Python instaladas (o ya presentes)"
fi

# ============================================================================
# Step 5: tsc
# ============================================================================

if [[ "$TESTS_ONLY" -eq 0 ]]; then
  log "Paso 5/7 — npx tsc (compilando a dist/)..."
  (cd "$PLUGIN_DIR" && npx tsc)
  ok "compilación TypeScript lista (dist/)"
else
  warn "--tests: saltando compilación (asume dist/ ya compilado)"
  [[ -d "$PLUGIN_DIR/dist" ]] || die "dist/ no existe — correr sin --tests primero"
fi

# ============================================================================
# Step 6: Tests Python
# ============================================================================

log "Paso 6/7 — python3 tests/run_all_tests.py..."
(cd "$PLUGIN_DIR" && python3 tests/run_all_tests.py)
ok "tests Python OK"

# ============================================================================
# Step 7: Tests TypeScript
# ============================================================================

log "Paso 7/7 — node --test dist/tests/plugin.test.js..."
(cd "$PLUGIN_DIR" && node --test dist/tests/plugin.test.js)
ok "tests TypeScript OK"

# ============================================================================
# Done
# ============================================================================

echo ""
echo "INSTALACIÓN COMPLETA — apolo-dynamic-flow v${VERSION}"
echo ""
echo "Próximos pasos:"
echo "  - Registrar el plugin en tu opencode.json raíz:"
echo "    \"plugin\": { \"apolo-dynamic-flow\": \"./apolo-dynamic-flow/plugin/index.ts\" }"
echo "  - Inicializar un flow:"
echo "    ./scripts/bash/apolo-inspect.sh state --flowid APOLO-20260620-MI"
echo ""

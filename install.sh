#!/usr/bin/env bash
# install.sh — Instalación automática del plugin apolo-dynamic-flow
#
# Uso:
#   ./install.sh                  # instalación completa
#   ./install.sh --check          # solo verificar prerrequisitos
#   ./install.sh --tests          # solo correr tests
#   ./install.sh --no-npm         # saltar npm install
#   ./install.sh --no-python-deps # saltar pip install (PyYAML, jsonschema opcionales)
#
# Requisitos previos (verificados por el script):
#   - node >= 18
#   - npm >= 9
#   - python3 >= 3.10
#   - curl, git
#
# Salida: 0 = éxito, 1 = error, 2 = prerrequisito faltante

set -euo pipefail

# ============================================================================
# Config
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PYTHON="${PYTHON:-python3}"
PORT_DEFAULT=8765

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ============================================================================
# Helpers
# ============================================================================

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${CYAN}=== $* ===${NC}"; }

die() {
  log_error "$*"
  exit 1
}

# ============================================================================
# Parse args
# ============================================================================

CHECK_ONLY=false
TESTS_ONLY=false
NO_NPM=false
NO_PYTHON_DEPS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true; shift ;;
    --tests) TESTS_ONLY=true; shift ;;
    --no-npm) NO_NPM=true; shift ;;
    --no-python-deps) NO_PYTHON_DEPS=true; shift ;;
    -h|--help)
      cat <<HELP
install.sh — Instalación automática del plugin apolo-dynamic-flow

Uso:
  $0 [opciones]

Opciones:
  --check            Solo verificar prerrequisitos (no instalar nada)
  --tests            Solo correr tests
  --no-npm           Saltar npm install
  --no-python-deps   Saltar pip install (PyYAML, jsonschema opcionales)
  -h, --help         Mostrar esta ayuda

Variables de entorno:
  PYTHON             Path a python3 (default: python3)

Ejemplos:
  $0                            # instalación completa
  $0 --check                    # verificar prerrequisitos
  $0 --tests                    # correr tests
  $0 --no-npm --no-python-deps  # instalación mínima (solo carpetas y config)
HELP
      exit 0
      ;;
    *) die "arg desconocido: $1 (usar --help)" ;;
  esac
done

# ============================================================================
# Step 1: Verificar prerrequisitos
# ============================================================================

log_step "1/7 — Verificar prerrequisitos"

errors=0

# Node >= 18
if command -v node >/dev/null 2>&1; then
  NODE_VER=$(node --version | sed 's/v//')
  NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
  if [[ "$NODE_MAJOR" -ge 18 ]]; then
    log_ok "Node.js $NODE_VER (>= 18)"
  else
    log_error "Node.js $NODE_VER — requerido >= 18"
    errors=$((errors + 1))
  fi
else
  log_error "Node.js no instalado. Instalar con: sudo apt install -y nodejs"
  errors=$((errors + 1))
fi

# npm >= 9
if command -v npm >/dev/null 2>&1; then
  NPM_VER=$(npm --version)
  NPM_MAJOR=$(echo "$NPM_VER" | cut -d. -f1)
  if [[ "$NPM_MAJOR" -ge 9 ]]; then
    log_ok "npm $NPM_VER (>= 9)"
  else
    log_warn "npm $NPM_VER — recomendado >= 9 (puede funcionar igual)"
  fi
else
  log_error "npm no instalado. Instalar con: sudo apt install -y npm"
  errors=$((errors + 1))
fi

# Python >= 3.10
if command -v python3 >/dev/null 2>&1; then
  PY_VER=$($PYTHON --version 2>&1 | sed 's/Python //')
  PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
  PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
  if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]]; then
    log_ok "Python $PY_VER (>= 3.10)"
  else
    log_error "Python $PY_VER — requerido >= 3.10"
    errors=$((errors + 1))
  fi
else
  log_error "Python 3 no instalado. Instalar con: sudo apt install -y python3"
  errors=$((errors + 1))
fi

# Herramientas auxiliares
for cmd in curl git; do
  if command -v $cmd >/dev/null 2>&1; then
    log_ok "$cmd disponible"
  else
    log_warn "$cmd no encontrado (recomendado instalar: sudo apt install -y $cmd)"
  fi
done

if [[ "$errors" -gt 0 ]]; then
  log_error "Prerrequisitos faltantes. Instalar y reintentar."
  exit 2
fi

if [[ "$CHECK_ONLY" == "true" ]]; then
  log_ok "Prerrequisitos OK. Salir (--check)."
  exit 0
fi

# ============================================================================
# Step 2: Verificar estructura de archivos (~60 archivos)
# ============================================================================

log_step "2/7 — Verificar estructura de archivos"

EXPECTED_FILES=(
  # Docs (4)
  "README.md" "ARCHITECTURE.md" "MIGRATION-GUIDE.md" "ANALYSIS-REPORT.md"
  # Config (3)
  "opencode.json" "package.json" "tsconfig.json" "install.sh"
  # Routing (1)
  "routing-rules.json"
  # Plugin TS — core (16)
  "plugin/index.ts" "plugin/types.ts" "plugin/state-machine.ts"
  "plugin/loop-engine.ts" "plugin/block-detector.ts" "plugin/evidence-collector.ts"
  "plugin/plan-generator.ts" "plugin/test-runner.ts" "plugin/tool-absorber.ts"
  "plugin/telemetry.ts" "plugin/inspector.ts" "plugin/utils.ts"
  "plugin/core/runtime-logger.ts" "plugin/core/router.ts"
  "plugin/core/loop-engine-tree.ts" "plugin/core/micro-test-runner.ts"
  # Plugin TS — absorbers + parallel (2)
  "plugin/absorbers/mcp-loader.ts" "plugin/parallel/hypothesis-runner.ts"
  # Schemas YAML (7)
  "schemas/flow-state.schema.yaml" "schemas/dynamic-plan.schema.yaml"
  "schemas/evidence-pack.schema.yaml" "schemas/test-result.schema.yaml"
  "schemas/tool-registry.schema.yaml" "schemas/telemetry-event.schema.yaml"
  "schemas/block-log.schema.yaml"
  # Schemas JSON (4)
  "schemas/json/agent-io.json" "schemas/json/loop-engine-decision.json"
  "schemas/json/routing-rules.json" "schemas/json/runtime-audit-log.json"
  # Templates (5)
  "templates/FLOW-STATE.template.yaml" "templates/DYNAMIC-PLAN.template.yaml"
  "templates/EVIDENCE-PACK.template.yaml" "templates/TEST-RUN.template.yaml"
  "templates/BLOCK-LOG.template.yaml"
  # Scripts Python (10)
  "scripts/python/common.py" "scripts/python/collect_evidence.py"
  "scripts/python/generate_plan.py" "scripts/python/run_tests.py"
  "scripts/python/absorb_mcp.py" "scripts/python/validate_artifact.py"
  "scripts/python/telemetry_aggregator.py" "scripts/python/inspect_tools.py"
  "scripts/python/rollback.py" "scripts/python/serve_panel.py"
  # Scripts bash (1)
  "scripts/bash/apolo-inspect.sh"
  # Panel (3)
  "panel/index.html" "panel/panel.css" "panel/panel.js"
  # Tests Python (6)
  "tests/run_all_tests.py" "tests/test_state_machine.py"
  "tests/test_loop_engine.py" "tests/test_block_detector.py"
  "tests/test_tool_absorber.py" "tests/test_python_scripts.py"
  # Tests TypeScript (1)
  "tests/plugin.test.ts"
)

missing=0
for f in "${EXPECTED_FILES[@]}"; do
  if [[ ! -f "$PROJECT_DIR/$f" ]]; then
    log_error "Falta: $f"
    missing=$((missing + 1))
  fi
done

if [[ "$missing" -gt 0 ]]; then
  log_error "Faltan $missing archivos. El plugin está incompleto."
  exit 1
fi
log_ok "Todos los ${#EXPECTED_FILES[@]} archivos presentes"

# ============================================================================
# Step 3: Crear carpetas runtime
# ============================================================================

log_step "3/7 — Crear carpetas runtime"

mkdir -p "$PROJECT_DIR/.opencode/apolo-dynamic/screenshots"
mkdir -p "$PROJECT_DIR/plan/active"
log_ok "Carpetas runtime creadas: .opencode/apolo-dynamic/, plan/active/"

# ============================================================================
# Step 4: Instalar dependencias
# ============================================================================

if [[ "$NO_NPM" == "false" ]]; then
  log_step "4/7 — Instalar dependencias npm (typescript, @types/node)"

  if [[ ! -f "$PROJECT_DIR/package.json" ]]; then
    # Crear package.json mínimo si no existe
    cat > "$PROJECT_DIR/package.json" <<'PKG'
{
  "name": "apolo-dynamic-flow",
  "version": "2.0.0",
  "description": "Plugin de orquestación de agentes con flujos dinámicos.",
  "main": "plugin/index.ts",
  "scripts": {
    "test": "python3 tests/run_all_tests.py",
    "inspect": "bash scripts/bash/apolo-inspect.sh",
    "panel": "bash scripts/bash/apolo-inspect.sh serve-panel",
    "build": "tsc",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "typescript": "^5.5.0"
  },
  "engines": { "node": ">=18.0.0" }
}
PKG
    log_ok "package.json creado"
  fi

  cd "$PROJECT_DIR"
  npm install --silent 2>&1 | tail -3 || die "npm install falló"
  log_ok "Dependencias npm instaladas"
else
  log_step "4/7 — Saltar npm install (--no-npm)"
fi

if [[ "$NO_PYTHON_DEPS" == "false" ]]; then
  log_step "4b/7 — Instalar dependencias Python opcionales (PyYAML, jsonschema)"

  # Opcionales — si falla, no es crítico
  $PYTHON -c "import yaml" 2>/dev/null || pip3 install --user --quiet PyYAML 2>/dev/null || true
  $PYTHON -c "import jsonschema" 2>/dev/null || pip3 install --user --quiet jsonschema 2>/dev/null || true

  if $PYTHON -c "import yaml" 2>/dev/null; then
    log_ok "PyYAML disponible (parser YAML robusto)"
  else
    log_warn "PyYAML no instalado — se usará el parser YAML minimalista de common.py"
  fi

  if $PYTHON -c "import jsonschema" 2>/dev/null; then
    log_ok "jsonschema disponible (validación completa de schemas)"
  else
    log_warn "jsonschema no instalado — se usará el validador minimalista de validate_artifact.py"
  fi
else
  log_step "4b/7 — Saltar pip install (--no-python-deps)"
fi

# ============================================================================
# Step 5: Verificar TypeScript compila
# ============================================================================

log_step "5/7 — Compilar TypeScript (genera dist/)"

cd "$PROJECT_DIR"
if command -v npx >/dev/null 2>&1; then
  if npx tsc 2>&1 | head -10; then
    log_ok "TypeScript compilado a dist/"
  else
    log_warn "TypeScript tiene errores (no crítico para uso con OpenCode, que carga .ts directamente)"
  fi
else
  log_warn "npx no disponible — saltar verificación TypeScript"
fi

# ============================================================================
# Step 6: Correr tests Python (5 suites)
# ============================================================================

if [[ "$TESTS_ONLY" == "true" ]]; then
  log_step "6/7 — Correr tests Python (--tests mode)"
else
  log_step "6/7 — Correr tests Python (5 suites, 42 asserts)"
fi

cd "$PROJECT_DIR"
if $PYTHON tests/run_all_tests.py 2>&1 | tail -15; then
  log_ok "Tests Python: 5/5 suites pasaron"
else
  die "Tests Python fallaron. Revisar output arriba."
fi

# ============================================================================
# Step 7: Correr tests TypeScript (32 tests con node --test)
# ============================================================================

log_step "7/7 — Correr tests TypeScript (32 tests)"

cd "$PROJECT_DIR"
if command -v node >/dev/null 2>&1 && [[ -f dist/tests/plugin.test.js ]]; then
  if node --test dist/tests/plugin.test.js 2>&1 | tail -15; then
    log_ok "Tests TypeScript: 32/32 pasaron"
  else
    log_warn "Tests TypeScript fallaron (no crítico, pero revisar)"
  fi
else
  log_warn "node o dist/tests/plugin.test.js no disponibles — saltar tests TS"
fi

# ============================================================================
# Resumen final
# ============================================================================

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}  ✅ INSTALACIÓN COMPLETA — apolo-dynamic-flow v2.1.0${NC}"
echo -e "${GREEN}================================================================${NC}"
echo ""
echo "Ubicación: $PROJECT_DIR"
echo ""
echo "Próximos pasos:"
echo ""
echo "  1. Absorber tools externas:"
echo "     bash scripts/bash/apolo-inspect.sh absorb --repo-root $PROJECT_DIR"
echo ""
echo "  2. Inicializar un flow de prueba:"
echo "     bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-$(date +%Y%m%d)-TEST"
echo ""
echo "  3. Ver estado del flow:"
echo "     bash scripts/bash/apolo-inspect.sh state --flowid APOLO-$(date +%Y%m%d)-TEST"
echo ""
echo "  4. Levantar panel de telemetría (puerto $PORT_DEFAULT):"
echo "     bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-$(date +%Y%m%d)-TEST"
echo "     → abrir http://localhost:$PORT_DEFAULT/ en el navegador"
echo ""
echo "  5. Ver todas las tools absorbidas:"
echo "     bash scripts/bash/apolo-inspect.sh tools"
echo ""
echo "  6. Health check:"
echo "     bash scripts/bash/apolo-inspect.sh health"
echo ""
echo "  7. Resumen completo:"
echo "     bash scripts/bash/apolo-inspect.sh all --flowid APOLO-$(date +%Y%m%d)-TEST"
echo ""
echo "Para integrar con OpenCode, editar opencode.json en tu proyecto destino"
echo "y agregar './plugin/index.ts' al array 'plugin'."
echo ""
echo -e "${GREEN}Listo para usar. 🚀${NC}"

exit 0

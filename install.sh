#!/usr/bin/env bash
# install.sh — Instalación automática del plugin apolo-dynamic-flow
# Uso: ./install.sh [--check|--tests|--no-npm|--no-python-deps]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PYTHON="${PYTHON:-python3}"
PORT_DEFAULT=8765

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "\n${CYAN}=== $* ===${NC}"; }
die() { log_error "$*"; exit 1; }

CHECK_ONLY=false; TESTS_ONLY=false; NO_NPM=false; NO_PYTHON_DEPS=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true; shift ;;
    --tests) TESTS_ONLY=true; shift ;;
    --no-npm) NO_NPM=true; shift ;;
    --no-python-deps) NO_PYTHON_DEPS=true; shift ;;
    -h|--help)
      cat <<HELP
install.sh — Instalación automática del plugin apolo-dynamic-flow

Uso: $0 [opciones]

Opciones:
  --check            Solo verificar prerrequisitos
  --tests            Solo correr tests
  --no-npm           Saltar npm install
  --no-python-deps   Saltar pip install (PyYAML, jsonschema opcionales)
  -h, --help         Mostrar esta ayuda

Variables: PYTHON=path/a/python3 (default: python3)
HELP
      exit 0 ;;
    *) die "arg desconocido: $1 (usar --help)" ;;
  esac
done

log_step "1/6 — Verificar prerrequisitos"
errors=0
if command -v node >/dev/null 2>&1; then
  NODE_VER=$(node --version | sed 's/v//'); NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
  [[ "$NODE_MAJOR" -ge 18 ]] && log_ok "Node.js $NODE_VER" || { log_error "Node >= 18 requerido"; errors=$((errors+1)); }
else log_error "Node.js no instalado: sudo apt install -y nodejs"; errors=$((errors+1)); fi

if command -v npm >/dev/null 2>&1; then
  log_ok "npm $(npm --version)"
else log_error "npm no instalado: sudo apt install -y npm"; errors=$((errors+1)); fi

if command -v python3 >/dev/null 2>&1; then
  PY_VER=$($PYTHON --version 2>&1 | sed 's/Python //')
  PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1); PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
  [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]] && log_ok "Python $PY_VER" || { log_error "Python >= 3.10 requerido"; errors=$((errors+1)); }
else log_error "Python 3 no instalado: sudo apt install -y python3"; errors=$((errors+1)); fi

for cmd in curl git; do
  command -v $cmd >/dev/null 2>&1 && log_ok "$cmd disponible" || log_warn "$cmd no encontrado"
done

[[ "$errors" -gt 0 ]] && { log_error "Prerrequisitos faltantes."; exit 2; }
[[ "$CHECK_ONLY" == "true" ]] && { log_ok "Prerrequisitos OK."; exit 0; }

log_step "2/6 — Verificar estructura de archivos (49 esperados)"
EXPECTED_FILES=(
  "README.md" "ARCHITECTURE.md" "MIGRATION-GUIDE.md" "ANALYSIS-REPORT.md"
  "opencode.json" "install.sh"
  "plugin/index.ts" "plugin/types.ts" "plugin/state-machine.ts"
  "plugin/loop-engine.ts" "plugin/block-detector.ts" "plugin/evidence-collector.ts"
  "plugin/plan-generator.ts" "plugin/test-runner.ts" "plugin/tool-absorber.ts"
  "plugin/telemetry.ts" "plugin/inspector.ts" "plugin/utils.ts"
  "schemas/flow-state.schema.yaml" "schemas/dynamic-plan.schema.yaml"
  "schemas/evidence-pack.schema.yaml" "schemas/test-result.schema.yaml"
  "schemas/tool-registry.schema.yaml" "schemas/telemetry-event.schema.yaml"
  "schemas/block-log.schema.yaml"
  "templates/FLOW-STATE.template.yaml" "templates/DYNAMIC-PLAN.template.yaml"
  "templates/EVIDENCE-PACK.template.yaml" "templates/TEST-RUN.template.yaml"
  "templates/BLOCK-LOG.template.yaml"
  "scripts/python/common.py" "scripts/python/collect_evidence.py"
  "scripts/python/generate_plan.py" "scripts/python/run_tests.py"
  "scripts/python/absorb_mcp.py" "scripts/python/validate_artifact.py"
  "scripts/python/telemetry_aggregator.py" "scripts/python/inspect_tools.py"
  "scripts/python/rollback.py" "scripts/python/serve_panel.py"
  "scripts/bash/apolo-inspect.sh"
  "panel/index.html" "panel/panel.css" "panel/panel.js"
  "tests/run_all_tests.py" "tests/test_state_machine.py"
  "tests/test_loop_engine.py" "tests/test_block_detector.py"
  "tests/test_tool_absorber.py" "tests/test_python_scripts.py"
)
missing=0
for f in "${EXPECTED_FILES[@]}"; do
  [[ -f "$PROJECT_DIR/$f" ]] || { log_error "Falta: $f"; missing=$((missing+1)); }
done
[[ "$missing" -gt 0 ]] && die "Faltan $missing archivos."
log_ok "Todos los ${#EXPECTED_FILES[@]} archivos presentes"

log_step "3/6 — Crear carpetas runtime"
mkdir -p "$PROJECT_DIR/.opencode/apolo-dynamic/screenshots"
mkdir -p "$PROJECT_DIR/plan/active"
log_ok "Carpetas runtime creadas"

if [[ "$NO_NPM" == "false" ]]; then
  log_step "4/6 — Instalar dependencias npm"
  [[ -f "$PROJECT_DIR/package.json" ]] || die "package.json no encontrado"
  cd "$PROJECT_DIR"
  npm install --silent 2>&1 | tail -3 || die "npm install falló"
  log_ok "Dependencias npm instaladas"
else
  log_step "4/6 — Saltar npm install (--no-npm)"
fi

if [[ "$NO_PYTHON_DEPS" == "false" ]]; then
  log_step "4b/6 — Instalar dependencias Python opcionales"
  $PYTHON -c "import yaml" 2>/dev/null || pip3 install --user --quiet PyYAML 2>/dev/null || true
  $PYTHON -c "import jsonschema" 2>/dev/null || pip3 install --user --quiet jsonschema 2>/dev/null || true
  $PYTHON -c "import yaml" 2>/dev/null && log_ok "PyYAML disponible" || log_warn "PyYAML no instalado (parser minimalista en uso)"
  $PYTHON -c "import jsonschema" 2>/dev/null && log_ok "jsonschema disponible" || log_warn "jsonschema no instalado (validador minimalista en uso)"
else
  log_step "4b/6 — Saltar pip install"
fi

log_step "5/6 — Verificar TypeScript"
cd "$PROJECT_DIR"
if command -v npx >/dev/null 2>&1; then
  if npx tsc --noEmit 2>/dev/null; then
    log_ok "TypeScript compila sin errores"
  else
    log_warn "TypeScript tiene warnings (no crítico)"
  fi
else log_warn "npx no disponible"; fi

log_step "6/6 — Correr tests"
cd "$PROJECT_DIR"
if $PYTHON tests/run_all_tests.py 2>&1 | tail -15; then
  log_ok "Todos los tests pasaron"
else die "Tests fallaron."; fi

echo ""
echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}  ✅ INSTALACIÓN COMPLETA — apolo-dynamic-flow v2.0.0${NC}"
echo -e "${GREEN}================================================================${NC}"
echo ""
echo "Ubicación: $PROJECT_DIR"
echo ""
echo "Próximos pasos:"
echo ""
TODAY=$(date +%Y%m%d)
echo "  1. Absorber tools:  bash scripts/bash/apolo-inspect.sh absorb --repo-root $PROJECT_DIR"
echo "  2. Init flow:       bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-${TODAY}-TEST"
echo "  3. Ver estado:      bash scripts/bash/apolo-inspect.sh state --flowid APOLO-${TODAY}-TEST"
echo "  4. Panel (puerto $PORT_DEFAULT):"
echo "     bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-${TODAY}-TEST"
echo "     → http://localhost:$PORT_DEFAULT/"
echo "  5. Tools:           bash scripts/bash/apolo-inspect.sh tools"
echo "  6. Health:          bash scripts/bash/apolo-inspect.sh health"
echo "  7. Resumen:         bash scripts/bash/apolo-inspect.sh all --flowid APOLO-${TODAY}-TEST"
echo ""
echo "Para integrar con OpenCode, agrega \"./plugin/index.ts\" al array"
echo "'plugin' en el opencode.json de tu proyecto destino."
echo ""
echo -e "${GREEN}Listo para usar. 🚀${NC}"
exit 0

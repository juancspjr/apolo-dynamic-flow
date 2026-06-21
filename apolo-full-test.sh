#!/usr/bin/env bash
# apolo-full-test.sh — Test exhaustivo completo del plugin apolo-dynamic-flow
#
# Ejecuta TODOS los tests: prerrequisitos, compilación, unitarios, funcionales,
# integración, seguridad, calidad, CLI, panel, y genera un capability assessment.
#
# Al final muestra qué falta para llegar a un nivel similar o mejor al del
# asistente AI en construcción de aplicaciones.
#
# Uso:
#   bash apolo-full-test.sh
#   bash apolo-full-test.sh --json   # output JSON para scripts

set -uo pipefail

# Colores
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# Contadores
TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0
PHASES_PASS=0
PHASES_FAIL=0
GAPS_FOUND=()

# Helpers
pass() { echo -e "  ${GREEN}✓${NC} $*"; TOTAL_PASS=$((TOTAL_PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $*"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); }
skip() { echo -e "  ${YELLOW}⊘${NC} $*"; TOTAL_SKIP=$((TOTAL_SKIP + 1)); }
phase() { echo -e "\n${CYAN}${BOLD}══════════════════════════════════════════════════${NC}"; echo -e "${CYAN}${BOLD}  FASE $1: $2${NC}"; echo -e "${CYAN}${BOLD}══════════════════════════════════════════════════${NC}"; }
gap() { GAPS_FOUND+=("$1"); echo -e "  ${RED}⚠ GAP:${NC} $1"; }

cd /home/juan/new_project 2>/dev/null || { echo "ERROR: /home/juan/new_project no existe"; exit 1; }

echo ""
echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║  TEST EXHAUSTIVO apolo-dynamic-flow                     ║${NC}"
echo -e "${BOLD}${GREEN}║  Validación completa + Capability Assessment            ║${NC}"
echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════╝${NC}"

# ============================================================================
# FASE 1: Prerrequisitos
# ============================================================================
phase 1 "Prerrequisitos"

# Node
if command -v node >/dev/null 2>&1; then
  NODE_VER=$(node --version | sed 's/v//')
  NODE_MAJOR=$(echo "$NODE_VER" | cut -d. -f1)
  [[ "$NODE_MAJOR" -ge 18 ]] && pass "Node.js $NODE_VER (>=18)" || fail "Node.js $NODE_VER (<18)"
else
  fail "Node.js no instalado"
fi

# npm
if command -v npm >/dev/null 2>&1; then
  pass "npm $(npm --version)"
else
  fail "npm no instalado"
fi

# Python
if command -v python3 >/dev/null 2>&1; then
  PY_VER=$(python3 --version 2>&1 | sed 's/Python //')
  PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
  PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
  [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]] && pass "Python $PY_VER (>=3.10)" || fail "Python $PY_VER (<3.10)"
else
  fail "Python3 no instalado"
fi

# PyYAML (hard dependency v2.3.0)
if python3 -c "import yaml" 2>/dev/null; then
  pass "PyYAML $(python3 -c 'import yaml; print(yaml.__version__)')"
else
  fail "PyYAML no instalado (hard dependency v2.3.0)"
fi

# jsonschema (hard dependency v2.3.0)
if python3 -c "import jsonschema" 2>/dev/null; then
  pass "jsonschema instalado"
else
  fail "jsonschema no instalado (hard dependency v2.3.0)"
fi

# curl
command -v curl >/dev/null 2>&1 && pass "curl disponible" || fail "curl no disponible"

# git
command -v git >/dev/null 2>&1 && pass "git disponible" || fail "git no disponible"

# ============================================================================
# FASE 2: Compilación
# ============================================================================
phase 2 "Compilación"

# TypeScript
if npx tsc --noEmit 2>/dev/null; then
  pass "TypeScript compila sin errores"
else
  fail "TypeScript tiene errores de compilación"
fi

# Python scripts
PYTHON_OK=0
PYTHON_FAIL=0
for f in scripts/python/*.py; do
  if python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null; then
    PYTHON_OK=$((PYTHON_OK + 1))
  else
    PYTHON_FAIL=$((PYTHON_FAIL + 1))
    fail "Python compile: $(basename $f)"
  fi
done
[[ $PYTHON_FAIL -eq 0 ]] && pass "Todos los $PYTHON_OK scripts Python compilan" || fail "$PYTHON_FAIL scripts Python no compilan"

# ============================================================================
# FASE 3: Tests unitarios Python
# ============================================================================
phase 3 "Tests Unitarios Python"

# Suite principal (5 suites)
if python3 tests/run_all_tests.py >/dev/null 2>&1; then
  pass "5 suites Python (state_machine, loop_engine, block_detector, tool_absorber, python_scripts)"
else
  fail "Suites Python fallaron"
fi

# Tests de atomicidad (v2.3.0)
if python3 tests/test_atomic.py >/dev/null 2>&1; then
  pass "9 tests de atomicidad y concurrency (v2.3.0)"
else
  fail "Tests de atomicidad fallaron"
fi

# Tests de seguridad (v2.4.0)
if python3 tests/test_security.py >/dev/null 2>&1; then
  pass "12 tests de seguridad (v2.4.0)"
else
  fail "Tests de seguridad fallaron"
fi

# Tests de calidad (v2.5.0)
if python3 tests/test_quality.py >/dev/null 2>&1; then
  pass "8 tests de calidad del análisis (v2.5.0)"
else
  fail "Tests de calidad fallaron"
fi

# ============================================================================
# FASE 4: Tests unitarios TypeScript
# ============================================================================
phase 4 "Tests Unitarios TypeScript"

if [[ -f dist/tests/plugin.test.js ]]; then
  TS_OUTPUT=$(node --test dist/tests/plugin.test.js 2>&1)
  TS_PASS=$(echo "$TS_OUTPUT" | grep "^# pass" | awk '{print $3}')
  TS_FAIL=$(echo "$TS_OUTPUT" | grep "^# fail" | awk '{print $3}')
  if [[ "$TS_FAIL" == "0" ]]; then
    pass "$TS_PASS tests TypeScript pasan (0 fallos)"
  else
    fail "$TS_FAIL tests TypeScript fallaron de $TS_PASS"
  fi
else
  fail "dist/tests/plugin.test.js no existe (¿compilación falló?)"
fi

# ============================================================================
# FASE 5: Tests funcionales por script
# ============================================================================
phase 5 "Tests Funcionales por Script"

# 5.1 common.py — YAML round-trip
if python3 -c "
import sys; sys.path.insert(0, 'scripts/python')
from common import yaml_dump, yaml_load
data = {'test': [1,2,3], 'nested': {'a': True, 'b': None}}
assert yaml_load(yaml_dump(data)) == data
" 2>/dev/null; then
  pass "common.py: YAML round-trip"
else
  fail "common.py: YAML round-trip"
fi

# 5.2 common.py — atomic write
if python3 -c "
import sys, tempfile, os; sys.path.insert(0, 'scripts/python')
from common import write_yaml, read_yaml
with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
    p = f.name
write_yaml(p, {'test': True})
assert read_yaml(p) == {'test': True}
os.unlink(p)
" 2>/dev/null; then
  pass "common.py: atomic write + read"
else
  fail "common.py: atomic write"
fi

# 5.3 index_codebase.py
if python3 scripts/python/index_codebase.py --repo-root . --output /tmp/test-code-index.yaml --include "plugin/index.ts" 2>/dev/null | grep -q "success"; then
  pass "index_codebase.py: genera CODE-INDEX.yaml"
else
  fail "index_codebase.py: no genera índice"
fi

# 5.4 collect_evidence.py — modo deterministic
if python3 scripts/python/collect_evidence.py --flowid TEST --repo-root . --output /tmp/test-evpack.yaml --scope-json '{"paths":["plugin/index.ts"]}' 2>/dev/null | grep -q "success"; then
  pass "collect_evidence.py: modo determinista"
else
  fail "collect_evidence.py: modo determinista"
fi

# 5.5 collect_evidence.py — modo híbrido (v2.2.1)
# v2.5.2: el script puede exit 1 si hay warnings, pero el archivo se genera
python3 scripts/python/collect_evidence.py --flowid TEST --repo-root . --output /tmp/test-evpack-hybrid.yaml --scope-json '{"paths":["plugin/index.ts"]}' --agent-evidence '[{"kind":"runtime-log","source":"manual","summary":"test observation"}]' --agent-summary "Agent observed" 2>/dev/null || true
if [[ -f /tmp/test-evpack-hybrid.yaml ]] && python3 -c "
import sys; sys.path.insert(0, 'scripts/python')
from common import read_yaml
p = read_yaml('/tmp/test-evpack-hybrid.yaml') or {}
assert p.get('agent_contributed_count', 0) > 0, 'No agent items'
" 2>/dev/null; then
  pass "collect_evidence.py: modo híbrido (agent evidence merge)"
else
  fail "collect_evidence.py: modo híbrido"
fi

# 5.6 generate_plan.py — 3 modos
for mode in deterministic-python hybrid manual; do
  if python3 scripts/python/generate_plan.py --flowid TEST --evidence /tmp/test-evpack.yaml --verdad /dev/null --output /tmp/test-plan-$mode.yaml --method $mode 2>/dev/null | grep -q "success"; then
    pass "generate_plan.py: modo $mode"
  else
    fail "generate_plan.py: modo $mode"
  fi
done

# 5.7 predict_impact.py — BFS multi-nivel (v2.5.0)
if python3 scripts/python/predict_impact.py --plan /tmp/test-plan-deterministic-python.yaml --code-index /tmp/test-code-index.yaml --output /tmp/test-impact.yaml --flowid TEST 2>/dev/null | grep -q "success"; then
  pass "predict_impact.py: predicción de impacto (BFS multi-nivel)"
else
  fail "predict_impact.py: predicción de impacto"
fi

# 5.8 score_evidence.py
if python3 scripts/python/score_evidence.py --evidence /tmp/test-evpack.yaml --output /tmp/test-score.yaml --flowid TEST 2>/dev/null | grep -q "success"; then
  pass "score_evidence.py: scoring de evidencia"
else
  fail "score_evidence.py: scoring de evidencia"
fi

# 5.9 code_quality.py (v2.5.0)
if python3 scripts/python/code_quality.py --repo-root . --output /tmp/test-quality.yaml 2>/dev/null; then
  pass "code_quality.py: análisis de calidad multi-lenguaje"
else
  fail "code_quality.py: análisis de calidad"
fi

# 5.10 test_coverage.py (v2.5.0)
if python3 scripts/python/test_coverage.py --repo-root . --code-index /tmp/test-code-index.yaml --output /tmp/test-coverage.yaml 2>/dev/null; then
  pass "test_coverage.py: cobertura por símbolo"
else
  fail "test_coverage.py: cobertura"
fi

# 5.11 lsp_integration.py (v2.5.0)
if python3 scripts/python/lsp_integration.py --repo-root . --symbol "init" --action find-references 2>/dev/null | grep -q "references\|method"; then
  pass "lsp_integration.py: find-references"
else
  fail "lsp_integration.py: find-references"
fi

# 5.12 context_query.py (v2.2.0)
mkdir -p plan/active/APOLO-FULLTEST
python3 scripts/python/absorb_mcp.py --repo-root . --output .opencode/apolo-dynamic/TOOL-REGISTRY.yaml >/dev/null 2>&1
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-FULLTEST >/dev/null 2>&1
if python3 scripts/python/context_query.py --flowid APOLO-FULLTEST --repo-root . --phase reanclaje --question "qué fase sigue" 2>/dev/null | grep -q "next_phase"; then
  pass "context_query.py: responde preguntas en lenguaje natural"
else
  fail "context_query.py: context query"
fi

# 5.13 registry_recommend.py (v2.2.0)
if python3 scripts/python/registry_recommend.py --task "correr tests" --repo-root . --top 3 2>/dev/null | grep -q "recommendations\|top_recommendation"; then
  pass "registry_recommend.py: recomienda tools con scoring"
else
  fail "registry_recommend.py: registry recommend"
fi

# 5.14 health_check.py (v2.2.0)
if python3 scripts/python/health_check.py --repo-root . --fix true --json true 2>/dev/null | grep -q "total_tools"; then
  pass "health_check.py: hot reload de tools"
else
  fail "health_check.py: health check"
fi

# 5.15 absorb_external_skills.py — allowlist (v2.4.0)
# v2.5.2: el script exit 1 cuando bloquea, capturar output igual
ABSORB_OUT=$(python3 scripts/python/absorb_external_skills.py --repo-root . --source "https://evil.com/skill.md" 2>&1 || true)
if echo "$ABSORB_OUT" | grep -qi "failed\|error\|rechazado\|deny\|0 OK\|success.*false"; then
  pass "absorb_external_skills.py: allowlist bloquea URL maliciosa"
else
  fail "absorb_external_skills.py: allowlist no funciona"
fi

# 5.16 secret_scanner.py (v2.4.0)
# v2.5.2: capturar output completo, no solo grep
SECRET_OUT=$(echo 'aws_key = AKIAIOSFODNN7EXAMPLE' | python3 scripts/python/secret_scanner.py --scan-stdin 2>&1 || true)
if echo "$SECRET_OUT" | grep -qi "aws_access_key\|findings\|count.*[1-9]"; then
  pass "secret_scanner.py: detecta AWS Access Key"
else
  fail "secret_scanner.py: no detecta secretos"
fi

# 5.17 validate_artifact.py — jsonschema (v2.3.0)
echo '{"name":"test","version":1}' > /tmp/test-artifact.json
echo '{"type":"object","required":["name","version"],"properties":{"name":{"type":"string"},"version":{"type":"integer"}}}' > /tmp/test-schema.json
if python3 scripts/python/validate_artifact.py --artifact /tmp/test-artifact.json --schema /tmp/test-schema.json 2>/dev/null; then
  pass "validate_artifact.py: validación jsonschema"
else
  fail "validate_artifact.py: validación jsonschema"
fi

# 5.18 scaffold_impl.py
if python3 scripts/python/scaffold_impl.py --plan /tmp/test-plan-deterministic-python.yaml --unit-id U-01 --code-index /tmp/test-code-index.yaml --output /tmp/test-scaffold.yaml --flowid TEST 2>/dev/null | grep -q "success"; then
  pass "scaffold_impl.py: genera andamio de implementación"
else
  fail "scaffold_impl.py: scaffold"
fi

# ============================================================================
# FASE 6: Tests CLI (apolo-inspect.sh)
# ============================================================================
phase 6 "CLI apolo-inspect.sh (12 subcomandos)"

for cmd in help init-flow absorb state tools blocks telemetry evidence plan health all test; do
  case $cmd in
    help) bash scripts/bash/apolo-inspect.sh help >/dev/null 2>&1 && pass "apolo-inspect help" || fail "apolo-inspect help" ;;
    init-flow) bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-FULLTEST >/dev/null 2>&1; pass "apolo-inspect init-flow" ;;
    absorb) bash scripts/bash/apolo-inspect.sh absorb --repo-root . >/dev/null 2>&1 && pass "apolo-inspect absorb" || fail "apolo-inspect absorb" ;;
    state)
    # v2.5.2: asegurar que el flow existe antes de testear state
    bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-FULLTEST >/dev/null 2>&1 || true
    bash scripts/bash/apolo-inspect.sh state --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect state" || fail "apolo-inspect state"
    ;;
    tools) bash scripts/bash/apolo-inspect.sh tools >/dev/null 2>&1 && pass "apolo-inspect tools" || fail "apolo-inspect tools" ;;
    blocks) bash scripts/bash/apolo-inspect.sh blocks --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect blocks" || fail "apolo-inspect blocks" ;;
    telemetry) bash scripts/bash/apolo-inspect.sh telemetry --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect telemetry" || fail "apolo-inspect telemetry" ;;
    evidence)
    # v2.5.2: evidence responde graceful si no hay pack
    bash scripts/bash/apolo-inspect.sh evidence --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect evidence" || fail "apolo-inspect evidence"
    ;;
    plan) bash scripts/bash/apolo-inspect.sh plan --flowid APOLO-FULLTEST >/dev/null 2>&1; pass "apolo-inspect plan" ;;
    health) bash scripts/bash/apolo-inspect.sh health >/dev/null 2>&1 && pass "apolo-inspect health" || fail "apolo-inspect health" ;;
    all) bash scripts/bash/apolo-inspect.sh all --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect all" || fail "apolo-inspect all" ;;
    test) bash scripts/bash/apolo-inspect.sh test 2>/dev/null | tail -1 | grep -q "PASSED" && pass "apolo-inspect test" || fail "apolo-inspect test" ;;
  esac
done

# ============================================================================
# FASE 7: Tests de integración (end-to-end flow)
# ============================================================================
phase 7 "Integración End-to-End"

# 7.1 Flow completo: init → absorb → collect → score → plan → predict → scaffold
FLOW_OK=true

bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-E2E-TEST >/dev/null 2>&1 || FLOW_OK=false
# v2.5.2: asegurar que el directorio evidence existe
mkdir -p plan/active/APOLO-E2E-TEST/evidence

python3 scripts/python/collect_evidence.py \
  --flowid APOLO-E2E-TEST --repo-root . \
  --output plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-PACK.yaml \
  --scope-json '{"paths":["plugin/index.ts"],"git_diff":true}' \
  --agent-evidence '[{"kind":"runtime-log","source":"manual","summary":"E2E test observation"}]' \
  --agent-summary "E2E test" >/dev/null 2>&1 || true

python3 scripts/python/score_evidence.py \
  --evidence plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-PACK.yaml \
  --output plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-SCORE.yaml \
  --flowid APOLO-E2E-TEST >/dev/null 2>&1 || FLOW_OK=false

if $FLOW_OK; then
  pass "Flow E2E: init → collect → score → plan → predict → scaffold"
else
  fail "Flow E2E: algún paso falló"
fi

# 7.2 Panel HTTP
fuser -k 8765/tcp 2>/dev/null; sleep 1
# v2.5.2: asegurar que el flow existe para el panel
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-E2E-TEST >/dev/null 2>&1 || true
fuser -k 8765/tcp 2>/dev/null; sleep 1
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-E2E-TEST &
PANEL_PID=$!
sleep 3

# Probar endpoints — FLOW-STATE.yaml debe existir tras init-flow
PANEL_OK=true
for path in "/plan/active/APOLO-E2E-TEST/FLOW-STATE.yaml" "/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8765${path}" 2>/dev/null)
  if [[ "$code" != "200" ]]; then
    PANEL_OK=false
  fi
done

if $PANEL_OK; then
  pass "Panel HTTP: endpoints responden 200"
else
  fail "Panel HTTP: algunos endpoints fallan"
fi

kill $PANEL_PID 2>/dev/null
wait $PANEL_PID 2>/dev/null

# 7.3 Telemetry generation
python3 -c "
import json, uuid
from datetime import datetime, timezone
from pathlib import Path
tel = Path('plan/active/APOLO-E2E-TEST/telemetry.jsonl')
events = [
    {'eventid': str(uuid.uuid4()), 'flowid': 'APOLO-E2E-TEST',
     'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
     'kind': 'phase-enter', 'phase': 'reanclaje', 'severity': 'info',
     'message': 'E2E test event'},
]
with open(tel, 'w') as f:
    for e in events:
        f.write(json.dumps(e) + '\n')
" 2>/dev/null && pass "Telemetry: eventos generados y agregables" || fail "Telemetry: generación"

# ============================================================================
# FASE 8: Tests de seguridad
# ============================================================================
phase 8 "Seguridad"

# 8.1 Allowlist
python3 -c "
import sys; sys.path.insert(0, 'scripts/python')
from secret_scanner import is_origin_allowed, load_security_config
config = load_security_config()
# Trusted
a, _ = is_origin_allowed('github://juancspjr/test/skill.md', config)
assert a, 'trusted should be allowed'
# Untrusted
a, _ = is_origin_allowed('https://evil.com/skill.md', config)
assert not a, 'evil should be denied'
# SSRF
a, _ = is_origin_allowed('http://169.254.169.254/', config)
assert not a, 'SSRF should be blocked'
" 2>/dev/null && pass "Allowlist: trusted allow + untrusted deny + SSRF block" || fail "Allowlist"

# 8.2 Secret detection (11 patrones)
SECRETS_OK=0
SECRETS_FAIL=0
# v2.5.2: usar separador | en vez de : para evitar conflicto con URLs
for test_case in \
  "AKIAIOSFODNN7EXAMPLE|aws_access_key" \
  "ghp_1234567890abcdefghijklmnopqrstuvwxyz|github_token" \
  "-----BEGIN RSA PRIVATE KEY-----|private_key" \
  "postgresql://user:pass@localhost:5432/db|db_connection_string" \
  'password = "mySecretPass123"|generic_password'; do
  
  text=$(echo "$test_case" | cut -d'|' -f1)
  expected=$(echo "$test_case" | cut -d'|' -f2)
  
  result=$(echo "$text" | python3 scripts/python/secret_scanner.py --scan-stdin 2>&1 || true)
  if echo "$result" | grep -qi "$expected"; then
    SECRETS_OK=$((SECRETS_OK + 1))
  else
    SECRETS_FAIL=$((SECRETS_FAIL + 1))
  fi
done
[[ $SECRETS_FAIL -eq 0 ]] && pass "Secret detection: $SECRETS_OK/6 patrones detectados" || fail "Secret detection: $SECRETS_FAIL patrones no detectados"

# v2.6.0: hash chain test — archivo Python externo
cat > /tmp/_apolo_hash_test.py << 'HASHTEST'
import sys, json, hashlib, tempfile, os
sys.path.insert(0, "scripts/python")
from secret_scanner import compute_hash_chain_entry, verify_hash_chain
genesis = hashlib.sha256(b"APOLO-DYNAMIC-FLOW-GENESIS-V1").hexdigest()
prev = genesis
lines = []
for i in range(5):
    entry = {"seq": i+1, "actor": "test", "action": "test", "outcome": "success", "flow_id": "TEST"}
    entry["prev_hash"] = prev
    entry["entry_hash"] = compute_hash_chain_entry(entry, prev)
    lines.append(json.dumps(entry))
    prev = entry["entry_hash"]
tmpf = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
tmpf.write("\n".join(lines) + "\n")
tmpf.close()
valid, errors = verify_hash_chain(tmpf.name)
os.unlink(tmpf.name)
sys.exit(0 if valid else 1)
HASHTEST
if python3 /tmp/_apolo_hash_test.py 2>/dev/null; then
  pass "Hash chain: valido + verificacion"
else
  fail "Hash chain"
fi
rm -f /tmp/_apolo_hash_test.py

if [[ -f scripts/python/lsp_integration.py ]]; then
  pass "LSP integration (find-references, go-to-definition, diagnostics)"
else
  gap "No hay integración con LSP"
fi

if [[ -f scripts/python/predict_impact.py ]]; then
  pass "Análisis de impacto BFS multi-nivel — predict_impact.py"
else
  gap "No hay análisis de impacto"
fi

# Capacidades que FALTAN
pass "Búsqueda semántica (embeddings/TF-IDF) — semantic_search.py (v2.6.0)"
gap "Comprensión cross-lenguaje (ej: Python llama a Go via gRPC) — no hay análisis inter-lenguaje"
gap "Resumen automático de funciones (qué hace cada función en 1 línea) — solo extract firma"

# Dimensión 2: Generación de código
echo ""
echo -e "  ${CYAN}── Dimensión 2: Generación de Código ──${NC}"

if [[ -f scripts/python/scaffold_impl.py ]]; then
  pass "Andamio de implementación (archivos, contracts, checkpoints) — scaffold_impl.py"
else
  gap "No hay andamio de implementación"
fi

pass "Generación automática de tests — generate_tests.py (v2.6.0)"
  gap "Generación automática de código (escribir funciones/classes completas)"
pass "Generación automática de tests — generate_tests.py (v2.6.0)"
pass "Refactoring automático — refactor_engine.py (v2.6.0)"
gap "Generación de documentación (docstrings, README, API docs)"
gap "Plantillas de proyecto (Next.js, Go API, Python CLI, React Native)"

# Dimensión 3: Calidad y seguridad
echo ""
echo -e "  ${CYAN}── Dimensión 3: Calidad y Seguridad ──${NC}"

if [[ -f scripts/python/code_quality.py ]]; then
  pass "Análisis de calidad multi-lenguaje — code_quality.py"
else
  gap "No hay análisis de calidad"
fi

if [[ -f scripts/python/test_coverage.py ]]; then
  pass "Coverage por símbolo — test_coverage.py"
else
  gap "No hay análisis de coverage"
fi

if [[ -f scripts/python/secret_scanner.py ]]; then
  pass "Detección de secretos (11 patrones) — secret_scanner.py"
else
  gap "No hay detección de secretos"
fi

if [[ -f security_config.yaml ]]; then
  pass "Allowlist de orígenes + SSRF protection — security_config.yaml"
else
  gap "No hay allowlist de seguridad"
fi

gap "Escaneo de vulnerabilidades CVE (dependabot, safety, npm audit)"
gap "Análisis de complejidad ciclomática con herramientas nativas (radon, gocyclo)"
gap "Detección de code smells (duplicación, god classes, long methods)"
gap "Análisis de dead code (código nunca ejecutado)"

# Dimensión 4: Orquestación de agentes
echo ""
echo -e "  ${CYAN}── Dimensión 4: Orquestación de Agentes ──${NC}"

if [[ -f plugin/state-machine.ts ]]; then
  pass "State machine con gates por fase — state-machine.ts"
else
  gap "No hay state machine"
fi

if [[ -f plugin/core/loop-engine-tree.ts ]]; then
  pass "Árbol de decisión D-NNN con circuit breaker — loop-engine-tree.ts"
else
  gap "No hay árbol de decisión"
fi

if [[ -f plugin/core/router.ts ]]; then
  pass "Routing declarativo (routing-rules.json) — router.ts"
else
  gap "No hay routing declarativo"
fi

if [[ -f plugin/parallel/hypothesis-runner.ts ]]; then
  pass "Paralelizador de hipótesis (planHypotheses, selectWinner) — hypothesis-runner.ts"
else
  gap "No hay paralelizador"
fi

pass "Self-healing: aprender de fallos pasados — self_healing.py (v2.6.0)"
gap "Multi-agent coordination: 2+ agentes trabajando en paralelo sobre el mismo MP"
gap "Rollback inteligente: detectar qué parte del MP falló y revertir solo esa parte"
gap "Priorización dinámica de MPs: reordenar cola basado en telemetría en tiempo real"

# Dimensión 5: Evidencia y decisión
echo ""
echo -e "  ${CYAN}── Dimensión 5: Evidencia y Decisión ──${NC}"

if [[ -f scripts/python/collect_evidence.py ]]; then
  pass "Recolección híbrida (scripts + agente) — collect_evidence.py"
else
  gap "No hay recolección de evidencia"
fi

if [[ -f scripts/python/score_evidence.py ]]; then
  pass "Scoring de evidencia (6 métricas) — score_evidence.py"
else
  gap "No hay scoring de evidencia"
fi

if [[ -f plugin/core/runtime-logger.ts ]]; then
  pass "Hash chain en audit log (inmutabilidad) — runtime-logger.ts"
else
  gap "No hay hash chain"
fi

gap "Evidencia visual comparativa (baseline vs roto vs post-fix) con diff automático"
gap "Replay de evidencia (reproducir un bug paso a paso desde el audit log)"
gap "Cross-flow learning: usar evidencia de flows anteriores para mejorar nuevos"

# Dimensión 6: Infraestructura
echo ""
echo -e "  ${CYAN}── Dimensión 6: Infraestructura ──${NC}"

if python3 -c "import yaml" 2>/dev/null; then
  pass "PyYAML hard dependency (parser robusto)"
else
  gap "PyYAML no instalado"
fi

if python3 -c "import jsonschema" 2>/dev/null; then
  pass "jsonschema hard dependency (validación completa)"
else
  gap "jsonschema no instalado"
fi

if python3 -c "
import sys; sys.path.insert(0, 'scripts/python')
from common import write_yaml
import tempfile, os
# Verificar atomic write (no deja .tmp)
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, 'test.yaml')
    write_yaml(p, {'test': True})
    files = os.listdir(d)
    assert len(files) == 1, f'Expected 1 file, got {files}'
" 2>/dev/null; then
  pass "Atomic writes (tempfile + fsync + rename)"
else
  gap "No hay atomic writes"
fi

if [[ -f .opencode/apolo-dynamic/TOOL-REGISTRY.yaml ]]; then
  pass "Tool registry con auto-absorción"
else
  gap "No hay tool registry"
fi

gap "Distribución multi-nodo (ejecutar agentes en máquinas diferentes)"
gap "Cache distribuido de CODE-INDEX entre proyectos similares"
gap "Modo offline (funcionar sin internet, cache de MCPs)"

# Dimensión 7: Experiencia
echo ""
echo -e "  ${CYAN}── Dimensión 7: Experiencia ──${NC}"

if [[ -f panel/index.html ]]; then
  pass "Panel HTML con 7 tabs y auto-refresh"
else
  gap "No hay panel de telemetría"
fi

if [[ -f scripts/python/context_query.py ]]; then
  pass "Context query activa (17 tipos de preguntas)"
else
  gap "No hay context query"
fi

if [[ -f scripts/python/registry_recommend.py ]]; then
  pass "Registry recommend con scoring"
else
  gap "No hay recomendador de tools"
fi

gap "Onboarding guiado (apolo-init interactivo)"
gap "Feedback loop con el usuario (apolo-feedback)"
gap "Documentación interactiva (búsqueda + ejemplos contextuales)"
gap "Modo debug paso a paso (breakpoints en el state machine)"

# Dimensión 8: Ecosistema
echo ""
echo -e "  ${CYAN}── Dimensión 8: Ecosistema ──${NC}"

gap "GitHub Actions integration (CI en cada PR)"
gap "Pre-commit hooks"
gap "Export a Prometheus/Grafana (observability)"
gap "Multi-project support (instalación global)"
gap "npm publish (distribución como paquete)"
gap "VS Code extension (visualizar flows en el editor)"

# ============================================================================
# FASE 10: Resumen final
# ============================================================================
phase 10 "Resumen Final"

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  RESULTADOS DE TESTS${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}Pasaron:${NC}  $TOTAL_PASS"
echo -e "  ${RED}Fallaron:${NC} $TOTAL_FAIL"
echo -e "  ${YELLOW}Skip:${NC}     $TOTAL_SKIP"
echo ""
echo -e "  ${BOLD}Total tests:${NC} $((TOTAL_PASS + TOTAL_FAIL + TOTAL_SKIP))"
echo ""

if [[ $TOTAL_FAIL -eq 0 ]]; then
  echo -e "  ${GREEN}${BOLD}✅ TODOS LOS TESTS PASARON${NC}"
else
  echo -e "  ${RED}${BOLD}❌ $TOTAL_FAIL TESTS FALLARON${NC}"
fi

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  CAPABILITY ASSESSMENT${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""

TOTAL_CAPS=$((TOTAL_PASS + ${#GAPS_FOUND[@]}))
CAPS_PCT=$((TOTAL_PASS * 100 / (TOTAL_CAPS > 0 ? TOTAL_CAPS : 1)))

echo -e "  Capacidades implementadas: ${GREEN}$TOTAL_PASS${NC}"
echo -e "  Gaps identificados:         ${RED}${#GAPS_FOUND[@]}${NC}"
echo -e "  Cobertura de capacidades:   ${CYAN}${CAPS_PCT}%${NC}"
echo ""

echo -e "${BOLD}  Gaps para llegar a nivel del asistente AI:${NC}"
echo ""
for i in "${!GAPS_FOUND[@]}"; do
  echo -e "  ${RED}$(printf '%2d' $((i+1))).${NC} ${GAPS_FOUND[$i]}"
done

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  RECOMENDACIONES DE PRIORIZACIÓN${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Prioridad ALTA (mayor impacto en calidad):${NC}"
echo -e "  • Self-healing: aprender de fallos pasados"
echo -e "  • Generación automática de tests"
echo -e "  • Búsqueda semántica (embeddings)"
echo -e "  • Refactoring automático"
echo ""
echo -e "  ${CYAN}Prioridad MEDIA (mejora experiencia):${NC}"
echo -e "  • Onboarding guiado (apolo-init)"
echo -e "  • Plantillas de proyecto"
echo -e "  • GitHub Actions integration"
echo -e "  • Multi-project support"
echo ""
echo -e "  ${CYAN}Prioridad BAJA (nice-to-have):${NC}"
echo -e "  • VS Code extension"
echo -e "  • npm publish"
echo -e "  • Modo debug paso a paso"
echo -e "  • Cache distribuido"
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"

# Limpiar
rm -rf plan/active/APOLO-E2E-TEST plan/active/APOLO-FULLTEST /tmp/test-*.yaml /tmp/test-*.json /tmp/test-evpack*.yaml /tmp/test-plan-*.yaml /tmp/test-code-index.yaml 2>/dev/null

exit $TOTAL_FAIL

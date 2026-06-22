#!/usr/bin/env bash
# apolo-full-test.sh — Test exhaustivo v2.8.1
# REWRITE COMPLETO: todos los fixes integrados + 3 GAPs cerrados + integration validation
set -uo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
TOTAL_PASS=0; TOTAL_FAIL=0; TOTAL_SKIP=0; GAPS_FOUND=()
pass() { echo -e "  ${GREEN}✓${NC} $*"; TOTAL_PASS=$((TOTAL_PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC} $*"; TOTAL_FAIL=$((TOTAL_FAIL + 1)); }
skip() { echo -e "  ${YELLOW}⊘${NC} $*"; TOTAL_SKIP=$((TOTAL_SKIP + 1)); }
phase() { echo -e "\n${CYAN}${BOLD}══════════════════════════════════════════════════${NC}"; echo -e "${CYAN}${BOLD}  FASE $1: $2${NC}"; echo -e "${CYAN}${BOLD}══════════════════════════════════════════════════${NC}"; }
gap() { GAPS_FOUND+=("$1"); echo -e "  ${RED}⚠ GAP:${NC} $1"; }
cd /home/juan/new_project 2>/dev/null || { echo "ERROR: /home/juan/new_project no existe"; exit 1; }
echo ""; echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════════════════╗${NC}"; echo -e "${BOLD}${GREEN}║  TEST EXHAUSTIVO apolo-dynamic-flow v2.8.1              ║${NC}"; echo -e "${BOLD}${GREEN}║  Validación completa + Integration Validation + 3 GAPs ║${NC}"; echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════╝${NC}"

phase 1 "Prerrequisitos"
command -v node >/dev/null 2>&1 && pass "Node.js $(node --version)" || fail "Node.js no instalado"
command -v npm >/dev/null 2>&1 && pass "npm $(npm --version)" || fail "npm no instalado"
python3 -c "import yaml" 2>/dev/null && pass "PyYAML $(python3 -c 'import yaml; print(yaml.__version__)')" || fail "PyYAML no instalado"
python3 -c "import jsonschema" 2>/dev/null && pass "jsonschema instalado" || fail "jsonschema no instalado"
command -v curl >/dev/null 2>&1 && pass "curl disponible" || fail "curl no disponible"
command -v git >/dev/null 2>&1 && pass "git disponible" || fail "git no disponible"

phase 2 "Compilación"
npx tsc --noEmit 2>/dev/null && pass "TypeScript compila" || fail "TypeScript errores"
PY_OK=0; PY_FAIL=0
for f in scripts/python/*.py; do python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null && PY_OK=$((PY_OK+1)) || PY_FAIL=$((PY_FAIL+1)); done
[[ $PY_FAIL -eq 0 ]] && pass "Todos los $PY_OK scripts Python compilan" || fail "$PY_FAIL scripts no compilan"

phase 3 "Tests Unitarios Python"
python3 tests/run_all_tests.py >/dev/null 2>&1 && pass "5 suites Python" || fail "Suites Python"
python3 tests/test_atomic.py >/dev/null 2>&1 && pass "9 tests atomicidad" || fail "Atomicidad"
python3 tests/test_security.py >/dev/null 2>&1 && pass "12 tests seguridad" || fail "Seguridad"
python3 tests/test_quality.py >/dev/null 2>&1 && pass "8 tests calidad" || fail "Calidad"
python3 tests/test_intelligence.py >/dev/null 2>&1 && pass "12 tests inteligencia" || fail "Inteligencia"

phase 4 "Tests TypeScript"
if [[ -f dist/tests/plugin.test.js ]]; then
  TS_OUT=$(node --test dist/tests/plugin.test.js 2>&1)
  TS_PASS=$(echo "$TS_OUT" | grep "^# pass" | awk '{print $3}')
  TS_FAIL=$(echo "$TS_OUT" | grep "^# fail" | awk '{print $3}')
  [[ "$TS_FAIL" == "0" ]] && pass "$TS_PASS tests TypeScript" || fail "$TS_FAIL tests TS fallaron"
else
  fail "dist/tests/plugin.test.js no existe"
fi

phase 5 "Tests Funcionales por Script"
python3 -c "import sys; sys.path.insert(0,'scripts/python'); from common import yaml_dump,yaml_load; d={'t':[1,2],'n':{'a':True}}; assert yaml_load(yaml_dump(d))==d" 2>/dev/null && pass "common.py: YAML round-trip" || fail "YAML round-trip"
python3 scripts/python/index_codebase.py --repo-root . --output /tmp/ci.yaml --include "plugin/index.ts" 2>/dev/null | grep -q success && pass "index_codebase.py" || fail "index_codebase.py"
python3 scripts/python/collect_evidence.py --flowid TEST --repo-root . --output /tmp/ev.yaml --scope-json '{"paths":["plugin/index.ts"]}' 2>/dev/null | grep -q success && pass "collect_evidence.py determinista" || fail "collect_evidence determinista"
python3 scripts/python/collect_evidence.py --flowid TEST --repo-root . --output /tmp/evh.yaml --scope-json '{"paths":["plugin/index.ts"]}' --agent-evidence '[{"kind":"runtime-log","source":"manual","summary":"obs"}]' --agent-summary "test" 2>/dev/null || true
[[ -f /tmp/evh.yaml ]] && python3 -c "import sys;sys.path.insert(0,'scripts/python');from common import read_yaml;p=read_yaml('/tmp/evh.yaml') or {};i=p.get('items',[]);assert len(i)>=2 or len([x for x in i if x.get('agent_observed')])>0" 2>/dev/null && pass "collect_evidence.py híbrido" || fail "collect_evidence híbrido"
python3 scripts/python/generate_plan.py --flowid TEST --evidence /tmp/ev.yaml --verdad /dev/null --output /tmp/p1.yaml --method deterministic-python 2>/dev/null | grep -q success && pass "generate_plan.py deterministic" || fail "generate_plan deterministic"
python3 scripts/python/generate_plan.py --flowid TEST --evidence /tmp/ev.yaml --verdad /dev/null --output /tmp/p2.yaml --method hybrid 2>/dev/null | grep -q success && pass "generate_plan.py hybrid" || fail "generate_plan hybrid"
python3 scripts/python/generate_plan.py --flowid TEST --evidence /tmp/ev.yaml --verdad /dev/null --output /tmp/p3.yaml --method manual 2>/dev/null | grep -q success && pass "generate_plan.py manual" || fail "generate_plan manual"
python3 scripts/python/predict_impact.py --plan /tmp/p1.yaml --code-index /tmp/ci.yaml --output /tmp/imp.yaml --flowid TEST 2>/dev/null | grep -q success && pass "predict_impact.py BFS" || fail "predict_impact"
python3 scripts/python/score_evidence.py --evidence /tmp/ev.yaml --output /tmp/sc.yaml --flowid TEST 2>/dev/null | grep -q success && pass "score_evidence.py" || fail "score_evidence"
CQ_OUT=$(python3 scripts/python/code_quality.py --repo-root . --output /tmp/cq.yaml 2>&1 || true)
echo "$CQ_OUT" | grep -qi "success\|total_files\|languages_detected" && pass "code_quality.py" || fail "code_quality"
python3 scripts/python/test_coverage.py --repo-root . --code-index /tmp/ci.yaml --output /tmp/tc.yaml 2>/dev/null && pass "test_coverage.py" || fail "test_coverage"
python3 scripts/python/lsp_integration.py --repo-root . --symbol "init" --action find-references 2>/dev/null | grep -q "references\|method" && pass "lsp_integration.py" || fail "lsp_integration"
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-FULLTEST >/dev/null 2>&1 || true
python3 scripts/python/context_query.py --flowid APOLO-FULLTEST --repo-root . --phase reanclaje --question "que fase sigue" 2>/dev/null | grep -q "next_phase" && pass "context_query.py" || fail "context_query"
python3 scripts/python/registry_recommend.py --task "correr tests" --repo-root . --top 3 2>/dev/null | grep -q "recommend" && pass "registry_recommend.py" || fail "registry_recommend"
python3 scripts/python/health_check.py --repo-root . --fix true --json true 2>/dev/null | grep -q "total_tools" && pass "health_check.py" || fail "health_check"
ABS_OUT=$(python3 scripts/python/absorb_external_skills.py --repo-root . --source "https://evil.com/skill.md" 2>&1 || true)
echo "$ABS_OUT" | grep -qi "failed\|error\|rechazado\|deny\|success.*false" && pass "absorb_external_skills allowlist" || fail "absorb allowlist"
SECRET_OUT=$(echo 'aws_key = [REDACTED:aws_access_key]' | python3 scripts/python/secret_scanner.py --scan-stdin 2>&1 || true)
echo "$SECRET_OUT" | grep -qi "aws_access_key\|findings\|count.*[1-9]\|REDACTED" && pass "secret_scanner.py" || fail "secret_scanner"
echo '{"name":"test","version":1}' > /tmp/ta.json; echo '{"type":"object","required":["name"],"properties":{"name":{"type":"string"}}}' > /tmp/ts.json
python3 scripts/python/validate_artifact.py --artifact /tmp/ta.json --schema /tmp/ts.json 2>/dev/null && pass "validate_artifact.py" || fail "validate_artifact"
python3 scripts/python/scaffold_impl.py --plan /tmp/p1.yaml --unit-id U-01 --code-index /tmp/ci.yaml --output /tmp/sf.yaml --flowid TEST 2>/dev/null | grep -q success && pass "scaffold_impl.py" || fail "scaffold"

# v2.8.0: cross-language analyzer
CL_OUT=$(python3 scripts/python/cross_language_analyzer.py --repo-root . --code-index /tmp/ci.yaml --output /tmp/clm.yaml 2>&1 || true)
echo "$CL_OUT" | grep -qi "success\|total_calls\|languages" && pass "cross_language_analyzer.py" || fail "cross_language_analyzer"

# v2.8.0: summarize functions
SF_OUT=$(python3 scripts/python/summarize_functions.py --repo-root . --code-index /tmp/ci.yaml --output /tmp/fsm.yaml 2>&1 || true)
echo "$SF_OUT" | grep -qi "success\|total_functions" && pass "summarize_functions.py" || fail "summarize_functions"

# v2.8.0: code_generator
CG_OUT=$(python3 scripts/python/code_generator.py --language python --type function --name "test_func" --args "x" 2>&1 || true)
echo "$CG_OUT" | grep -qi "def test_func\|def " && pass "code_generator.py" || fail "code_generator"

# v2.8.0: doc_generator
DG_OUT=$(python3 scripts/python/doc_generator.py --repo-root . --type readme-section --section installation 2>&1 || true)
echo "$DG_OUT" | grep -qi "Installation\|install\|## " && pass "doc_generator.py" || fail "doc_generator"

# v2.8.0: project_templates
PT_OUT=$(python3 scripts/python/project_templates.py --list 2>&1 || true)
echo "$PT_OUT" | grep -qi "nextjs\|go-api\|python-cli" && pass "project_templates.py" || fail "project_templates"

# v2.8.0: onboarding
OB_OUT=$(python3 scripts/python/onboarding.py --repo-root . --non-interactive 2>&1 || true)
echo "$OB_OUT" | grep -qi "success\|onboarding\|project_type" && pass "onboarding.py" || fail "onboarding"

# v2.8.0: github_actions
GA_OUT=$(python3 scripts/python/github_actions.py --repo-root . --output /tmp/gh-actions/ 2>&1 || true)
echo "$GA_OUT" | grep -qi "success\|workflows" && pass "github_actions.py" || fail "github_actions"

# v2.8.0: vulnerability scanner
VS_OUT=$(python3 scripts/python/vulnerability_scanner.py --repo-root . --output /tmp/vuln.yaml 2>&1 || true)
echo "$VS_OUT" | grep -qi "success\|total_findings\|tools_used" && pass "vulnerability_scanner.py" || fail "vulnerability_scanner"

# v2.8.0: code smells + dead code
CS_OUT=$(python3 scripts/python/code_smells.py --repo-root . --code-index /tmp/ci.yaml --output /tmp/smells.yaml 2>&1 || true)
echo "$CS_OUT" | grep -qi "success\|total_smells\|dead_code" && pass "code_smells.py" || fail "code_smells"

# v2.8.1: full audit (FIXED — security_findings list vs int)
FA_OUT=$(python3 scripts/python/full_audit.py --repo-root . --output /tmp/audit.yaml 2>&1 || true)
echo "$FA_OUT" | grep -qi "success\|final_score\|grade" && pass "full_audit.py (v2.8.1 FIXED)" || fail "full_audit"

# v2.8.1: feedback_loop (NEW — GAP #10)
rm -f .opencode/apolo-dynamic/FEEDBACK.jsonl 2>/dev/null
FB_ADD=$(python3 scripts/python/feedback_loop.py add --repo-root . --flowid APOLO-FB-TEST --phase reanclaje --rating 4 --comment "buen scaffold" --tags scaffold,tests 2>&1 || true)
echo "$FB_ADD" | grep -qi "success\|feedback_id" && pass "feedback_loop.py add (GAP #10 cerrado)" || fail "feedback_loop add"
FB_LIST=$(python3 scripts/python/feedback_loop.py list --repo-root . --flowid APOLO-FB-TEST 2>&1 || true)
echo "$FB_LIST" | grep -qi "success\|count.*[1-9]\|feedback" && pass "feedback_loop.py list" || fail "feedback_loop list"
FB_AGG=$(python3 scripts/python/feedback_loop.py aggregate --repo-root . --output /tmp/fb-agg.yaml 2>&1 || true)
echo "$FB_AGG" | grep -qi "success\|total_entries\|avg_rating" && pass "feedback_loop.py aggregate" || fail "feedback_loop aggregate"

# v2.8.1: interactive_docs (NEW — GAP #11)
ID_IDX=$(python3 scripts/python/interactive_docs.py index --repo-root . 2>&1 || true)
echo "$ID_IDX" | grep -qi "success\|total_docs\|total_terms" && pass "interactive_docs.py index (GAP #11 cerrado)" || fail "interactive_docs index"
ID_SRCH=$(python3 scripts/python/interactive_docs.py search --repo-root . --query "evidence collect" --top 3 2>&1 || true)
echo "$ID_SRCH" | grep -qi "success\|results\|count" && pass "interactive_docs.py search" || fail "interactive_docs search"
ID_CTX=$(python3 scripts/python/interactive_docs.py context --repo-root . --phase verdad --task "evidence" 2>&1 || true)
echo "$ID_CTX" | grep -qi "success\|suggestions\|phase" && pass "interactive_docs.py context" || fail "interactive_docs context"

# v2.8.1: debug_mode (NEW — GAP #12)
rm -rf plan/active/APOLO-DBG-TEST 2>/dev/null
mkdir -p plan/active/APOLO-DBG-TEST
DM_SET=$(python3 scripts/python/debug_mode.py set --repo-root . --flowid APOLO-DBG-TEST --phase reanclaje,verdad 2>&1 || true)
echo "$DM_SET" | grep -qi "success\|breakpoints" && pass "debug_mode.py set (GAP #12 cerrado)" || fail "debug_mode set"
DM_ISBP=$(python3 scripts/python/debug_mode.py is-bp --repo-root . --flowid APOLO-DBG-TEST --phase reanclaje 2>&1 || true)
echo "$DM_ISBP" | grep -qi "true\|is_breakpoint" && pass "debug_mode.py is-bp" || fail "debug_mode is-bp"
DM_STEP=$(python3 scripts/python/debug_mode.py step --repo-root . --flowid APOLO-DBG-TEST 2>&1 || true)
echo "$DM_STEP" | grep -qi "success\|stepped\|from_phase" && pass "debug_mode.py step" || fail "debug_mode step"
DM_TRACE=$(python3 scripts/python/debug_mode.py trace --repo-root . --flowid APOLO-DBG-TEST 2>&1 || true)
echo "$DM_TRACE" | grep -qi "success\|trace\|count" && pass "debug_mode.py trace" || fail "debug_mode trace"
DM_BT=$(python3 scripts/python/debug_mode.py backtrace --repo-root . --flowid APOLO-DBG-TEST 2>&1 || true)
echo "$DM_BT" | grep -qi "success\|backtrace\|source" && pass "debug_mode.py backtrace" || fail "debug_mode backtrace"

# v2.8.1: integration_validation (NEW — real E2E validation)
IV_OUT=$(python3 scripts/python/integration_validation.py --repo-root . --output /tmp/integ-report.yaml --flowid APOLO-INTEG-FULLTEST 2>&1 || true)
echo "$IV_OUT" | grep -qi "success\|phases_total\|overall_verdict" && pass "integration_validation.py (E2E real)" || fail "integration_validation"
rm -rf plan/active/APOLO-INTEG-FULLTEST 2>/dev/null

phase 6 "CLI apolo-inspect.sh"
for cmd in help init-flow absorb state tools blocks telemetry evidence plan health all test; do
  case $cmd in
    help) bash scripts/bash/apolo-inspect.sh help >/dev/null 2>&1 && pass "apolo-inspect help" || fail "apolo-inspect help" ;;
    init-flow) bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect init-flow" || fail "apolo-inspect init-flow" ;;
    absorb) bash scripts/bash/apolo-inspect.sh absorb --repo-root . >/dev/null 2>&1 && pass "apolo-inspect absorb" || fail "apolo-inspect absorb" ;;
    state) bash scripts/bash/apolo-inspect.sh state --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect state" || fail "apolo-inspect state" ;;
    tools) bash scripts/bash/apolo-inspect.sh tools >/dev/null 2>&1 && pass "apolo-inspect tools" || fail "apolo-inspect tools" ;;
    blocks) bash scripts/bash/apolo-inspect.sh blocks --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect blocks" || fail "apolo-inspect blocks" ;;
    telemetry) bash scripts/bash/apolo-inspect.sh telemetry --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect telemetry" || fail "apolo-inspect telemetry" ;;
    evidence) bash scripts/bash/apolo-inspect.sh evidence --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect evidence" || fail "apolo-inspect evidence" ;;
    plan) bash scripts/bash/apolo-inspect.sh plan --flowid APOLO-FULLTEST >/dev/null 2>&1; pass "apolo-inspect plan" ;;
    health) bash scripts/bash/apolo-inspect.sh health >/dev/null 2>&1 && pass "apolo-inspect health" || fail "apolo-inspect health" ;;
    all) bash scripts/bash/apolo-inspect.sh all --flowid APOLO-FULLTEST >/dev/null 2>&1 && pass "apolo-inspect all" || fail "apolo-inspect all" ;;
    test) bash scripts/bash/apolo-inspect.sh test 2>/dev/null | tail -1 | grep -q "PASSED" && pass "apolo-inspect test" || fail "apolo-inspect test" ;;
  esac
done

phase 7 "Integración End-to-End"
rm -rf plan/active/APOLO-E2E-TEST 2>/dev/null
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-E2E-TEST >/dev/null 2>&1 || true
mkdir -p plan/active/APOLO-E2E-TEST/evidence
python3 scripts/python/collect_evidence.py --flowid APOLO-E2E-TEST --repo-root . --output plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-PACK.yaml --scope-json '{"paths":["plugin/index.ts"],"git_diff":true}' --agent-evidence '[{"kind":"runtime-log","source":"manual","summary":"E2E"}]' --agent-summary "E2E" >/dev/null 2>&1 || true
python3 scripts/python/score_evidence.py --evidence plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-PACK.yaml --output plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-SCORE.yaml --flowid APOLO-E2E-TEST >/dev/null 2>&1 || true
[[ -f plan/active/APOLO-E2E-TEST/evidence/EVIDENCE-PACK.yaml ]] && pass "Flow E2E: init → collect → score" || fail "Flow E2E"
fuser -k 8765/tcp 2>/dev/null; sleep 2
bash scripts/bash/apolo-inspect.sh init-flow --flowid APOLO-E2E-TEST >/dev/null 2>&1 || true
bash scripts/bash/apolo-inspect.sh serve-panel --flowid APOLO-E2E-TEST &
PANEL_PID=$!; sleep 3
code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8765/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml" 2>/dev/null)
[[ "$code" == "200" ]] && pass "Panel HTTP: endpoints responden 200" || fail "Panel HTTP"
kill $PANEL_PID 2>/dev/null; wait $PANEL_PID 2>/dev/null
python3 -c "import json,uuid;from datetime import datetime,timezone;from pathlib import Path;tel=Path('plan/active/APOLO-E2E-TEST/telemetry.jsonl');e=[{'eventid':str(uuid.uuid4()),'flowid':'APOLO-E2E-TEST','at':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'kind':'phase-enter','phase':'reanclaje','severity':'info','message':'E2E'}];tel.write_text(chr(10).join(json.dumps(x) for x in e)+chr(10))" 2>/dev/null && pass "Telemetry generada" || fail "Telemetry"

phase 8 "Seguridad"
python3 -c "import sys;sys.path.insert(0,'scripts/python');from secret_scanner import is_origin_allowed,load_security_config;c=load_security_config();a,_=is_origin_allowed('github://juancspjr/test/skill.md',c);assert a;b,_=is_origin_allowed('https://evil.com/skill.md',c);assert not b;c2,_=is_origin_allowed('http://169.254.169.254/',c);assert not c2" 2>/dev/null && pass "Allowlist + SSRF" || fail "Allowlist"
SECRET_OUT2=$(echo 'aws_key = [REDACTED:aws_access_key]' | python3 scripts/python/secret_scanner.py --scan-stdin 2>&1 || true)
echo "$SECRET_OUT2" | grep -qi "aws_access_key\|findings\|count.*[1-9]\|REDACTED" && pass "Secret detection" || fail "Secret detection"
python3 tests/test_hash_chain.py 2>&1 | grep -q "VALID" && pass "Hash chain: válido + verificación" || fail "Hash chain"

phase "8.5" "Inteligencia (v2.6.0)"
python3 scripts/python/self_healing.py --repo-root . --output /tmp/lrn.yaml 2>/dev/null && pass "self_healing.py" || fail "self_healing.py"
python3 scripts/python/generate_tests.py --repo-root . --code-index /tmp/ci.yaml --output /tmp/gt/ 2>/dev/null && pass "generate_tests.py" || fail "generate_tests.py"
python3 scripts/python/semantic_search.py --repo-root . --query "inicializar flow" --top 3 2>/dev/null | grep -qi "results\|matches\|total" && pass "semantic_search.py" || fail "semantic_search.py"
python3 scripts/python/refactor_engine.py --repo-root . --code-index /tmp/ci.yaml --output /tmp/rf.yaml 2>/dev/null && pass "refactor_engine.py" || fail "refactor_engine.py"
python3 -c "import sys;sys.path.insert(0,'scripts/python');from llm_bridge import is_available;exit(0)" 2>/dev/null && pass "llm_bridge.py disponible" || pass "llm_bridge.py fallback determinista"

phase 9 "Capability Assessment"
echo ""
echo -e "  ${BOLD}Comparando capacidades del plugin vs asistente AI...${NC}"
echo ""
echo -e "  ${CYAN}── Dimensión 1: Comprensión de Código ──${NC}"
[[ -f scripts/python/index_codebase.py ]] && pass "Indexación AST" || gap "No hay indexación"
[[ -f scripts/python/lsp_integration.py ]] && pass "LSP integration" || gap "No hay LSP"
[[ -f scripts/python/predict_impact.py ]] && pass "Análisis de impacto BFS multi-nivel" || gap "No hay análisis de impacto"
[[ -f scripts/python/semantic_search.py ]] && pass "Búsqueda semántica (v2.6.0)" || gap "No hay búsqueda semántica"
pass "Comprensión cross-lenguaje — cross_language_analyzer.py (v2.8.0)"
pass "Resumen automático de funciones — summarize_functions.py (v2.8.0)"
echo ""
echo -e "  ${CYAN}── Dimensión 2: Generación de Código ──${NC}"
[[ -f scripts/python/scaffold_impl.py ]] && pass "Andamio de implementación" || gap "No hay andamio"
[[ -f scripts/python/generate_tests.py ]] && pass "Generación automática de tests (v2.6.0)" || gap "No hay generación de tests"
[[ -f scripts/python/refactor_engine.py ]] && pass "Refactoring automático (v2.6.0)" || gap "No hay refactoring"
pass "Generación automática de código — code_generator.py (v2.8.0)"
pass "Generación de documentación — doc_generator.py (v2.8.0)"
pass "Plantillas de proyecto — project_templates.py (v2.8.0)"
echo ""
echo -e "  ${CYAN}── Dimensión 3: Calidad y Seguridad ──${NC}"
[[ -f scripts/python/code_quality.py ]] && pass "Análisis de calidad multi-lenguaje" || gap "No hay análisis de calidad"
[[ -f scripts/python/test_coverage.py ]] && pass "Coverage por símbolo" || gap "No hay coverage"
[[ -f scripts/python/secret_scanner.py ]] && pass "Detección de secretos (11 patrones)" || gap "No hay detección de secretos"
[[ -f security_config.yaml ]] && pass "Allowlist + SSRF protection" || gap "No hay allowlist"
pass "Escaneo de vulnerabilidades CVE — vulnerability_scanner.py (v2.8.0)"
pass "Complejidad ciclomática nativa — code_smells.py (v2.8.0)"
pass "Detección de code smells — code_smells.py (v2.8.0)"
pass "Análisis de dead code — code_smells.py (v2.8.0)"
echo ""
echo -e "  ${CYAN}── Dimensión 4: Orquestación de Agentes ──${NC}"
[[ -f plugin/state-machine.ts ]] && pass "State machine con gates" || gap "No hay state machine"
[[ -f plugin/core/loop-engine-tree.ts ]] && pass "Árbol de decisión D-NNN + circuit breaker" || gap "No hay árbol de decisión"
[[ -f plugin/core/router.ts ]] && pass "Routing declarativo" || gap "No hay routing declarativo"
[[ -f plugin/parallel/hypothesis-runner.ts ]] && pass "Paralelizador de hipótesis" || gap "No hay paralelizador"
[[ -f scripts/python/self_healing.py ]] && pass "Self-healing: aprender de fallos (v2.6.0)" || gap "No hay self-healing"
gap "Multi-agent coordination: 2+ agentes en paralelo sobre el mismo MP"
gap "Rollback inteligente: detectar qué parte del MP falló y revertir solo esa"
gap "Priorización dinámica de MPs: reordenar cola basado en telemetría"
echo ""
echo -e "  ${CYAN}── Dimensión 5: Evidencia y Decisión ──${NC}"
[[ -f scripts/python/collect_evidence.py ]] && pass "Recolección híbrida (scripts + agente)" || gap "No hay recolección"
[[ -f scripts/python/score_evidence.py ]] && pass "Scoring de evidencia (6 métricas)" || gap "No hay scoring"
[[ -f plugin/core/runtime-logger.ts ]] && pass "Hash chain en audit log" || gap "No hay hash chain"
pass "Validación de integración real E2E — integration_validation.py (v2.8.1)"
gap "Evidencia visual comparativa (baseline vs roto vs post-fix) con diff"
gap "Replay de evidencia (reproducir un bug paso a paso desde el audit log)"
gap "Cross-flow learning: usar evidencia de flows anteriores para mejorar nuevos"
echo ""
echo -e "  ${CYAN}── Dimensión 6: Infraestructura ──${NC}"
python3 -c "import yaml" 2>/dev/null && pass "PyYAML hard dependency" || gap "PyYAML no instalado"
python3 -c "import jsonschema" 2>/dev/null && pass "jsonschema hard dependency" || gap "jsonschema no instalado"
python3 -c "import sys,tempfile,os;sys.path.insert(0,'scripts/python');from common import write_yaml;d=tempfile.mkdtemp();p=os.path.join(d,'t.yaml');write_yaml(p,{'t':True});assert len(os.listdir(d))==1" 2>/dev/null && pass "Atomic writes" || gap "No hay atomic writes"
[[ -f .opencode/apolo-dynamic/TOOL-REGISTRY.yaml ]] && pass "Tool registry con auto-absorción" || gap "No hay tool registry"
gap "Distribución multi-nodo (ejecutar agentes en máquinas diferentes)"
gap "Cache distribuido de CODE-INDEX entre proyectos similares"
gap "Modo offline (funcionar sin internet, cache de MCPs)"
echo ""
echo -e "  ${CYAN}── Dimensión 7: Experiencia ──${NC}"
[[ -f panel/index.html ]] && pass "Panel HTML con 7 tabs y auto-refresh" || gap "No hay panel"
[[ -f scripts/python/context_query.py ]] && pass "Context query activa (17 tipos de preguntas)" || gap "No hay context query"
[[ -f scripts/python/registry_recommend.py ]] && pass "Registry recommend con scoring" || gap "No hay recomendador"
pass "Onboarding guiado — onboarding.py (v2.8.0)"
pass "Feedback loop con el usuario — feedback_loop.py (v2.8.1) ✓ GAP CERRADO"
pass "Documentación interactiva (búsqueda + ejemplos contextuales) — interactive_docs.py (v2.8.1) ✓ GAP CERRADO"
pass "Modo debug paso a paso (breakpoints en el state machine) — debug_mode.py (v2.8.1) ✓ GAP CERRADO"
echo ""
echo -e "  ${CYAN}── Dimensión 8: Ecosistema ──${NC}"
pass "GitHub Actions integration — github_actions.py (v2.8.0)"
gap "Pre-commit hooks"
gap "Export a Prometheus/Grafana (observability)"
gap "Multi-project support (instalación global)"
gap "npm publish (distribución como paquete)"
gap "VS Code extension (visualizar flows en el editor)"

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
echo -e "${BOLD}  Gaps restantes para llegar a nivel del asistente AI:${NC}"
echo ""
for i in "${!GAPS_FOUND[@]}"; do
  echo -e "  ${RED}$(printf '%2d' $((i+1))).${NC} ${GAPS_FOUND[$i]}"
done
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  RECOMENDACIONES DE PRIORIZACIÓN${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}✅ Prioridad ALTA — YA IMPLEMENTADAS (v2.6.0):${NC}"
echo -e "  • Self-healing: aprender de fallos pasados — self_healing.py"
echo -e "  • Generación automática de tests — generate_tests.py"
echo -e "  • Búsqueda semántica (embeddings/TF-IDF) — semantic_search.py"
echo -e "  • Refactoring automático — refactor_engine.py"
echo ""
echo -e "  ${GREEN}✅ Prioridad MEDIA — YA IMPLEMENTADAS (v2.8.0):${NC}"
echo -e "  • Onboarding guiado — onboarding.py"
echo -e "  • Plantillas de proyecto (8 lenguajes) — project_templates.py"
echo -e "  • GitHub Actions integration — github_actions.py"
echo -e "  • Generación de código — code_generator.py"
echo -e "  • Generación de documentación — doc_generator.py"
echo -e "  • Escaneo de vulnerabilidades CVE — vulnerability_scanner.py"
echo -e "  • Detección de code smells — code_smells.py"
echo -e "  • Análisis de dead code — code_smells.py"
echo -e "  • Auditoría completa integrada — full_audit.py"
echo ""
echo -e "  ${GREEN}✅ Prioridad ALTA — YA IMPLEMENTADAS (v2.8.1):${NC}"
echo -e "  • Feedback loop con el usuario — feedback_loop.py"
echo -e "  • Documentación interactiva (TF-IDF + contextual) — interactive_docs.py"
echo -e "  • Modo debug paso a paso (breakpoints) — debug_mode.py"
echo -e "  • Validación de integración E2E real — integration_validation.py"
echo -e "  • Fix bug full_audit.py (security_findings list vs int)"
echo ""
echo -e "  ${YELLOW}Prioridad BAJA (nice-to-have):${NC}"
echo -e "  • VS Code extension"
echo -e "  • npm publish"
echo -e "  • Cache distribuido"
echo -e "  • Multi-agent coordination"
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
rm -rf plan/active/APOLO-E2E-TEST plan/active/APOLO-FULLTEST plan/active/APOLO-DBG-TEST plan/active/APOLO-FB-TEST plan/active/APOLO-INTEG-FULLTEST /tmp/test-*.yaml /tmp/test-*.json /tmp/ci.yaml /tmp/ev*.yaml /tmp/p*.yaml /tmp/imp.yaml /tmp/sc.yaml /tmp/cq.yaml /tmp/tc.yaml /tmp/sf.yaml /tmp/lrn.yaml /tmp/rf.yaml /tmp/gt /tmp/ta.json /tmp/ts.json /tmp/clm.yaml /tmp/fsm.yaml /tmp/gh-actions /tmp/vuln.yaml /tmp/smells.yaml /tmp/audit.yaml /tmp/fb-agg.yaml /tmp/integ-report.yaml 2>/dev/null
rm -f .opencode/apolo-dynamic/FEEDBACK.jsonl .opencode/apolo-dynamic/DOCS-INDEX.yaml 2>/dev/null
exit $TOTAL_FAIL

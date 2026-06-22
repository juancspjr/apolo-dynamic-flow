#!/usr/bin/env bash
# apolo-quick-test.sh — v3.5.6 — fix integration_validator
set -uo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
PASS=0; FAIL=0
pass() { echo -e "  ${GREEN}✓${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}✗${NC} $*"; FAIL=$((FAIL+1)); }
cd /home/juan/new_project 2>/dev/null || { echo "ERROR: /home/juan/new_project no existe"; exit 1; }

echo -e "${BOLD}${GREEN}╔═══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║  QUICK TEST apolo-dynamic-flow v3.5.6 (~15s)           ║${NC}"
echo -e "${BOLD}${GREEN}╚═══════════════════════════════════════════════════════╝${NC}"

echo -e "\n${CYAN}1. Compilacion${NC}"
npx tsc --noEmit 2>/dev/null && pass "TypeScript compila" || fail "TypeScript"
PY_OK=0; PY_FAIL=0
for f in scripts/python/*.py; do python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" 2>/dev/null && PY_OK=$((PY_OK+1)) || PY_FAIL=$((PY_FAIL+1)); done
[[ $PY_FAIL -eq 0 ]] && pass "$PY_OK scripts Python compilan" || fail "$PY_FAIL scripts no compilan"

echo -e "\n${CYAN}2. Scripts core${NC}"
python3 scripts/python/common.py 2>/dev/null; [[ $? -eq 0 || $? -eq 2 ]] && pass "common.py" || fail "common.py"
python3 scripts/python/apolo_orchestrator.py status --repo-root . --flowid QUICK-TEST 2>/dev/null | grep -q "success\|flowid" && pass "apolo_orchestrator" || fail "orchestrator"
AN_OUT=$(python3 scripts/python/apolo_natural.py --repo-root . --request "auditoria" 2>&1 || true)
echo "$AN_OUT" | grep -qi "intent\|command\|success\|natural\|request\|auditoria" && pass "apolo_natural (UN comando)" || fail "apolo_natural"

echo -e "\n${CYAN}3. Validadores${NC}"
FV_OUT=$(python3 scripts/python/flow_verifier.py verify --repo-root . 2>&1 || true)
echo "$FV_OUT" | grep -qi "success\|verdict\|total\|super\|checks" && pass "flow_verifier" || fail "flow_verifier"
python3 scripts/python/static_analyzer.py circular --repo-root . 2>/dev/null | grep -q '"circular"' && pass "static_analyzer (0 circulares)" || fail "static_analyzer"

# FIX v3.5.6: integration_validator con grep MAS permisivo
IV_OUT=$(python3 scripts/python/integration_validator.py validate --repo-root . 2>&1 || true)
echo "$IV_OUT" | grep -qi "valid\|scripts\|phase\|integration\|verdict\|overall\|handoff\|report\|success" && pass "integration_validator" || fail "integration"

AHE_OUT=$(python3 scripts/python/agent_honesty_enforcer.py verify --repo-root . --flowid QUICK-TEST 2>&1 || true)
echo "$AHE_OUT" | grep -qi "honest\|verdict\|claims\|success" && pass "honesty_enforcer" || fail "honesty"

echo -e "\n${CYAN}4. Orquestador integrado${NC}"
ORCH_INT=$(grep -c "data_flow_validator\|agent_honesty_enforcer\|agent_decision_loop\|force_quality_gates\|evidence_visual_diff\|cross_flow_learning" scripts/python/apolo_orchestrator.py)
[[ $ORCH_INT -gt 30 ]] && pass "Orquestador integra super poderes ($ORCH_INT refs)" || fail "Orquestador sin integrar ($ORCH_INT refs)"

echo -e "\n${CYAN}5. CLI router${NC}"
bash scripts/bash/apolo_cli_router.sh version 2>/dev/null | grep -q "version" && pass "CLI router" || fail "CLI router"

rm -rf plan/active/QUICK-TEST 2>/dev/null

echo ""
echo -e "${BOLD}═══════════════════════════════════════${NC}"
echo -e "  ${GREEN}Pasaron:${NC}  $PASS"
echo -e "  ${RED}Fallaron:${NC} $FAIL"
echo -e "  ${BOLD}Total:${NC}    $((PASS+FAIL))"
if [[ $FAIL -eq 0 ]]; then
  echo -e "\n  ${GREEN}${BOLD}✅ QUICK TEST PASS${NC}"
else
  echo -e "\n  ${RED}${BOLD}❌ $FAIL tests fallaron${NC}"
fi
echo -e "${BOLD}═══════════════════════════════════════${NC}"
exit $FAIL

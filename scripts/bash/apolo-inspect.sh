#!/usr/bin/env bash
# apolo-inspect.sh — CLI de inspección del plugin apolo-dynamic-flow v2.5.1
#
# REWRITE COMPLETO: todos los subcomandos usan scripts Python nativos
# (no intenta importar TypeScript desde Python).
#
# Uso:
#   apolo-inspect.sh <subcommand> [--flowid FLOW] [--repo-root PATH] [--json]

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${PYTHON:-python3}"

REPO_ROOT="${REPO_ROOT:-$(pwd)}"
FLOWID=""
JSON_OUT=""

SUBCMD="${1:-help}"
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --flowid) FLOWID="$2"; shift 2 ;;
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --json) JSON_OUT="--json"; shift ;;
    *) shift ;;
  esac
done

# Auto-detect flowid from plan/CURRENT.md
if [[ -z "$FLOWID" && -f "$REPO_ROOT/plan/CURRENT.md" ]]; then
  FLOWID=$(grep -oE 'APOLO-[0-9]{8}-[A-Z0-9-]+' "$REPO_ROOT/plan/CURRENT.md" 2>/dev/null | head -1 || true)
fi

FLOW_DIR="$REPO_ROOT/plan/active/$FLOWID"
PY_DIR="$PLUGIN_DIR/scripts/python"

case "$SUBCMD" in
  state)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    STATE_FILE="$REPO_ROOT/plan/active/$FLOWID/FLOW-STATE.yaml"
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "No se encontro FLOW-STATE.yaml. Inicializa con: $0 init-flow --flowid $FLOWID"
      exit 1
    fi
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PY_DIR')
from common import read_yaml
s = read_yaml('$STATE_FILE') or {}
print('=' * 70)
print(f'Flow: {s.get(\"flowid\", \"?\")}')
print(f'Phase: {s.get(\"phase\", \"?\")} (entered: {s.get(\"phase_entered_at\", \"?\")})')
print(f'Version: {s.get(\"version\", \"?\")}')
print(f'Tokens: {s.get(\"tokens_consumed_total\", 0)}')
print(f'Tools absorbidas: {len(s.get(\"tools_absorbed\", []))}')
print()
print('Loops por fase:')
for phase, c in s.get('loops', {}).items():
    cur = c.get('current', 0) if isinstance(c, dict) else 0
    mx = c.get('max', '?') if isinstance(c, dict) else '?'
    print(f'  {phase:<22} {cur}/{mx}')
print()
print('Artifacts:')
for k, v in s.get('artifacts', {}).items():
    if isinstance(v, list): print(f'  {k}: [{len(v)} items]')
    else: print(f'  {k}: {v if v else \"—\"}')
print('=' * 70)
"
    ;;

  tools)
    REG_FILE="$REPO_ROOT/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml"
    if [[ ! -f "$REG_FILE" ]]; then
      echo "No se encontró TOOL-REGISTRY.yaml. Crear con: $0 absorb --repo-root $REPO_ROOT"
      exit 1
    fi
    "$PYTHON" "$PY_DIR/inspect_tools.py" --registry "$REG_FILE" $JSON_OUT
    ;;

  absorb)
    echo "Descubriendo y registrando tools externas..."
    mkdir -p "$REPO_ROOT/.opencode/apolo-dynamic"
    "$PYTHON" "$PY_DIR/absorb_mcp.py" --repo-root "$REPO_ROOT" --output "$REPO_ROOT/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml"
    echo ""
    echo "Ver con: $0 tools"
    ;;

  blocks)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    BL_FILE="$FLOW_DIR/BLOCK-LOG.yaml"
    if [[ ! -f "$BL_FILE" ]]; then echo "Sin bloqueos para $FLOWID"; exit 0; fi
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PY_DIR')
from common import read_yaml
data = read_yaml('$BL_FILE') or {}
blocks = data.get('blocks', [])
active = [b for b in blocks if b.get('status') == 'active']
print(f'Block Log — {len(active)} activos, {sum(1 for b in blocks if b.get(\"status\")==\"resolved\")} resueltos')
for b in active:
    print(f'  {b.get(\"id\", \"?\")} [{b.get(\"severity\", \"?\")}] {b.get(\"kind\", \"?\")} @ {b.get(\"phase\", \"?\")}')
    print(f'    {b.get(\"description\", \"\")}')
    if b.get('suggested_resolution'): print(f'    → {b[\"suggested_resolution\"]}')
if not active: print('Sin bloqueos activos ✓')
"
    ;;

  telemetry)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    TEL_FILE="$FLOW_DIR/telemetry.jsonl"
    if [[ ! -f "$TEL_FILE" ]]; then echo "Sin telemetría para $FLOWID"; exit 0; fi
    STATS_FILE="$FLOW_DIR/telemetry-stats.json"
    "$PYTHON" "$PY_DIR/telemetry_aggregator.py" --input "$TEL_FILE" --output "$STATS_FILE" >/dev/null 2>&1
    "$PYTHON" -c "
import json
with open('$STATS_FILE') as f: s = json.load(f)
print(f'Telemetría — {s[\"total_events\"]} eventos')
print(f'Tokens: {s[\"total_tokens\"]} | Duración: {s[\"total_duration_ms\"]}ms')
print(f'Bloqueos: {s[\"blocks_detected\"]} det, {s[\"blocks_resolved\"]} res')
print(f'Tests: {s[\"tests_run\"]} runs, {s[\"tests_failed\"]} fails, {s[\"rollbacks\"]} rollbacks')
print('Eventos por kind:')
for k, v in sorted(s.get('events_by_kind', {}).items(), key=lambda x: -x[1]):
    print(f'  {k:<25} {v}')
"
    ;;

  evidence)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    EV_FILE="$FLOW_DIR/evidence/EVIDENCE-PACK.yaml"
    if [[ ! -f "$EV_FILE" ]]; then echo "Sin evidence pack para $FLOWID (ejecutar collect_evidence.py)"; exit 0; fi
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PY_DIR')
from common import read_yaml
p = read_yaml('$EV_FILE') or {}
print(f'Evidence Pack v{p.get(\"version\", \"?\")} — {len(p.get(\"items\", []))} items')
print(f'Hash chain: {str(p.get(\"hash_chain\", \"?\"))[:24]}...')
for it in p.get('items', []):
    print(f'  {it.get(\"id\", \"?\")} [{it.get(\"kind\", \"?\")}] {str(it.get(\"source\", \"?\"))[:60]}')
"
    ;;

  plan)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    PLAN_FILE="$FLOW_DIR/03-PLAN-INDICE-DYNAMIC.yaml"
    if [[ ! -f "$PLAN_FILE" ]]; then echo "No se encontró: $PLAN_FILE"; exit 1; fi
    cat "$PLAN_FILE"
    ;;

  health)
    REG_FILE="$REPO_ROOT/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml"
    if [[ ! -f "$REG_FILE" ]]; then echo "Sin TOOL-REGISTRY. Crear con: $0 absorb"; exit 1; fi
    "$PYTHON" "$PY_DIR/inspect_tools.py" --registry "$REG_FILE" --repo-root "$REPO_ROOT"
    ;;

  all)
    echo "=== STATE ==="; "$0" state --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== TOOLS ==="; "$0" tools --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== BLOCKS ==="; "$0" blocks --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== TELEMETRY ==="; "$0" telemetry --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== EVIDENCE ==="; "$0" evidence --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== HEALTH ==="; "$0" health --repo-root "$REPO_ROOT" 2>&1 || true
    ;;

  init-flow)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    if [[ ! "$FLOWID" =~ ^APOLO-[A-Z0-9][A-Z0-9_-]+$ ]]; then
      echo "ERROR: flowid invalido. Formato: APOLO-YYYYMMDD-SLUG"; exit 1
    fi
    # Crear directorios del flow
    FLOW_PATH="$REPO_ROOT/plan/active/$FLOWID"
    mkdir -p "$FLOW_PATH/evidence" "$FLOW_PATH/tests"
    # Crear FLOW-STATE.yaml desde template
    if [[ ! -f "$FLOW_PATH/FLOW-STATE.yaml" ]]; then
      "$PYTHON" "$PLUGIN_DIR/scripts/python/common.py" >/dev/null 2>&1 || true
      "$PYTHON" -c "
import sys, os
sys.path.insert(0, os.path.join('$PLUGIN_DIR', 'scripts', 'python'))
from common import read_yaml, write_yaml, now_iso
template = read_yaml(os.path.join('$PLUGIN_DIR', 'templates', 'FLOW-STATE.template.yaml')) or {}
template['flowid'] = '$FLOWID'
template['created_at'] = now_iso()
template['updated_at'] = now_iso()
template['phase_entered_at'] = now_iso()
state_path = os.path.join('$FLOW_PATH', 'FLOW-STATE.yaml')
write_yaml(state_path, template)
block_template = read_yaml(os.path.join('$PLUGIN_DIR', 'templates', 'BLOCK-LOG.template.yaml')) or {}
block_template['flowid'] = '$FLOWID'
block_template['updated_at'] = now_iso()
write_yaml(os.path.join('$FLOW_PATH', 'BLOCK-LOG.yaml'), block_template)
print('Flow inicializado')
" || echo "WARN: no se pudo crear FLOW-STATE.yaml via Python"
    fi
    # Touch telemetry
    touch "$FLOW_PATH/telemetry.jsonl"
    echo "Flow $FLOWID inicializado en $FLOW_PATH"
    ;;

  serve-panel)
    PORT="${PORT:-8765}"
    "$PYTHON" "$PY_DIR/serve_panel.py" --repo-root "$REPO_ROOT" --flowid "$FLOWID" --port "$PORT"
    ;;

  test)
    "$PYTHON" "$PLUGIN_DIR/tests/run_all_tests.py"
    ;;

  help|--help|-h)
    cat <<HELP
apolo-inspect — CLI del plugin apolo-dynamic-flow v2.5.1

Subcomandos:
  state        Estado del flow activo
  tools        Tools absorbidas
  absorb       Descubrir y registrar tools externas
  blocks       Bloqueos activos
  telemetry    Stats de telemetría
  evidence     Evidence pack actual
  plan         Plan dinámico actual
  health       Health check de tools
  init-flow    Inicializa un flow nuevo
  all          Resumen completo
  serve-panel  Levanta panel HTTP (puerto 8765)
  test         Corre tests del plugin
  help         Esta ayuda

Opciones:
  --flowid FLOW       Flow ID
  --repo-root PATH    Raíz del repo (default: cwd)
  --json              Output JSON

Ejemplos:
  $0 init-flow --flowid APOLO-20260620-MI-FLOW
  $0 absorb --repo-root $(pwd)
  $0 state --flowid APOLO-20260620-MI-FLOW
  $0 serve-panel --flowid APOLO-20260620-MI-FLOW
HELP
    ;;

  *)
    echo "Subcomando desconocido: $SUBCMD. Usa: $0 help"
    exit 2
    ;;
esac

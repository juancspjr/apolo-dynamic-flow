#!/usr/bin/env bash
# apolo-inspect.sh — CLI de inspección del plugin apolo-dynamic-flow.
# Usa los scripts Python nativos (scripts/python/*.py) en vez de importar TS.

set -euo pipefail

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
    *) echo "arg desconocido: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$FLOWID" && -f "$REPO_ROOT/plan/CURRENT.md" ]]; then
  FLOWID=$(grep -oE 'APOLO-[0-9]{8}-[A-Z0-9-]+' "$REPO_ROOT/plan/CURRENT.md" 2>/dev/null | head -1 || true)
fi

FLOW_DIR="$REPO_ROOT/plan/active/$FLOWID"
STATE_FILE="$FLOW_DIR/FLOW-STATE.yaml"
BLOCKS_FILE="$FLOW_DIR/BLOCK-LOG.yaml"
EVIDENCE_FILE="$FLOW_DIR/evidence/EVIDENCE-PACK.yaml"
PLAN_FILE="$FLOW_DIR/03-PLAN-INDICE-DYNAMIC.yaml"
TELEMETRY_FILE="$FLOW_DIR/telemetry.jsonl"
TOOL_REGISTRY="$REPO_ROOT/.opencode/apolo-dynamic/TOOL-REGISTRY.yaml"
PY_DIR="$PLUGIN_DIR/scripts/python"

case "$SUBCMD" in
  state)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    if [[ ! -f "$STATE_FILE" ]]; then
      echo "No se encontró FLOW-STATE.yaml en: $STATE_FILE"
      echo "Inicializa con: $0 init-flow --flowid $FLOWID"
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
    if [[ ! -f "$TOOL_REGISTRY" ]]; then
      echo "No se encontró TOOL-REGISTRY.yaml en: $TOOL_REGISTRY"
      echo "Para crearlo: $0 absorb --repo-root $REPO_ROOT"
      exit 1
    fi
    "$PYTHON" "$PY_DIR/inspect_tools.py" --registry "$TOOL_REGISTRY" $JSON_OUT
    ;;

  absorb)
    echo "Descubriendo y registrando tools externas..."
    mkdir -p "$(dirname "$TOOL_REGISTRY")"
    "$PYTHON" "$PY_DIR/absorb_mcp.py" --repo-root "$REPO_ROOT" --output "$TOOL_REGISTRY"
    echo ""
    echo "Ver con: $0 tools"
    ;;

  blocks)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    if [[ ! -f "$BLOCKS_FILE" ]]; then echo "Sin bloqueos para $FLOWID"; exit 0; fi
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PY_DIR')
from common import read_yaml
data = read_yaml('$BLOCKS_FILE') or {}
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
    if [[ ! -f "$TELEMETRY_FILE" ]]; then echo "Sin telemetría para $FLOWID"; exit 0; fi
    STATS_FILE="$FLOW_DIR/telemetry-stats.json"
    "$PYTHON" "$PY_DIR/telemetry_aggregator.py" --input "$TELEMETRY_FILE" --output "$STATS_FILE" >/dev/null
    "$PYTHON" -c "
import json
with open('$STATS_FILE') as f: s = json.load(f)
print(f'Telemetría — {s[\"total_events\"]} eventos')
print(f'Tokens: {s[\"total_tokens\"]} | Duración: {s[\"total_duration_ms\"]}ms')
print(f'Bloqueos: {s[\"blocks_detected\"]} det, {s[\"blocks_resolved\"]} res')
print(f'Tests: {s[\"tests_run\"]} runs, {s[\"tests_failed\"]} fails, {s[\"rollbacks\"]} rollbacks')
print(f'Tools absorbidas: {s[\"tools_absorbed\"]}')
print('Eventos por kind:')
for k, v in sorted(s.get('events_by_kind', {}).items(), key=lambda x: -x[1]):
    print(f'  {k:<25} {v}')
"
    ;;

  evidence)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    if [[ ! -f "$EVIDENCE_FILE" ]]; then echo "No se encontró: $EVIDENCE_FILE"; exit 1; fi
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PY_DIR')
from common import read_yaml
p = read_yaml('$EVIDENCE_FILE') or {}
print(f'Evidence Pack v{p.get(\"version\", \"?\")} — {len(p.get(\"items\", []))} items')
print(f'Hash chain: {p.get(\"hash_chain\", \"?\")[:24]}...')
for it in p.get('items', []):
    print(f'  {it.get(\"id\", \"?\")} [{it.get(\"kind\", \"?\")}] {it.get(\"source\", \"?\")[:60]}')
"
    ;;

  plan)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido"; exit 1; fi
    if [[ ! -f "$PLAN_FILE" ]]; then echo "No se encontró: $PLAN_FILE"; exit 1; fi
    cat "$PLAN_FILE"
    ;;

  health)
    if [[ ! -f "$TOOL_REGISTRY" ]]; then echo "Sin TOOL-REGISTRY. Crear con: $0 absorb"; exit 1; fi
    "$PYTHON" "$PY_DIR/inspect_tools.py" --registry "$TOOL_REGISTRY" --repo-root "$REPO_ROOT"
    ;;

  init-flow)
    if [[ -z "$FLOWID" ]]; then echo "ERROR: --flowid requerido (formato: APOLO-YYYYMMDD-SLUG)"; exit 1; fi
    if [[ ! "$FLOWID" =~ ^APOLO-[0-9]{8}-[A-Z0-9-]+$ ]]; then
      echo "ERROR: flowid inválido. Formato: APOLO-YYYYMMDD-SLUG"; exit 1
    fi
    mkdir -p "$FLOW_DIR/evidence" "$FLOW_DIR/tests"
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PY_DIR')
from common import read_yaml, write_yaml, now_iso
if __import__('os').path.exists('$STATE_FILE'): print('Ya existe'); exit()
t = read_yaml('$PLUGIN_DIR/templates/FLOW-STATE.template.yaml') or {}
t['flowid'] = '$FLOWID'; t['created_at'] = now_iso(); t['updated_at'] = now_iso(); t['phase_entered_at'] = now_iso()
write_yaml('$STATE_FILE', t)
b = read_yaml('$PLUGIN_DIR/templates/BLOCK-LOG.template.yaml') or {}
b['flowid'] = '$FLOWID'; b['updated_at'] = now_iso()
write_yaml('$BLOCKS_FILE', b)
print(f'✅ Flow inicializado: $FLOWID')
"
    touch "$TELEMETRY_FILE"
    echo "✅ Telemetría inicializada"
    echo ""
    echo "Próximos pasos:"
    echo "  1. $0 absorb --repo-root $REPO_ROOT"
    echo "  2. $0 state --flowid $FLOWID"
    echo "  3. $0 serve-panel --flowid $FLOWID"
    ;;

  all)
    echo "=== STATE ==="; $0 state --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== TOOLS ==="; $0 tools --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== BLOCKS ==="; $0 blocks --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== TELEMETRY ==="; $0 telemetry --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== EVIDENCE ==="; $0 evidence --flowid "$FLOWID" --repo-root "$REPO_ROOT" 2>&1 || true; echo
    echo "=== HEALTH ==="; $0 health --repo-root "$REPO_ROOT" 2>&1 || true
    ;;

  serve-panel)
    PORT="${PORT:-8765}"
    "$PYTHON" "$PY_DIR/serve_panel.py" --repo-root "$REPO_ROOT" --flowid "$FLOWID" --port "$PORT"
    ;;

  test)
    "$PYTHON" "$PLUGIN_DIR/tests/run_all_tests.py"
    ;;

  help|--help|-h)
    cat <<HELP_EOF
apolo-inspect — CLI del plugin apolo-dynamic-flow

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
  serve-panel  Levanta panel HTTP (puerto 8080)
  test         Corre tests del plugin

Opciones:
  --flowid FLOW       Flow ID
  --repo-root PATH    Raíz del repo (default: cwd)
  --json              Output JSON

Ejemplos:
  $0 init-flow --flowid APOLO-20260620-MI-FLOW
  $0 absorb --repo-root /path/to/repo
  $0 state --flowid APOLO-20260620-MI-FLOW
  $0 serve-panel --flowid APOLO-20260620-MI-FLOW
HELP_EOF
    ;;

  *)
    echo "Subcomando desconocido: $SUBCMD. Usa: $0 help"
    exit 2
    ;;
esac

#!/usr/bin/env bash
# apolo-inspect.sh — CLI de inspección del plugin apolo-dynamic-flow.
#
# Uso:
#   apolo-inspect.sh <subcommand> [--flowid FLOW] [--repo-root PATH] [--json]
#
# Subcomandos:
#   state        Estado del flow activo
#   tools        Tools absorbidas
#   blocks       Bloqueos activos
#   telemetry    Stats de telemetría
#   evidence     Evidence pack actual
#   plan         Plan dinámico actual
#   health       Health check de todas las tools
#   all          Resumen completo
#   serve-panel  Levanta servidor HTTP para el panel en puerto 8080

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="${PYTHON:-python3}"

# Defaults
REPO_ROOT="${REPO_ROOT:-$(pwd)}"
FLOWID=""
JSON_OUT=""

# Parse args
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

# Si no se especifica flowid, intentar leer de plan/CURRENT
if [[ -z "$FLOWID" && -f "$REPO_ROOT/plan/CURRENT.md" ]]; then
  FLOWID=$(grep -oE 'APOLO-[0-9]{8}-[A-Z0-9-]+' "$REPO_ROOT/plan/CURRENT.md" | head -1 || true)
fi

case "$SUBCMD" in
  state)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspect_state({'repoRoot': '$REPO_ROOT', 'flowid': '$FLOWID', 'json': bool('$JSON_OUT')}))
" ;;

  tools)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspectTools({'repoRoot': '$REPO_ROOT', 'json': bool('$JSON_OUT')}))
" ;;

  blocks)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspect_blocks({'repoRoot': '$REPO_ROOT', 'flowid': '$FLOWID', 'json': bool('$JSON_OUT')}))
" ;;

  telemetry)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspectTelemetry({'repoRoot': '$REPO_ROOT', 'flowid': '$FLOWID', 'json': bool('$JSON_OUT')}))
" ;;

  evidence)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspectEvidence({'repoRoot': '$REPO_ROOT', 'flowid': '$FLOWID', 'json': bool('$JSON_OUT')}))
" ;;

  plan)
    PLAN_PATH="$REPO_ROOT/plan/active/$FLOWID/03-PLAN-INDICE-DYNAMIC.yaml"
    if [[ -f "$PLAN_PATH" ]]; then
      cat "$PLAN_PATH"
    else
      echo "No se encontró plan en $PLAN_PATH" >&2
      exit 1
    fi
    ;;

  health)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspectHealth({'repoRoot': '$REPO_ROOT'}))
" ;;

  all)
    "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR/plugin')
import inspector
print(inspector.inspectAll({'repoRoot': '$REPO_ROOT', 'flowid': '$FLOWID', 'json': bool('$JSON_OUT')}))
" ;;

  serve-panel)
    PORT="${PORT:-8080}"
    echo "Sirviendo panel en http://localhost:$PORT/?repo=$REPO_ROOT&flowid=$FLOWID"
    cd "$PLUGIN_DIR/panel"
    "$PYTHON" -m http.server "$PORT"
    ;;

  help|--help|-h)
    cat <<EOF
apolo-inspect — CLI de inspección del plugin apolo-dynamic-flow

Uso:
  apolo-inspect.sh <subcommand> [options]

Subcomandos:
  state        Estado del flow activo
  tools        Tools absorbidas (MCPs, skills, plugins, scripts)
  blocks       Bloqueos activos
  telemetry    Stats de telemetría
  evidence     Evidence pack actual
  plan         Plan dinámico actual
  health       Health check de todas las tools
  all          Resumen completo
  serve-panel  Levanta servidor HTTP para el panel (puerto 8080)

Opciones:
  --flowid FLOW       Flow ID a inspeccionar (default: plan/CURRENT.md)
  --repo-root PATH    Raíz del repo (default: cwd)
  --json              Output en JSON

Variables de entorno:
  PYTHON              Path a python3 (default: python3)
  PORT                Puerto para serve-panel (default: 8080)
EOF
    ;;

  *)
    echo "Subcomando desconocido: $SUBCMD" >&2
    echo "Usa: apolo-inspect.sh help" >&2
    exit 2
    ;;
esac

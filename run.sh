#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"
if [[ -f "$PROJECT_ROOT/.env.local" ]]; then
  set -a
  source "$PROJECT_ROOT/.env.local"
  set +a
fi

export FLASK_APP=run.py
export WFS_ENV="${WFS_ENV:-production}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"
PYTHON_BIN="${WFS_PYTHON:-python3}"

MODE="${1:-single}"

case "$MODE" in
  single)
    export WFS_ENABLE_SCHEDULER="${WFS_ENABLE_SCHEDULER:-true}"
    "$PYTHON_BIN" run.py
    ;;
  web)
    export WFS_ENABLE_SCHEDULER=false
    export WFS_SCHEDULER_CONTROL_URL="${WFS_SCHEDULER_CONTROL_URL:-http://127.0.0.1:8009}"
    "$PYTHON_BIN" -m flask run --host "${WFS_HOST:-127.0.0.1}" --port "${WFS_PORT:-8008}"
    ;;
  scheduler)
    export WFS_ENABLE_SCHEDULER=true
    "$PYTHON_BIN" -m flask run --host 127.0.0.1 --port "${WFS_CONTROL_PORT:-8009}"
    ;;
  migrate)
    "$PYTHON_BIN" scripts/migrate.py
    ;;
  *)
    echo "Usage: ./run.sh [single|web|scheduler|migrate]"
    exit 2
    ;;
esac

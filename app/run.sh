#!/bin/bash
set -euo pipefail

export FLASK_APP=run.py
export WFS_ENV="${WFS_ENV:-production}"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

MODE="${1:-single}"

case "$MODE" in
  single)
    export WFS_ENABLE_SCHEDULER="${WFS_ENABLE_SCHEDULER:-true}"
    python3 run.py
    ;;
  web)
    export WFS_ENABLE_SCHEDULER=false
    export WFS_SCHEDULER_CONTROL_URL="${WFS_SCHEDULER_CONTROL_URL:-http://127.0.0.1:8009}"
    python3 -m flask run --host 0.0.0.0 --port 8008
    ;;
  scheduler)
    export WFS_ENABLE_SCHEDULER=true
    python3 -m flask run --host 127.0.0.1 --port 8009
    ;;
  *)
    echo "Usage: ./run.sh [single|web|scheduler]"
    exit 2
    ;;
esac

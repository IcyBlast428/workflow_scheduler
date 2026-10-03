#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
set -a
source .env.postgres.local
set +a
export WFS_ENABLE_SCHEDULER=false
exec "$WFS_PYTHON" "$@"

#!/usr/bin/env bash
# Root / fixed-directory deployment. No Node, Git or Docker required on the server.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUTF8=1
PYTHON="${WFS_DEPLOY_PYTHON:-python3.12}"
if [[ -x .venv/bin/python ]]; then PYTHON="$PWD/.venv/bin/python"; fi
command -v "$PYTHON" >/dev/null 2>&1 || { echo '请先安装 Python 3.12（包含 venv/pip），或设置 WFS_DEPLOY_PYTHON。' >&2; exit 1; }
exec "$PYTHON" scripts/deploy.py "${@:-install}"

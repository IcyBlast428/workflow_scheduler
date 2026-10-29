#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PYTHON="${WFS_DRILL_PYTHON:-python3}"
# These test modules create isolated temporary databases/jobs. They do not read
# the local service .env and never kill the running platform.
"$PYTHON" -m unittest discover -s tests -p test_operations.py -v
"$PYTHON" -m unittest discover -s tests -p test_admission.py -v
"$PYTHON" -m unittest discover -s tests -p test_operational_workflows.py -v

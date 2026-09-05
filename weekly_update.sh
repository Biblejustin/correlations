#!/bin/bash
# Shared runtime entry point. Default updates local files; --publish opts into Git.
# --dry-run preserves its historical meaning: run locally, no commit/push.
# No checkout/reset/revert, implicit pull, or hidden failure masking.
set -eo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-$HERE/../venv/bin/python}"
if [ ! -x "$PY" ]; then
    python3 -m venv "$HERE/../venv"
    PY="$HERE/../venv/bin/python"
    "$PY" -m pip install -r "$HERE/requirements.txt" pytest
fi
exec "$PY" "$HERE/weekly_update.py" "$@"

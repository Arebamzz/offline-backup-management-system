#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required to run this backup script." >&2
    echo "Install Python 3.8+ or set PYTHON_BIN to the Python executable path." >&2
    exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
    exec /usr/bin/pkexec "$PYTHON_BIN" "$SCRIPT_DIR/bin/pull_backup.py" "$@"
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/bin/pull_backup.py" "$@"

#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PYTHON}"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required to run this backup app." >&2
    echo "Install Python 3.8+ or set PYTHON_BIN to the Python executable path." >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import PySide6" >/dev/null 2>&1; then
    echo "ERROR: PySide6 is required to run the desktop app." >&2
    echo "Run ./install_desktop_app.sh to create .venv and install PySide6." >&2
    exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/bin/pull_backup_gui.py" "$@"

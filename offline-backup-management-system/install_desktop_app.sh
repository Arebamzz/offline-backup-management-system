#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Offline Backup"
DESKTOP_FILE_NAME="offline-backup.desktop"
LOCAL_APPS_DIR="${HOME}/.local/share/applications"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-${HOME}/Desktop}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${SCRIPT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"

warn() {
    printf 'WARNING: %s\n' "$*" >&2
}

info() {
    printf '%s\n' "$*"
}

require_venv_pip() {
    if "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        return 0
    fi

    info "Bootstrapping pip inside ${VENV_DIR}"
    "$VENV_PYTHON" -m ensurepip --upgrade

    if ! "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        warn "pip is still missing inside ${VENV_DIR}."
        warn "Remove ${VENV_DIR}, then run this installer again."
        return 1
    fi
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    warn "Python 3 was not found. Install Python 3.8+ before running the app."
elif ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
    warn "Python venv support was not found. Install python3-venv, then run this installer again."
elif [ ! -x "$VENV_PYTHON" ]; then
    info "Creating Python virtual environment at ${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if [ -x "$VENV_PYTHON" ] && ! "$VENV_PYTHON" -c "import PySide6" >/dev/null 2>&1; then
    info "Installing PySide6 into ${VENV_DIR}"
    require_venv_pip
    "$VENV_PYTHON" -m pip install PySide6
fi

chmod +x "${SCRIPT_DIR}/pull_backup_v2.sh"
chmod +x "${SCRIPT_DIR}/pull_backup_gui.sh"
chmod +x "${SCRIPT_DIR}/bin/pull_backup.py"
chmod +x "${SCRIPT_DIR}/bin/pull_backup_gui.py"

mkdir -p "$LOCAL_APPS_DIR"

TEMP_DESKTOP_FILE="$(mktemp)"
cat >"$TEMP_DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME}
Comment=Configure and run the offline pull backup
Exec=${SCRIPT_DIR}/pull_backup_gui.sh
Icon=${SCRIPT_DIR}/assets/offline-backup.svg
Path=${SCRIPT_DIR}
Terminal=false
Categories=Utility;System;
StartupWMClass=offline-backup
EOF

install -m 755 "$TEMP_DESKTOP_FILE" "${LOCAL_APPS_DIR}/${DESKTOP_FILE_NAME}"

if [ -d "$DESKTOP_DIR" ]; then
    install -m 755 "$TEMP_DESKTOP_FILE" "${DESKTOP_DIR}/${DESKTOP_FILE_NAME}"
    info "Desktop icon installed to ${DESKTOP_DIR}/${DESKTOP_FILE_NAME}"
else
    warn "Desktop folder was not found: ${DESKTOP_DIR}"
fi

rm -f "$TEMP_DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$LOCAL_APPS_DIR" >/dev/null 2>&1 || true
fi

info "Application menu launcher installed to ${LOCAL_APPS_DIR}/${DESKTOP_FILE_NAME}"
info "Open '${APP_NAME}' from your application menu, or double-click the desktop icon."
info "If your desktop asks, right-click the icon and choose Allow Launching."

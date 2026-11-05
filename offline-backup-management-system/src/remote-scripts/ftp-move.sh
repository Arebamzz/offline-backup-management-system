#!/usr/bin/env bash

set -Eeuo pipefail

# ==================================================
# CONFIGURATION
# ==================================================

BASE_DIR="/YOUR_PATH/remote-backups"
INPROGRESS_DIR="$BASE_DIR/In_Progress"

A1_SOURCE="$BASE_DIR/SystemA-ProdBackup"
SYSTEM_B_SOURCE="$BASE_DIR/SystemB-ProdBackup"
PROJECT_SOURCE="$BASE_DIR/ProjectEnvironment"

A1_DEST="$INPROGRESS_DIR/SystemA-ProdBackup"
SYSTEM_B_DEST="$INPROGRESS_DIR/SystemB-ProdBackup"
PROJECT_DEST="$INPROGRESS_DIR/ProjectEnvironment"

# A file must be older than 5 minutes before being moved.
# This reduces the risk of moving a file that is still being written.
MINIMUM_AGE_MINUTES=5

LOCK_FILE="$BASE_DIR/.FTP.lock"
MOVED_COUNT=0

# ==================================================
# ERROR HANDLING
# ==================================================

handle_error() {
    EXIT_CODE=$?
    ERROR_LINE=$1

    echo
    echo "======================================"
    echo "ERROR: Move process failed."
    echo "Line: $ERROR_LINE"
    echo "Exit code: $EXIT_CODE"
    echo "======================================"

    exit "$EXIT_CODE"
}

trap 'handle_error "$LINENO"' ERR

# ==================================================
# MOVE FUNCTION
# ==================================================

move_file() {
    SOURCE_FILE="$1"
    DESTINATION_FOLDER="$2"

    FILE_NAME=$(basename "$SOURCE_FILE")
    DESTINATION_FILE="$DESTINATION_FOLDER/$FILE_NAME"

    if [ ! -s "$SOURCE_FILE" ]; then
        echo "Skipping empty source file: $SOURCE_FILE"
        return 0
    fi

    if [ -e "$DESTINATION_FILE" ] && [ -s "$DESTINATION_FILE" ]; then
        if cmp -s -- "$SOURCE_FILE" "$DESTINATION_FILE"; then
            rm -- "$SOURCE_FILE"
            echo "Already verified at destination: $DESTINATION_FILE"
            MOVED_COUNT=$((MOVED_COUNT + 1))
            return 0
        fi
        echo "ERROR: Destination has different non-empty content: $DESTINATION_FILE" >&2
        return 1
    fi

    echo "Copying and verifying:"
    echo "  From: $SOURCE_FILE"
    echo "  To  : $DESTINATION_FILE"

    SOURCE_META_BEFORE=$(stat -c '%s:%y' -- "$SOURCE_FILE")
    TEMP_FILE=$(mktemp -p "$DESTINATION_FOLDER" ".$FILE_NAME.XXXXXXXX.partial")

    if ! rsync -a -- "$SOURCE_FILE" "$TEMP_FILE"; then
        rm -f -- "$TEMP_FILE"
        return 1
    fi

    if ! cmp -s -- "$SOURCE_FILE" "$TEMP_FILE" || \
       [ "$(stat -c '%s:%y' -- "$SOURCE_FILE")" != "$SOURCE_META_BEFORE" ]; then
        rm -f -- "$TEMP_FILE"
        echo "ERROR: Source changed or copy verification failed: $SOURCE_FILE" >&2
        return 1
    fi

    mv -f -- "$TEMP_FILE" "$DESTINATION_FILE"
    rm -- "$SOURCE_FILE"

    MOVED_COUNT=$((MOVED_COUNT + 1))
}

# ==================================================
# START
# ==================================================

echo
echo "======================================"
echo "Checking for completed backup files"
echo "Time: $(date)"
echo "======================================"

# ==================================================
# CHECK REQUIRED COMMANDS
# ==================================================

for COMMAND in find mv flock stat basename mountpoint rsync cmp mktemp; do
    if ! command -v "$COMMAND" >/dev/null 2>&1; then
        echo "ERROR: Required command is missing:"
        echo "$COMMAND"
        exit 1
    fi
done

# Prevent multiple runs at the same time.
exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    echo "Another FTP move process is already running."
    echo "This run will stop without moving anything."
    exit 0
fi

# ==================================================
# CHECK SOURCE FOLDERS
# ==================================================

for DIRECTORY in \
    "$A1_SOURCE" \
    "$SYSTEM_B_SOURCE" \
    "$PROJECT_SOURCE"
do
    if [ ! -d "$DIRECTORY" ]; then
        echo "ERROR: Source directory was not found:"
        echo "$DIRECTORY"
        exit 1
    fi
done

# ==================================================
# VERIFY SECONDARY STORAGE
# ==================================================

if ! mountpoint -q -- "$INPROGRESS_DIR"; then
    echo "ERROR: In_Progress secondary storage is not mounted."
    exit 1
fi

# ==================================================
# CREATE DIRECT DESTINATION FOLDERS
# ==================================================

mkdir -p \
    "$A1_DEST" \
    "$SYSTEM_B_DEST" \
    "$PROJECT_DEST"

# ==================================================
# MOVE SYSTEM_B-A1 FULL.ZIP AND DIFF.ZIP
# ==================================================

echo
echo "Checking SYSTEM_B-A1 backup files..."

while IFS= read -r -d '' FILE; do
    move_file "$FILE" "$A1_DEST"
done < <(
    find "$A1_SOURCE" \
        -maxdepth 1 \
        -type f \
        -size +0c \
        -mmin +"$MINIMUM_AGE_MINUTES" \
        \( -iname "*-Full.zip" -o -iname "*-Diff.zip" \) \
        ! -name "*.partial" \
        -print0
)

# ==================================================
# MOVE SYSTEM_B FULL.ZIP AND DIFF.ZIP
# ==================================================

echo
echo "Checking SYSTEM_B backup files..."

while IFS= read -r -d '' FILE; do
    move_file "$FILE" "$SYSTEM_B_DEST"
done < <(
    find "$SYSTEM_B_SOURCE" \
        -maxdepth 1 \
        -type f \
        -size +0c \
        -mmin +"$MINIMUM_AGE_MINUTES" \
        \( -iname "*-Full.zip" -o -iname "*-Diff.zip" \) \
        ! -name "*.partial" \
        -print0
)

# ==================================================
# MOVE ALL COMPLETED PROJECT FILES
# ==================================================

echo
echo "Checking PROJECT backup files..."

while IFS= read -r -d '' FILE; do
    move_file "$FILE" "$PROJECT_DEST"
done < <(
    find "$PROJECT_SOURCE" \
        -maxdepth 1 \
        -type f \
        -size +0c \
        -mmin +"$MINIMUM_AGE_MINUTES" \
        ! -name "*.partial" \
        ! -name "*.swp" \
        ! -name ".*.swp" \
        -print0
)

# ==================================================
# RESULT
# ==================================================

if [ "$MOVED_COUNT" -eq 0 ]; then
    echo
    echo "No new completed backup files were found."
    echo "Nothing was moved."
    exit 0
fi

echo
echo "======================================"
echo "DONE"
echo "$MOVED_COUNT file(s) moved successfully."
echo
echo "Destination:"
echo "$INPROGRESS_DIR"
echo
echo "Completion time: $(date)"
echo "======================================"

echo
echo "Current files in In_Progress:"

find "$INPROGRESS_DIR" \
    -type f \
    -printf '%TY-%Tm-%Td %TH:%TM | %s bytes | %p\n'

exit 0

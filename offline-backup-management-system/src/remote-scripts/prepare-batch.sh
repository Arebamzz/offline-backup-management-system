set -Eeuo pipefail

REQUESTED_BATCH="$1"
BASE="$2"
SOURCE="$3"
QUEUE_ROOT="$4"
LOCK_FILE="$5"
shift 5

exec 9>"$LOCK_FILE"

if ! flock -w 300 9; then
    echo "LOCK_TIMEOUT"
    exit 75
fi

if [ ! -d "$SOURCE" ]; then
    echo "ERROR_INPROGRESS_MISSING"
    exit 1
fi

if ! mountpoint -q -- "$SOURCE"; then
    echo "ERROR: In_Progress secondary storage is not mounted."
    exit 1
fi

if [ "$(dirname -- "$QUEUE_ROOT")" != "$SOURCE" ]; then
    echo "ERROR: Queue must be a direct child of In_Progress."
    exit 1
fi

mkdir -p "$QUEUE_ROOT"

if [ "$(stat -c %d -- "$SOURCE")" != "$(stat -c %d -- "$QUEUE_ROOT")" ]; then
    echo "ERROR: Queue and In_Progress are on different filesystems."
    exit 1
fi

# Remove empty queue folders left from completed runs.
while IFS= read -r -d '' DIRECTORY; do
    if [ -z "$(find "$DIRECTORY" -type f -print -quit)" ]; then
        rm -rf -- "$DIRECTORY"
    fi
done < <(
    find "$QUEUE_ROOT" \
        -mindepth 1 \
        -maxdepth 1 \
        -type d \
        -print0
)

# Retry an existing queue before starting a new batch.
EXISTING="$(
    find "$QUEUE_ROOT" \
        -mindepth 1 \
        -maxdepth 1 \
        -type d \
        -printf '%f\n' |
    sort |
    head -n 1 || true
)"

if [ -n "$EXISTING" ] && [ ! -e "$QUEUE_ROOT/$EXISTING/.pending" ]; then
    EMPTY_FILE="$(find "$QUEUE_ROOT/$EXISTING" -type f -size 0 -print -quit)"
    if [ -n "$EMPTY_FILE" ]; then
        echo "ERROR: Empty backup file in transfer queue: $EMPTY_FILE" >&2
        exit 1
    fi
    printf 'BATCH:%s\n' "$EXISTING"
    exit 0
fi

if [ -z "$EXISTING" ] && [ -z "$(find "$SOURCE" -path "$QUEUE_ROOT" -prune -o -type f -print -quit)" ]; then
    echo "NO_FILES"
    exit 0
fi

if [ -z "$EXISTING" ]; then
    EMPTY_FILE="$(find "$SOURCE" -path "$QUEUE_ROOT" -prune -o -type f -size 0 -print -quit)"
    if [ -n "$EMPTY_FILE" ]; then
        echo "ERROR: Empty backup file in In_Progress: $EMPTY_FILE" >&2
        exit 1
    fi
fi

if [ -n "$EXISTING" ]; then
    REQUESTED_BATCH="$EXISTING"
fi

QUEUE="$QUEUE_ROOT/$REQUESTED_BATCH"
NEW_SOURCE="$SOURCE/.In_Progress.new.$REQUESTED_BATCH"

if [ -z "$EXISTING" ] && { [ -e "$QUEUE" ] || [ -e "$NEW_SOURCE" ]; }; then
    echo "ERROR: Temporary queue or replacement folder already exists."
    exit 1
fi

# Prepare replacement folders before moving the current batch.
for DIRECTORY in "$@"; do
    if [ ! -d "$SOURCE/$DIRECTORY" ] || [ -z "$EXISTING" ]; then
        mkdir -p "$NEW_SOURCE/$DIRECTORY"
    fi
done

if [ -d "$NEW_SOURCE" ]; then
    chown -R --reference="$SOURCE" "$NEW_SOURCE"
fi

if [ -z "$EXISTING" ]; then
    mkdir -- "$QUEUE"
    touch -- "$QUEUE/.pending"
fi

# Keep the mount point in place. Moving children stays on the secondary disk.
# The pending marker lets the next run finish an interrupted freeze.
while IFS= read -r -d '' ENTRY; do
    NAME="$(basename -- "$ENTRY")"
    if [ ! -e "$QUEUE/$NAME" ]; then
        mv -- "$ENTRY" "$QUEUE/$NAME"
    fi
done < <(
    find "$SOURCE" -mindepth 1 -maxdepth 1 \
        ! -path "$QUEUE_ROOT" \
        ! -path "$NEW_SOURCE" \
        -print0
)

for DIRECTORY in "$@"; do
    if [ ! -e "$SOURCE/$DIRECTORY" ]; then
        if [ ! -d "$NEW_SOURCE/$DIRECTORY" ]; then
            mkdir -p "$NEW_SOURCE/$DIRECTORY"
            chown -R --reference="$SOURCE" "$NEW_SOURCE/$DIRECTORY"
        fi
        mv -- "$NEW_SOURCE/$DIRECTORY" "$SOURCE/$DIRECTORY"
    elif [ -d "$NEW_SOURCE/$DIRECTORY" ]; then
        rmdir -- "$NEW_SOURCE/$DIRECTORY"
    fi
done

if [ -d "$NEW_SOURCE" ]; then
    rmdir -- "$NEW_SOURCE"
fi

EMPTY_FILE="$(find "$QUEUE" -path "$QUEUE/.pending" -prune -o -type f -size 0 -print -quit)"
if [ -n "$EMPTY_FILE" ]; then
    echo "ERROR: Empty backup file in transfer queue: $EMPTY_FILE" >&2
    exit 1
fi

rm -- "$QUEUE/.pending"
printf 'BATCH:%s\n' "$REQUESTED_BATCH"

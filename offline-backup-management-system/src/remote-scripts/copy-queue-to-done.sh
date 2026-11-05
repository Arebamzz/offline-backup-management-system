set -Eeuo pipefail

BATCH="$1"
QUEUE_ROOT="$2"
DONE_ROOT="$3"
RESERVE_BYTES="$4"

QUEUE="$QUEUE_ROOT/$BATCH"

if [ ! -d "$QUEUE" ]; then
    echo "ERROR: Remote queue does not exist:"
    echo "$QUEUE"
    exit 1
fi

mkdir -p "$DONE_ROOT"

QUEUE_BYTES="$(du -sb "$QUEUE" | awk '{print $1}')"
DONE_BYTES="$(du -sb "$DONE_ROOT" | awk '{print $1}')"

AVAILABLE_BYTES="$(
    df -B1 --output=avail "$DONE_ROOT" |
    tail -n 1 |
    tr -d ' '
)"

# Existing Done data will be deleted before the latest files are copied,
# so its current size can be counted as reclaimable space.
RECLAIMABLE_BYTES=$((AVAILABLE_BYTES + DONE_BYTES))

if [ "$RECLAIMABLE_BYTES" -lt $((QUEUE_BYTES + RESERVE_BYTES)) ]; then
    echo "ERROR: Developer Done disk does not have enough usable space."
    echo "Queue bytes       : $QUEUE_BYTES"
    echo "Usable after clean: $RECLAIMABLE_BYTES"
    echo "Required reserve  : $RESERVE_BYTES"
    exit 1
fi

rsync -a \
    --partial \
    --delete-before \
    "$QUEUE/" \
    "$DONE_ROOT/"

echo "DONE_LATEST_COPY_COMPLETE"

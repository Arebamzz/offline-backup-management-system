set -Eeuo pipefail

BATCH="$1"
QUEUE_ROOT="$2"
DONE_ROOT="$3"

QUEUE="$QUEUE_ROOT/$BATCH"

if [ -d "$QUEUE" ]; then
    rm -rf -- "$QUEUE"
fi

echo "Remote transfer queue cleared: $BATCH"

echo "Developer disk usage:"
df -h / "$DONE_ROOT"

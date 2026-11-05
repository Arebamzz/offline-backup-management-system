#!/usr/bin/env bash

set -Eeuo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root." >&2
    exit 1
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROD="/opt/offline-backup"
SCRIPT="$PROD/src/remote-scripts/prepare-batch.sh"
CONFIG="$PROD/config/pull-backup.json"

python3 - "$CONFIG" <<'PY'
import json
import sys

remote = json.load(open(sys.argv[1], encoding="utf-8"))["remote"]
source = "/YOUR_PATH/remote-backups/In_Progress"
old_queue = "/YOUR_PATH/remote-backups/.Transfer_Queue"
new_queue = source + "/.Transfer_Queue"
if remote["inProgressPath"] != source or remote["queueRoot"] not in (old_queue, new_queue):
    raise SystemExit("Production remote paths differ from expected values; no files changed.")
PY

stamp="$(date +%Y%m%d-%H%M%S)"
cp -a -- "$SCRIPT" "$SCRIPT.before-mounted-queue.$stamp"
cp -a -- "$CONFIG" "$CONFIG.before-mounted-queue.$stamp"

install -m "$(stat -c %a "$SCRIPT")" \
    -o "$(stat -c %U "$SCRIPT")" -g "$(stat -c %G "$SCRIPT")" \
    "$ROOT/src/remote-scripts/prepare-batch.sh" "$SCRIPT"

python3 - "$CONFIG" <<'PY'
import json
import os
import pathlib
import sys
import tempfile

path = pathlib.Path(sys.argv[1])
original = path.read_text(encoding="utf-8")
old = '"queueRoot": "/YOUR_PATH/remote-backups/.Transfer_Queue"'
new = '"queueRoot": "/YOUR_PATH/remote-backups/In_Progress/.Transfer_Queue"'
if original.count(old) == 1:
    updated = original.replace(old, new, 1)
elif original.count(new) == 1:
    updated = original
else:
    raise SystemExit("Production queueRoot did not match; restore the script from its saved copy.")
json.loads(updated)
stat = path.stat()
descriptor, temporary = tempfile.mkstemp(prefix=".pull-backup-queue-", dir=path.parent)
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(updated)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, stat.st_mode & 0o777)
    os.chown(temporary, stat.st_uid, stat.st_gid)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

bash -n "$SCRIPT"
echo "Mounted queue installed. Previous production files saved with suffix: $stamp"

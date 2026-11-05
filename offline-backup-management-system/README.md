# Offline Backup Management System — Sanitized Source Portfolio

> **Source snapshot for review only.** Hostnames, IP addresses, user accounts, internal system labels, email addresses, disk UUIDs and production paths have been replaced with example values or `YOUR_*` placeholders. This is **not a ready-to-run production configuration**. Permission from the original code owner is still required before publication, even with secrets removed.

The codebase includes a Python backup orchestration CLI, PySide6 desktop GUI, Docs Library synchronization, rsync/SSH integration, JSON/SQLite configuration, logging/reporting and systemd support. Some legacy JavaScript components remain in the snapshot.

**Important:** The example IP ranges `192.0.2.0/24` and `203.0.113.0/24` are reserved for documentation. Replace them for an authorized test environment. Never use this demo against live systems without reviewing all actions (including file movement/deletion, network setup, ownership changes and disk mounts).

## Setup

```bash
cp config/pull-backup.example.json config/pull-backup.json
# Edit local config; this file is gitignored
python3 scripts/check_syntax.py
```

See `SANITIZATION_NOTES.md` for a change summary, excluded internal files, and remaining publication checks.

---

# Offline Backup Script

This project keeps the existing `pull_backup_v2.sh` entrypoint, but the backup workflow now runs through a configurable Python CLI.

## Run

Requires Python 3.8+ on the offline backup PC. No third-party Python packages are required.

```bash
./pull_backup_v2.sh
```

The runtime configuration is `config/pull-backup.json` (excluded from version control). Copy the example first, replace all placeholders with values appropriate to an authorized test environment, and review every path and script before use.

```bash
cp config/pull-backup.example.json config/pull-backup.json
```

To run with another config file:

```bash
PULL_BACKUP_CONFIG=/etc/pull-backup/config.json ./pull_backup_v2.sh
```

or:

```bash
python3 ./bin/pull_backup.py --config /etc/pull-backup/config.json
```

## Desktop GUI

Start the PySide6 desktop app with the repository virtualenv:

```bash
.venv/bin/python bin/pull_backup_gui.py
```

or use the desktop launcher installed for the project. The Dashboard activity
view can show both:

- the production Offline Backup log at `/var/log/pull_backup/pull_backup.log`
- the local Docs Backup log at `/home/YOUR_USERNAME/.local/share/offline-backup/pull_backup.log`

Use **Refresh Activity** to reload the latest readable summaries. The GUI
filters noisy rsync/OpenSSH progress from the dashboard; use **Open Full Log**
when detailed transfer output is needed.

## LAN permissions

The backup entrypoint uses one `pkexec` authentication at startup. The whole
backup then runs with the required network and disk permissions, including LAN
cleanup when the backup finishes.

## Docs Library Backup

The GUI **Docs Library** tab stores file-server configuration in SQLite:

```text
/YOUR_PATH/backup-storage/docs_backup/docs_servers.sqlite
```

Each server can have one or more backup paths:

```text
Local Path  = folder on the 4TB backup disk
Remote Path = folder on the source server
```

Example:

```text
Local Path  = /YOUR_PATH/backup-storage/docs_backup/ExampleFileServer/bankin_slip_1.1
Remote Path = /YOUR_PATH/source-documents/bankin_slip_1.1
```

Run all configured Docs paths from the terminal:

```bash
.venv/bin/python bin/pull_docs.py --config config/pull-backup.json
```

The first successful sync for a path copies the remote directory contents into
the local directory with rsync. Later syncs use the path's `Last Synced`
checkpoint, scan the remote server for newer files, and copy only new or
updated files. Local files are not deleted when remote files disappear.

`Last Synced` updates only after a path finishes successfully. If the source
server drops or rsync fails partway through, the checkpoint stays unchanged so
the next run retries from the previous successful point.

Docs backup uses the configured SSH key and known_hosts settings. The current
production-style key paths are:

```text
/home/YOUR_USERNAME/.ssh/YOUR_SSH_KEY
/home/YOUR_USERNAME/.ssh/known_hosts
```

If production Offline Backup summaries are missing from the GUI but exist in
`/var/log/pull_backup/pull_backup.log`, make sure the desktop user can read the
production log:

```bash
sudo setfacl -m u:YOUR_USERNAME:rx /var/log/pull_backup
sudo setfacl -m m:rx,u:YOUR_USERNAME:r /var/log/pull_backup/pull_backup.log
sudo setfacl -d -m u:YOUR_USERNAME:rx /var/log/pull_backup
sudo setfacl -d -m m:rx /var/log/pull_backup
```

## Maintain

- Edit paths, remote host, LAN settings, SSH options, safety limits, WORM retention, and email settings in `config/pull-backup.json`.
- Use `config/pull-backup.example.json` as a template for another environment.
- The workflow orchestration lives in `src/backup_lib/backup_orchestrator.py`.
- Remote server scripts live in `src/remote-scripts/`.
- Operational pieces are separated under `src/backup_lib/services/`.
- Docs Library server/path configuration is stored in `/YOUR_PATH/backup-storage/docs_backup/docs_servers.sqlite` and mirrored into `docs.servers` in the active config for compatibility.

The automatic offline backup flow keeps the LAN enabled while the Offline
Backup completes and sends its SUCCESS report, then runs the Docs Library
backup in the same process. LAN cleanup happens only after Docs Library backup
finishes. Do not enable a separate `docs-backup.timer`, or Docs Library will
run independently from the combined flow.

## Verify Syntax

```bash
python3 ./scripts/check_syntax.py
```

You can also check the entrypoint without starting a backup:

```bash
./pull_backup_v2.sh --help
```

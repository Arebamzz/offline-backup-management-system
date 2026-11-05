import os
import pathlib
import posixpath
import shlex
import sqlite3
from datetime import datetime, timedelta, timezone

from backup_lib.core.ssh_options import build_rsync_remote_shell, build_ssh_args
from backup_lib.services.docs_db import DOC_EXTENSIONS, index_docs


class DocsBackup:
    def __init__(self, config, runner, logger):
        self.config = config
        self.runner = runner
        self.logger = logger

    def run(self):
        docs = self.config.get("docs", {})
        if docs.get("serverDbPath"):
            self._run_configured_servers(pathlib.Path(docs["serverDbPath"]))
            return

        entries = docs.get("replacementDocs", [])
        local_root = docs["localRoot"]
        db_path = docs["dbPath"]

        if not entries:
            self.logger.line("Docs backup skipped: Replacement Docs is empty.")
            index_count = index_docs(local_root, db_path)
            self.logger.line("Docs DB indexed: {} files.".format(index_count))
            return

        pathlib.Path(local_root).mkdir(parents=True, exist_ok=True)

        self.logger.line("Docs backup started.")
        self.logger.line("Docs local root: {}".format(local_root))
        self.logger.line("Docs DB: {}".format(db_path))

        for entry in entries:
            remote_path = self._remote_path(entry)
            self.logger.line("Pulling docs: {} -> {}".format(remote_path, local_root))
            self._rsync(remote_path, local_root)

        index_count = index_docs(local_root, db_path, DOC_EXTENSIONS)
        self.logger.line("Docs DB indexed: {} files.".format(index_count))
        self.logger.line("SUCCESS: Docs backup completed.")

    def _run_configured_servers(self, db_path):
        docs = self.config.get("docs", {})
        local_root = docs.get("localRoot") or str(db_path.parent)
        index_db_path = docs.get("dbPath") or str(
            pathlib.Path(local_root) / "docs.sqlite"
        )

        if not db_path.exists():
            self.logger.line("Docs server config skipped: DB not found: {}".format(db_path))
            index_count = index_docs(local_root, index_db_path)
            self.logger.line("Docs DB indexed: {} files.".format(index_count))
            return

        pathlib.Path(local_root).mkdir(parents=True, exist_ok=True)
        self.logger.line(
            "Docs backup started: {}".format(
                datetime.now().astimezone().strftime("%-d/%-m/%y %H:%M")
            )
        )
        self.logger.line("Docs server backup started.")
        self.logger.line("Docs server config DB: {}".format(db_path))

        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            filters = []
            params = []
            target_name = os.environ.get("OFFLINE_BACKUP_DOCS_SERVER_NAME", "").strip()
            target_ip = os.environ.get("OFFLINE_BACKUP_DOCS_SERVER_IP", "").strip()
            target_index = os.environ.get("OFFLINE_BACKUP_DOCS_PATH_INDEX", "").strip()

            if target_name:
                filters.append("servers.name = ?")
                params.append(target_name)
            if target_ip:
                filters.append("servers.ip = ?")
                params.append(target_ip)
            if target_index:
                filters.append("backup_paths.sort_order = ?")
                params.append(int(target_index))

            where_clause = "WHERE " + " AND ".join(filters) if filters else ""
            rows = list(
                connection.execute(
                    """
                    SELECT
                        backup_paths.id AS path_id,
                        backup_paths.local_path,
                        backup_paths.remote_path,
                        backup_paths.last_synced,
                        servers.name,
                        servers.ip,
                        servers.username
                    FROM backup_paths
                    JOIN servers ON servers.id = backup_paths.server_id
                    {where_clause}
                    ORDER BY servers.id, backup_paths.sort_order, backup_paths.id
                    """.format(where_clause=where_clause),
                    params,
                )
            )

            if not rows:
                self.logger.line("Docs server backup skipped: no backup paths configured.")
                index_count = index_docs(local_root, index_db_path)
                self.logger.line("Docs DB indexed: {} files.".format(index_count))
                return

            for row in rows:
                self.logger.line(
                    "Docs status: {} -> Last Synced: {}".format(
                        row["remote_path"],
                        self._display_timestamp(row["last_synced"]),
                    )
                )
                self._sync_configured_path(connection, row)

        index_count = index_docs(local_root, index_db_path, DOC_EXTENSIONS)
        self.logger.line("Docs DB indexed: {} files.".format(index_count))
        self.logger.line("SUCCESS: Docs server backup completed.")

    def _sync_configured_path(self, connection, row):
        local_path = row["local_path"]
        remote_path = row["remote_path"]
        remote_host = "{}@{}".format(row["username"], row["ip"])
        last_synced = row["last_synced"]

        pathlib.Path(local_path).mkdir(parents=True, exist_ok=True)
        self.logger.line(
            "Docs path: {} {}:{} -> {}".format(
                row["name"], remote_host, remote_path, local_path
            )
        )

        sync_checkpoint = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if last_synced:
            copied = self._rsync_newer_files(
                remote_host,
                remote_path,
                local_path,
                last_synced,
            )
            self.logger.line(
                "Docs incremental copied {} file(s) since {}.".format(
                    copied, last_synced
                )
            )
        else:
            self._rsync_directory(remote_host, remote_path, local_path)
            self.logger.line("Docs initial sync completed.")

        connection.execute(
            "UPDATE backup_paths SET last_synced = ? WHERE id = ?",
            (sync_checkpoint, row["path_id"]),
        )
        connection.commit()

    def _rsync_directory(self, remote_host, remote_path, local_path):
        remote_shell = build_rsync_remote_shell(self.config["ssh"])
        remote_source = "{}:{}/".format(remote_host, remote_path.rstrip("/"))

        self.runner.run(
            "rsync",
            [
                "-a",
                "-e",
                remote_shell,
                remote_source,
                local_path.rstrip("/") + "/",
            ],
        )

    def _rsync_newer_files(self, remote_host, remote_path, local_path, last_synced):
        remote_shell = build_rsync_remote_shell(self.config["ssh"])
        scan_since = self._scan_since(last_synced)
        find_command = (
            "cd {root} && find . -type f -newermt {timestamp} -print"
        ).format(
            root=shlex.quote(remote_path),
            timestamp=shlex.quote(scan_since),
        )
        return self._rsync_newer_files_with_shell(
            remote_shell, remote_host, remote_path, local_path, find_command
        )

    def _scan_since(self, last_synced):
        try:
            parsed = datetime.fromisoformat(str(last_synced).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return (parsed - timedelta(minutes=5)).isoformat(timespec="seconds")
        except ValueError:
            return last_synced

    def _display_timestamp(self, value):
        if not value:
            return "Never"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%-d/%-m/%y %H:%M")
        except ValueError:
            return str(value)

    def _rsync_newer_files_with_shell(
        self, remote_shell, remote_host, remote_path, local_path, find_command
    ):
        find_result = self.runner.run(
            "ssh",
            build_ssh_args(self.config["ssh"]) + [remote_host, find_command],
            capture_stdout=True,
            capture_stderr=True,
            stream_output=False,
        )
        files = [line.strip() for line in find_result.stdout.splitlines() if line.strip()]
        if not files:
            return 0

        files_from = "\n".join(files) + "\n"
        self.runner.run(
            "rsync",
            [
                "-a",
                "--relative",
                "--files-from=-",
                "-e",
                remote_shell,
                "{}:{}/".format(remote_host, remote_path.rstrip("/")),
                local_path.rstrip("/") + "/",
            ],
            input_text=files_from,
        )
        return len(files)

    def _remote_path(self, entry):
        value = str(entry).strip()
        if value.startswith("/"):
            return value
        return posixpath.join(self.config["remote"]["base"], value)

    def _rsync(self, remote_path, target_root):
        remote_shell = build_rsync_remote_shell(self.config["ssh"])
        remote_source = "{}:{}".format(self.config["remote"]["host"], remote_path)

        self.runner.run(
            "rsync",
            [
                "-a",
                "--relative",
                "-e",
                remote_shell,
                remote_source,
                target_root + "/",
            ],
        )

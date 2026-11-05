#!/usr/bin/env python3

import json
import os
import pathlib
import re
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

try:
    from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt, QUrl
    from PySide6.QtGui import QIcon
    from PySide6.QtWebSockets import QWebSocket
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QStyle,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    sys.stderr.write("ERROR: PySide6 is required to run the desktop app.\n")
    sys.exit(1)


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from backup_lib.config import resolve_writable_log_path
from backup_lib.core.ssh_options import build_ssh_args, build_rsync_remote_shell

DEFAULT_CONFIG = ROOT / "config" / "pull-backup.json"
BACKUP_SCRIPT = ROOT / "pull_backup_v2.sh"
DOCS_BACKUP_SCRIPT = ROOT / "bin" / "pull_docs.py"
APP_ICON = ROOT / "assets" / "offline-backup.svg"
APP_ID = "offline-backup"
SYSTEM_CONFIG = pathlib.Path("/opt/offline-backup/config/pull-backup.json")
SYSTEM_LOG = pathlib.Path("/var/log/pull_backup/pull_backup.log")


FIELD_GROUPS = [
    (
        "Remote",
        [
            ("Host", "remote.host", "text"),
            ("Base", "remote.base", "text"),
            ("Queue root", "remote.queueRoot", "text"),
            ("Done root", "remote.doneRoot", "text"),
            ("In progress path", "remote.inProgressPath", "text"),
            ("Lock file", "remote.lockFile", "text"),
            ("Replacement dirs", "remote.replacementDirs", "lines"),
        ],
    ),
    (
        "Local",
        [
            ("Mount", "local.mount", "dir"),
            ("Root", "local.root", "dir"),
            ("Stage root", "local.stageRoot", "dir"),
            ("Expected UUID", "local.expectedUuid", "text"),
            ("Lock file", "local.lockFile", "file"),
            ("Log file", "local.logFile", "file"),
            ("Owner", "local.owner", "text"),
            ("Group", "local.group", "text"),
            ("Root mode", "local.rootMode", "text"),
        ],
    ),
    (
        "SSH + LAN",
        [
            ("SSH key", "ssh.key", "file"),
            ("Known hosts", "ssh.knownHosts", "file"),
            ("Connect timeout seconds", "ssh.connectTimeoutSeconds", "int"),
            ("Identities only", "ssh.identitiesOnly", "bool"),
            ("Batch mode", "ssh.batchMode", "bool"),
            ("Strict host key checking", "ssh.strictHostKeyChecking", "bool"),
            ("LAN enabled", "lan.enabled", "bool"),
            ("LAN interface", "lan.interface", "text"),
            ("LAN IPv4", "lan.ipv4", "text"),
            ("LAN wait seconds", "lan.waitSeconds", "int"),
            ("Require default route", "lan.requireDefaultRoute", "bool"),
        ],
    ),
    (
        "Safety + WORM",
        [
            ("Minimum files", "safetyGuard.minFiles", "int"),
            ("Minimum bytes", "safetyGuard.minBytes", "int"),
            ("Developer Done reserve bytes", "developerDone.reserveBytes", "int"),
            ("WORM root", "worm.root", "dir"),
            ("WORM keep days", "worm.keepDays", "int"),
            ("WORM owner", "worm.owner", "text"),
            ("WORM group", "worm.group", "text"),
            ("WORM dir mode", "worm.dirMode", "text"),
            ("WORM file mode", "worm.fileMode", "text"),
        ],
    ),
    (
        "Email + Logging",
        [
            ("Email from", "email.from", "text"),
            ("Email to", "email.to", "lines"),
            ("msmtp binary", "email.msmtpBin", "file"),
            ("msmtp config", "email.msmtpConfig", "file"),
            ("Mirror log to console", "logging.mirrorToConsole", "bool"),
            ("Required commands", "requiredCommands", "lines"),
        ],
    ),
]


def read_nested(data, dotted_key, default=""):
    current = data
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return default
        current = current.get(part)
    return default if current is None else current


def write_nested(data, dotted_key, value):
    current = data
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


class NoClipboardLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.NoContextMenu)

    def keyPressEvent(self, event):
        blocked_keys = {Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_X}
        has_shortcut_modifier = bool(
            event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)
        )
        if has_shortcut_modifier and event.key() in blocked_keys:
            return
        if event.key() == Qt.Key.Key_Insert and event.modifiers() & Qt.ShiftModifier:
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            return
        super().mousePressEvent(event)


class RatioTableWidget(QTableWidget):
    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self._ratio_update_pending = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._ratio_update_pending:
            self._ratio_update_pending = True
            QTimer.singleShot(0, self._apply_column_ratio)

    def _apply_column_ratio(self):
        self._ratio_update_pending = False
        header = self.horizontalHeader()
        if header.count() != 3:
            return

        total_width = max(0, header.width())
        for index, ratio in enumerate((3, 3, 1)):
            header.resizeSection(index, total_width * ratio // 7)


class DocsPathTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 5, parent)
        self._ratio_update_pending = False
        self.setHorizontalHeaderLabels(
            ["No.", "Local Path", "Remote Path", "Last Synced", "Action"]
        )
        self.verticalHeader().setVisible(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._ratio_update_pending:
            self._ratio_update_pending = True
            QTimer.singleShot(0, self._apply_column_ratio)

    def _apply_column_ratio(self):
        self._ratio_update_pending = False
        header = self.horizontalHeader()
        if header.count() != 5:
            return

        total_width = max(0, header.width())
        for index, ratio in enumerate((1, 4, 4, 2, 1)):
            header.resizeSection(index, total_width * ratio // 12)


class BackupWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.config_path = DEFAULT_CONFIG
        self.widgets = {}
        self.docs_servers = []
        self.docs_server_passwords = {}
        self.docs_db_path = None
        self._refresh_open_docs_config = None
        self.process = None
        self.log_position = 0
        self.log_source_path = None
        from collections import deque
        self._log_lines = deque(maxlen=300)
        self._last_inventory_signature = None
        self._last_log_permission_warning = None
        self._last_activity_line = None
        self._activity_manual_view = False
        self.ws = None

        self.setWindowTitle("Offline Backup")
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1050, 650)
        self.setMinimumSize(850, 550)

        self._build()
        self.load_config()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_dashboard)
        self.timer.start(1500)

        self.refresh_dashboard()
        # try connect to local websocket server for realtime updates
        try:
            self.ws = QWebSocket()
            self.ws.textMessageReceived.connect(self._on_ws_message)
            self.ws.errorOccurred.connect(lambda e: None)
            self.ws.open(QUrl('ws://localhost:8080/ws'))
        except Exception:
            self.ws = None

    def _build(self):
        container = QWidget()
        outer = QVBoxLayout(container)

        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self._build_dashboard()
        self._build_docs_library()

        for title, fields in FIELD_GROUPS:
            tab = QWidget()
            form = QFormLayout(tab)

            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignLeft)
            form.setFormAlignment(Qt.AlignTop)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(8)

            for label, key, kind in fields:
                form.addRow(label, self._make_field(key, kind))

            self.tabs.addTab(tab, title)

        actions = QHBoxLayout()

        for label, handler in [
            ("Save Config", self.save_config),
            ("Run Backup", self.run_backup),
            ("Stop", self.stop_backup),
        ]:
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)

        actions.addStretch(1)

        clear_button = QPushButton("Clear View")
        clear_button.clicked.connect(self.clear_activity_view)
        actions.addWidget(clear_button)

        log_button = QPushButton("Open Full Log")
        log_button.clicked.connect(self.open_log_file)
        actions.addWidget(log_button)

        outer.addLayout(actions)

        self.status_label = QLabel("Ready")
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.status_label)

        self.setCentralWidget(container)

    def _build_docs_library(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("Backup file server configuration"))

        self.docs_table = RatioTableWidget(0, 3)
        self.docs_table.setHorizontalHeaderLabels(["Name", "IP", "Action"])
        self.docs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.docs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.docs_table.setSelectionMode(QTableWidget.SingleSelection)
        self.docs_table.verticalHeader().setVisible(False)
        header = self.docs_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        self.docs_table.itemSelectionChanged.connect(self._update_delete_server_button)
        QTimer.singleShot(0, self.docs_table._apply_column_ratio)
        layout.addWidget(self.docs_table, 1)

        server_actions = QHBoxLayout()

        add_server_button = QPushButton("Add server")
        add_server_button.clicked.connect(self.add_docs_server)
        server_actions.addWidget(add_server_button)

        self.delete_server_button = QToolButton()
        self.delete_server_button.setIcon(
            QApplication.style().standardIcon(QStyle.SP_TrashIcon)
        )
        self.delete_server_button.setToolTip("Delete selected server")
        self.delete_server_button.setAccessibleName("Delete selected server")
        self.delete_server_button.setEnabled(False)
        self.delete_server_button.clicked.connect(self.delete_selected_server)
        server_actions.addWidget(self.delete_server_button)
        server_actions.addStretch(1)

        layout.addLayout(server_actions)

        self.tabs.addTab(tab, "Docs Library")

    def _docs_config_db_path(self):
        data = self._read_config_data()
        configured_db_path = read_nested(data, "docs.serverDbPath", "")
        if configured_db_path:
            return pathlib.Path(configured_db_path)

        docs_local_root = read_nested(data, "docs.localRoot", "")
        if docs_local_root:
            return pathlib.Path(docs_local_root) / "docs_servers.sqlite"
        return ROOT / ".docs_servers.sqlite"

    def _read_config_data(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as file_handle:
                return json.load(file_handle)
        except Exception:
            return {}

    def _init_docs_config_db(self):
        db_path = self._docs_config_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    ip TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password_hint TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backup_paths (
                    id INTEGER PRIMARY KEY,
                    server_id INTEGER NOT NULL,
                    local_path TEXT NOT NULL,
                    remote_path TEXT NOT NULL,
                    last_synced TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(server_id) REFERENCES servers(id) ON DELETE CASCADE
                )
                """
            )
        self.docs_db_path = db_path
        return db_path

    def _load_docs_servers_from_db(self):
        db_path = self._docs_config_db_path()
        if not db_path.exists():
            return False

        servers = []
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            for row in connection.execute(
                "SELECT id, name, ip, username, password_hint FROM servers ORDER BY id"
            ):
                paths = []
                for path_row in connection.execute(
                    """
                    SELECT local_path, remote_path, last_synced
                    FROM backup_paths
                    WHERE server_id = ?
                    ORDER BY sort_order, id
                    """,
                    (row["id"],),
                ):
                    paths.append(
                        {
                            "localPath": path_row["local_path"],
                            "remotePath": path_row["remote_path"],
                            "lastSynced": path_row["last_synced"],
                        }
                    )
                servers.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "ip": row["ip"],
                        "username": row["username"],
                        "passwordHint": row["password_hint"],
                        "paths": paths,
                    }
                )
        self.docs_servers = servers
        self.docs_db_path = db_path
        return True

    def _save_docs_servers_to_db(self):
        db_path = self._init_docs_config_db()
        with sqlite3.connect(db_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("DELETE FROM backup_paths")
            connection.execute("DELETE FROM servers")
            for server in self.docs_servers:
                cursor = connection.execute(
                    """
                    INSERT INTO servers (name, ip, username, password_hint, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        server.get("name", ""),
                        server.get("ip", ""),
                        server.get("username", ""),
                        server.get("passwordHint", ""),
                    ),
                )
                server["id"] = cursor.lastrowid
                for index, path_entry in enumerate(server.get("paths", []), start=1):
                    connection.execute(
                        """
                        INSERT INTO backup_paths (
                            server_id, local_path, remote_path, last_synced, sort_order
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            server["id"],
                            path_entry.get("localPath", ""),
                            path_entry.get("remotePath", ""),
                            path_entry.get("lastSynced", ""),
                            index,
                        ),
                    )

    def refresh_docs_servers(self):
        self.docs_table.setRowCount(0)

        for server in self.docs_servers:
            row = self.docs_table.rowCount()
            self.docs_table.insertRow(row)
            self.docs_table.setItem(row, 0, QTableWidgetItem(server["name"]))
            self.docs_table.setItem(row, 1, QTableWidgetItem(server["ip"]))

            action_button = QToolButton()
            action_button.setIcon(
                QIcon.fromTheme(
                    "preferences-system",
                    QApplication.style().standardIcon(QStyle.SP_FileDialogDetailedView),
                )
            )
            action_button.setToolTip("Configure server")
            action_button.setAccessibleName("Configure {}".format(server["name"]))
            action_button.clicked.connect(
                lambda checked=False, server=server: self.open_server_configuration(server)
            )
            self.docs_table.setCellWidget(row, 2, action_button)

    def _update_delete_server_button(self):
        self.delete_server_button.setEnabled(
            self.docs_table.currentRow() >= 0
        )

    def delete_selected_server(self):
        row = self.docs_table.currentRow()
        if row < 0 or row >= len(self.docs_servers):
            return

        server = self.docs_servers[row]
        answer = QMessageBox.warning(
            self,
            "Delete server",
            "Warning: server {} ({}) and its saved configuration will be deleted. Continue?".format(
                server["name"],
                server["ip"],
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.docs_server_passwords.pop(id(server), None)
        del self.docs_servers[row]
        self.refresh_docs_servers()
        self.save_config()
        self.status_label.setText("Server {} deleted.".format(server["name"]))

    def add_docs_server(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add server")
        form = QFormLayout(dialog)

        name_edit = QLineEdit()
        ip_edit = QLineEdit()
        username_edit = QLineEdit()
        password_edit = NoClipboardLineEdit()
        confirm_password_edit = NoClipboardLineEdit()
        password_edit.setEchoMode(QLineEdit.Password)
        confirm_password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Name", name_edit)
        form.addRow("IP", ip_edit)
        form.addRow("Username", username_edit)
        form.addRow("Password", password_edit)
        form.addRow("Confirm password", confirm_password_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        name = name_edit.text().strip()
        ip = ip_edit.text().strip()
        username = username_edit.text().strip()
        password = password_edit.text()
        confirm_password = confirm_password_edit.text()
        if (
            not name
            or not ip
            or not username
            or not password
            or not confirm_password
        ):
            QMessageBox.warning(
                self,
                "Add server",
                "Name, IP, username, password and confirm password are required.",
            )
            return
        if password != confirm_password:
            QMessageBox.warning(
                self,
                "Add server",
                "Password and confirm password do not match.",
            )
            return

        self.status_label.setText("Testing access to {}...".format(ip))
        access_result = self._test_server_access(username, ip, password)
        if access_result is False:
            return

        server = {
            "name": name,
            "ip": ip,
            "username": username,
            "passwordHint": "*" * min(len(password), 12),
            "paths": [],
        }
        self.docs_servers.append(server)
        self.docs_server_passwords[id(server)] = password
        self.refresh_docs_servers()
        self.save_config()
        if access_result is True:
            self.status_label.setText(
                "Server {} added and access verified.".format(name)
            )
        elif access_result == "reachable":
            self.status_label.setText(
                "Server {} added; SSH port reachable, credentials not tested.".format(
                    name
                )
            )
        else:
            self.status_label.setText(
                "Server {} added; access was not tested.".format(name)
            )

    def _test_server_access(self, username, ip, password, show_success_message=True):
        sshpass_path = shutil.which("sshpass")
        if not sshpass_path:
            try:
                with socket.create_connection((ip, 22), timeout=5):
                    return "reachable"
            except (OSError, socket.timeout):
                return None

        try:
            ssh_command = [
                sshpass_path,
                "-p",
                password,
                "ssh",
                "-o",
                "BatchMode=no",
                "-o",
                "PasswordAuthentication=yes",
                "-o",
                "PubkeyAuthentication=no",
                "-o",
                "KbdInteractiveAuthentication=no",
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "NumberOfPasswordPrompts=1",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "UserKnownHostsFile={}".format(
                    self._get_widget_value("ssh.knownHosts", "file")
                ),
                "{}@{}".format(username, ip),
                "true",
            ]
            result = subprocess.run(
                ssh_command,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode == 0:
                return True

            error_detail = (result.stderr or result.stdout or "Unknown SSH error").strip()
            if show_success_message:
                QMessageBox.warning(
                    self,
                    "Server access failed",
                    "Could not access {}@{}. Check the username, IP, password, and SSH host key.\n\n{}".format(
                        username,
                        ip,
                        error_detail,
                    ),
                )
            return False
        except (OSError, subprocess.TimeoutExpired) as error:
            if show_success_message:
                QMessageBox.warning(
                    self,
                    "Server access failed",
                    "Could not test server access: {}".format(error),
                )
            return False

    def _run_server_ssh_command(self, username, ip, password, remote_command):
        sshpass_path = shutil.which("sshpass")
        if not sshpass_path:
            return None, "sshpass is not installed."

        command = [
            sshpass_path,
            "-p",
            password,
            "ssh",
            "-o",
            "BatchMode=no",
            "-o",
            "PasswordAuthentication=yes",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "UserKnownHostsFile={}".format(
                self._get_widget_value("ssh.knownHosts", "file")
            ),
            "{}@{}".format(username, ip),
            remote_command,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)

        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "SSH command failed.").strip()

    def _test_backup_path_access(self, username, ip, password, local_path, remote_path):
        if not local_path or not remote_path:
            return "Path test skipped: local and remote path are required."

        try:
            pathlib.Path(local_path).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=local_path):
                pass
        except Exception as error:
            return "Local path failed: {}".format(error)

        remote_test = "test -d {0} && test -r {0}".format(shlex.quote(remote_path))
        remote_ok, remote_error = self._run_server_ssh_command(
            username, ip, password, remote_test
        )
        if remote_ok is None:
            return "Remote path not tested: {}".format(remote_error)
        if not remote_ok:
            return "Remote path failed: {}".format(remote_error)

        sshpass_path = shutil.which("sshpass")
        if not sshpass_path:
            return "Local path: OK; remote login not tested."

        rsync_path = shutil.which("rsync")
        if not rsync_path:
            return "Remote path: OK; rsync dry-run skipped because rsync is missing."

        remote_shell = " ".join(
            shlex.quote(part)
            for part in [
                "ssh",
                "-o",
                "BatchMode=no",
                "-o",
                "PasswordAuthentication=yes",
                "-o",
                "PubkeyAuthentication=no",
                "-o",
                "KbdInteractiveAuthentication=no",
                "-o",
                "PreferredAuthentications=password",
                "-o",
                "NumberOfPasswordPrompts=1",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "UserKnownHostsFile={}".format(
                    self._get_widget_value("ssh.knownHosts", "file")
                ),
            ]
        )
        command = [
            sshpass_path,
            "-p",
            password,
            rsync_path,
            "-an",
            "-e",
            remote_shell,
            "{}@{}:{}/".format(username, ip, remote_path.rstrip("/")),
            str(pathlib.Path(local_path)) + "/",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return "Rsync dry-run failed: {}".format(error)

        if result.returncode == 0:
            return "Local path: OK; remote path: OK; rsync dry-run: OK."
        return "Rsync dry-run failed: {}".format(
            (result.stderr or result.stdout or "Unknown rsync error.").strip()
        )

    def _select_local_path(self, target_edit):
        current = target_edit.text().strip() or read_nested(
            self._read_config_data(), "docs.localRoot", str(ROOT)
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select local backup path",
            current,
        )
        if selected:
            target_edit.setText(selected)

    def _format_docs_last_synced(self, value):
        if not value:
            return ""
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone()
            return "{}/{}/{} {:02d}:{:02d}".format(
                parsed.day,
                parsed.month,
                str(parsed.year)[-2:],
                parsed.hour,
                parsed.minute,
            )
        except ValueError:
            return str(value)

    def _docs_ssh_config(self):
        return {
            "key": self._get_widget_value("ssh.key", "file"),
            "knownHosts": self._get_widget_value("ssh.knownHosts", "file"),
            "connectTimeoutSeconds": self._get_widget_value(
                "ssh.connectTimeoutSeconds", "int"
            ),
            "identitiesOnly": self._get_widget_value("ssh.identitiesOnly", "bool"),
            "batchMode": self._get_widget_value("ssh.batchMode", "bool"),
            "strictHostKeyChecking": self._get_widget_value(
                "ssh.strictHostKeyChecking", "bool"
            ),
        }

    def _test_server_key_access(self, username, ip):
        ssh_config = self._docs_ssh_config()
        ssh_key = pathlib.Path(ssh_config["key"])
        if not ssh_key.exists():
            return False, (
                "SSH key does not exist: {}. Setup/copy the Docs SSH key first, "
                "or update SSH key path in SSH + LAN."
            ).format(ssh_key)

        command = [
            "ssh",
            *build_ssh_args(ssh_config),
            "{}@{}".format(username, ip),
            "true",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(15, int(ssh_config["connectTimeoutSeconds"]) + 5),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)

        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "SSH key login failed.").strip()

    def _test_backup_path_key_access(self, username, ip, local_path, remote_path):
        if not local_path or not remote_path:
            return "Path test skipped: local and remote path are required."

        try:
            pathlib.Path(local_path).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=local_path):
                pass
        except Exception as error:
            return "Local path failed: {}".format(error)

        ssh_config = self._docs_ssh_config()
        remote_test = "test -d {0} && test -r {0}".format(shlex.quote(remote_path))
        command = [
            "ssh",
            *build_ssh_args(ssh_config),
            "{}@{}".format(username, ip),
            remote_test,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(15, int(ssh_config["connectTimeoutSeconds"]) + 5),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return "Remote path failed: {}".format(error)

        if result.returncode != 0:
            return "Remote path failed: {}".format(
                (result.stderr or result.stdout or "Remote path is not readable.").strip()
            )

        rsync_path = shutil.which("rsync")
        if not rsync_path:
            return "Remote path: OK; rsync dry-run skipped because rsync is missing."

        command = [
            rsync_path,
            "-an",
            "-e",
            build_rsync_remote_shell(ssh_config),
            "{}@{}:{}/".format(username, ip, remote_path.rstrip("/")),
            str(pathlib.Path(local_path)) + "/",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return "Rsync dry-run failed: {}".format(error)

        if result.returncode == 0:
            return "Local path: OK; remote path: OK; rsync dry-run: OK."
        return "Rsync dry-run failed: {}".format(
            (result.stderr or result.stdout or "Unknown rsync error.").strip()
        )

    def open_server_configuration(self, server):
        dialog = QDialog(self)
        dialog.setWindowTitle("Server Backup Configuration - Docs")
        dialog.resize(900, 560)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        name_edit = QLineEdit(server.get("name", ""))
        ip_edit = QLineEdit(server.get("ip", ""))
        username_edit = QLineEdit(server.get("username", ""))

        form.addRow("Name", name_edit)
        form.addRow("IP", ip_edit)
        form.addRow("Username", username_edit)
        layout.addLayout(form)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        path_table = DocsPathTableWidget()
        path_table.setSelectionBehavior(QTableWidget.SelectRows)
        path_table.setSelectionMode(QTableWidget.SingleSelection)
        path_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        layout.addWidget(path_table, 1)

        def add_path_row(path_entry=None):
            path_entry = path_entry or {}
            row = path_table.rowCount()
            path_table.insertRow(row)
            number_item = QTableWidgetItem(str(row + 1))
            number_item.setFlags(number_item.flags() & ~Qt.ItemIsEditable)
            path_table.setItem(row, 0, number_item)
            path_table.setItem(
                row, 1, QTableWidgetItem(path_entry.get("localPath", ""))
            )
            path_table.setItem(
                row, 2, QTableWidgetItem(path_entry.get("remotePath", ""))
            )
            last_synced = path_entry.get("lastSynced", "")
            last_synced_item = QTableWidgetItem(
                self._format_docs_last_synced(last_synced)
            )
            last_synced_item.setData(Qt.UserRole, last_synced)
            path_table.setItem(row, 3, last_synced_item)
            run_button = QToolButton()
            run_button.setIcon(
                QApplication.style().standardIcon(QStyle.SP_MediaPlay)
            )
            run_button.setToolTip("Run backup for this path")
            run_button.setAccessibleName("Run backup for path {}".format(row + 1))
            run_button.clicked.connect(
                lambda checked=False, button=run_button: run_path_backup(button)
            )
            path_table.setCellWidget(row, 4, run_button)
            QTimer.singleShot(0, path_table._apply_column_ratio)

        def refresh_path_table_from_server():
            for current_server in self.docs_servers:
                if (
                    current_server.get("name") == server.get("name")
                    and current_server.get("ip") == server.get("ip")
                ):
                    server["paths"] = current_server.get("paths", [])
                    break
            path_table.setRowCount(0)
            for path_entry in server.get("paths", []):
                add_path_row(path_entry)
            update_delete_path_button()

        def renumber_path_rows():
            for row in range(path_table.rowCount()):
                item = path_table.item(row, 0)
                if item:
                    item.setText(str(row + 1))

        def update_delete_path_button():
            delete_path_button.setEnabled(path_table.currentRow() >= 0)

        def save_dialog_values():
            server["name"] = name_edit.text().strip()
            server["ip"] = ip_edit.text().strip()
            server["username"] = username_edit.text().strip()
            server["paths"] = collect_paths()
            self.refresh_docs_servers()
            return self.save_config()

        def run_path_backup(button):
            row = -1
            for index in range(path_table.rowCount()):
                if path_table.cellWidget(index, 4) is button:
                    row = index
                    break
            if row < 0 or row >= path_table.rowCount():
                return
            path_table.selectRow(row)
            if not save_dialog_values():
                return
            self.status_label.setText(
                "Starting docs backup for path {}...".format(row + 1)
            )
            self.run_docs_backup(
                {
                    "OFFLINE_BACKUP_DOCS_SERVER_NAME": server["name"],
                    "OFFLINE_BACKUP_DOCS_SERVER_IP": server["ip"],
                    "OFFLINE_BACKUP_DOCS_PATH_INDEX": str(row + 1),
                }
            )

        def run_all_path_backups():
            if path_table.rowCount() <= 0:
                QMessageBox.information(
                    dialog,
                    "Run Docs Backup",
                    "No backup paths are configured for this server.",
                )
                return
            if not save_dialog_values():
                return
            self.status_label.setText(
                "Starting docs backup for all paths on {}...".format(
                    server["name"]
                )
            )
            self.run_docs_backup(
                {
                    "OFFLINE_BACKUP_DOCS_SERVER_NAME": server["name"],
                    "OFFLINE_BACKUP_DOCS_SERVER_IP": server["ip"],
                }
            )

        def delete_selected_path():
            row = path_table.currentRow()
            if row < 0:
                return
            answer = QMessageBox.warning(
                dialog,
                "Delete Backup Path",
                "Delete selected backup path?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            path_table.removeRow(row)
            renumber_path_rows()
            update_delete_path_button()

        def open_add_path_dialog():
            path_dialog = QDialog(dialog)
            path_dialog.setWindowTitle("Add Backup Path")
            path_dialog.resize(430, 150)
            path_layout = QVBoxLayout(path_dialog)
            path_form = QFormLayout()
            path_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            path_form.setHorizontalSpacing(12)
            path_form.setVerticalSpacing(8)
            path_layout.addLayout(path_form)

            local_path_edit = QLineEdit()
            remote_path_edit = QLineEdit()

            local_row = QWidget()
            local_layout = QHBoxLayout(local_row)
            local_layout.setContentsMargins(0, 0, 0, 0)
            local_layout.setSpacing(6)
            local_layout.addWidget(local_path_edit, 1)
            browse_local_button = QToolButton()
            browse_local_button.setIcon(
                QApplication.style().standardIcon(QStyle.SP_DirOpenIcon)
            )
            browse_local_button.setToolTip("Browse local path")
            browse_local_button.setAccessibleName("Browse local path")
            browse_local_button.clicked.connect(
                lambda: self._select_local_path(local_path_edit)
            )
            local_layout.addWidget(browse_local_button)

            path_form.addRow("Local Path", local_row)
            path_form.addRow("Remote Path", remote_path_edit)

            buttons = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            )
            buttons.accepted.connect(path_dialog.accept)
            buttons.rejected.connect(path_dialog.reject)
            button_row = QHBoxLayout()
            button_row.addWidget(buttons)
            button_row.addStretch(1)
            path_layout.addLayout(button_row)

            if path_dialog.exec() != QDialog.Accepted:
                return

            local_path = local_path_edit.text().strip()
            remote_path = remote_path_edit.text().strip()
            if not local_path or not remote_path:
                QMessageBox.warning(
                    dialog,
                    "Add Backup Path",
                    "Local Path and Remote Path are required.",
                )
                return

            add_path_row(
                {
                    "localPath": local_path,
                    "remotePath": remote_path,
                    "lastSynced": "",
                }
            )

        for path_entry in server.get("paths", []):
            add_path_row(path_entry)

        self._refresh_open_docs_config = refresh_path_table_from_server
        dialog.finished.connect(
            lambda _result: setattr(self, "_refresh_open_docs_config", None)
        )

        path_actions = QHBoxLayout()
        add_path_button = QToolButton()
        add_path_button.setIcon(
            QApplication.style().standardIcon(QStyle.SP_FileDialogNewFolder)
        )
        add_path_button.setToolTip("Add backup path")
        add_path_button.clicked.connect(open_add_path_dialog)
        path_actions.addWidget(add_path_button)

        delete_path_button = QToolButton()
        delete_path_button.setIcon(
            QApplication.style().standardIcon(QStyle.SP_TrashIcon)
        )
        delete_path_button.setToolTip("Delete selected backup path")
        delete_path_button.setAccessibleName("Delete selected backup path")
        delete_path_button.setEnabled(False)
        delete_path_button.clicked.connect(delete_selected_path)
        path_actions.addWidget(delete_path_button)

        test_button = QPushButton("Test Connection")
        path_actions.addWidget(test_button)
        run_all_button = QPushButton("Run All")
        run_all_button.setToolTip("Run backup for all paths on this server")
        run_all_button.clicked.connect(run_all_path_backups)
        path_actions.addWidget(run_all_button)
        test_result_label = QLabel("")
        test_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_actions.addWidget(test_result_label, 1)
        layout.addLayout(path_actions)
        path_table.itemSelectionChanged.connect(update_delete_path_button)

        def collect_paths():
            paths = []
            for row in range(path_table.rowCount()):
                local_item = path_table.item(row, 1)
                remote_item = path_table.item(row, 2)
                last_synced_item = path_table.item(row, 3)
                local_path = local_item.text().strip() if local_item else ""
                remote_path = remote_item.text().strip() if remote_item else ""
                last_synced = (
                    last_synced_item.data(Qt.UserRole)
                    if last_synced_item and last_synced_item.data(Qt.UserRole)
                    else last_synced_item.text().strip()
                    if last_synced_item
                    else ""
                )
                if local_path or remote_path:
                    paths.append(
                        {
                            "localPath": local_path,
                            "remotePath": remote_path,
                            "lastSynced": last_synced,
                        }
                    )
            return paths

        def test_connection():
            test_result_label.setText("Testing...")
            QApplication.processEvents()
            username = username_edit.text().strip()
            ip = ip_edit.text().strip()
            result, detail = self._test_server_key_access(username, ip)
            messages = []
            if result is True:
                messages.append("SSH key login: OK")
            else:
                messages.append("SSH key login: failed - {}".format(detail))

            if result is True and path_table.rowCount() > 0:
                for row, path_entry in enumerate(collect_paths(), start=1):
                    messages.append(
                        "Path {}: {}".format(
                            row,
                            self._test_backup_path_key_access(
                                username,
                                ip,
                                path_entry.get("localPath", ""),
                                path_entry.get("remotePath", ""),
                            ),
                        )
                    )

            test_result_label.setText("\n".join(messages))

        test_button.clicked.connect(test_connection)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        if save_dialog_values():
            self.status_label.setText(
                "Server configuration saved for {}.".format(server["name"])
            )

    def _build_dashboard(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        status_form = QFormLayout()

        self.backup_status_label = QLabel("Idle")
        self.lan_status_label = QLabel("Checking...")
        self.current_step_label = QLabel("-")

        status_form.addRow("Backup Status", self.backup_status_label)
        status_form.addRow("LAN Status", self.lan_status_label)
        status_form.addRow("Current Step", self.current_step_label)

        layout.addLayout(status_form)

        lan_actions = QHBoxLayout()

        lan_up_button = QPushButton("LAN UP")
        lan_up_button.clicked.connect(self.lan_up)

        lan_down_button = QPushButton("LAN DOWN")
        lan_down_button.clicked.connect(self.lan_down)

        refresh_button = QPushButton("Refresh Activity")
        refresh_button.clicked.connect(self.refresh_activity)

        lan_actions.addWidget(lan_up_button)
        lan_actions.addWidget(lan_down_button)
        lan_actions.addWidget(refresh_button)
        lan_actions.addStretch(1)

        layout.addLayout(lan_actions)

        layout.addWidget(QLabel("Activity Log"))

        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setAcceptRichText(True)
        # dark background and green text (monospace)
        self.activity_log.setStyleSheet(
            "background: #000; color: #0f0; font-family: 'Courier New', monospace;"
        )
        layout.addWidget(self.activity_log, 1)

        self.tabs.addTab(tab, "Dashboard")

    def _make_field(self, key, kind):
        if kind == "bool":
            widget = QCheckBox()
            self.widgets[key] = {"widget": widget, "kind": kind}
            return widget

        if kind == "int":
            widget = QLineEdit()
            self.widgets[key] = {"widget": widget, "kind": kind}
            return widget

        if kind == "lines":
            widget = QTextEdit()
            widget.setFixedHeight(86)
            self.widgets[key] = {"widget": widget, "kind": kind}
            return widget

        line_edit = QLineEdit()

        if kind in {"file", "dir"}:
            browse_button = QPushButton("Browse")
            browse_button.clicked.connect(
                lambda: self.browse_value(key, kind)
            )

            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)

            layout.addWidget(line_edit, 1)
            layout.addWidget(browse_button)

            self.widgets[key] = {
                "widget": line_edit,
                "kind": kind,
            }

            return row

        self.widgets[key] = {
            "widget": line_edit,
            "kind": kind,
        }

        return line_edit

    def browse_value(self, key, kind):
        current = str(self._get_widget_value(key) or ROOT)

        if kind == "dir":
            selected = QFileDialog.getExistingDirectory(
                self,
                "Select directory",
                current,
            )
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select file",
                str(pathlib.Path(current).parent),
                "All files (*)",
            )

        if selected:
            self._set_widget_value(key, selected)

    def load_config(self):
        try:
            with open(
                self.config_path,
                "r",
                encoding="utf-8",
            ) as file_handle:
                data = json.load(file_handle)

            if isinstance(read_nested(data, "local.logFile"), str):
                data["local"]["logFile"] = resolve_writable_log_path(
                    read_nested(data, "local.logFile"),
                    pathlib.Path.home() / ".local" / "share" / "offline-backup",
                )

            for _, fields in FIELD_GROUPS:
                for _, key, _ in fields:
                    self._set_widget_value(
                        key,
                        read_nested(data, key, []),
                    )

            loaded_from_db = self._load_docs_servers_from_db()
            if not loaded_from_db:
                configured_servers = read_nested(data, "docs.servers", [])
                if isinstance(configured_servers, list):
                    self.docs_servers = [
                        {
                            "name": server.get("name", ""),
                            "ip": server.get("ip", ""),
                            "username": server.get("username", ""),
                            "passwordHint": server.get("passwordHint", ""),
                            "paths": server.get("paths", []),
                        }
                        for server in configured_servers
                        if isinstance(server, dict)
                        and server.get("name")
                        and server.get("ip")
                    ]
            self.refresh_docs_servers()

            self.status_label.setText(
                "Loaded {}".format(self.config_path)
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Load failed",
                str(error),
            )

    def save_config(self):
        try:
            try:
                with open(
                    self.config_path,
                    "r",
                    encoding="utf-8",
                ) as file_handle:
                    data = json.load(file_handle)
            except Exception:
                data = {}

            for _, fields in FIELD_GROUPS:
                for _, key, kind in fields:
                    write_nested(
                        data,
                        key,
                        self._get_widget_value(key, kind),
                    )

            self._save_docs_servers_to_db()
            write_nested(data, "docs.servers", self.docs_servers)
            write_nested(data, "docs.serverDbPath", str(self.docs_db_path))

            self.config_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with open(
                self.config_path,
                "w",
                encoding="utf-8",
            ) as file_handle:
                json.dump(data, file_handle, indent=4)
                file_handle.write("\n")

            self.status_label.setText(
                "Saved {}".format(self.config_path)
            )

            return True

        except Exception as error:
            QMessageBox.critical(
                self,
                "Save failed",
                str(error),
            )
            return False

    def run_backup(self):
        self._activity_manual_view = False
        if (
            self.process
            and self.process.state() != QProcess.NotRunning
        ):
            QMessageBox.information(
                self,
                "Backup running",
                "Backup is already running.",
            )
            return

        if not self.save_config():
            return

        # Start reading from the beginning of the current run's log output.
        self.log_position = 0
        self._log_lines.clear()
        self._last_activity_line = None
        self.activity_log.clear()
        self.status_label.setText("Starting backup process...")
        self.backup_status_label.setText("Running")
        self.current_step_label.setText("Starting backup...")

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(ROOT))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("OFFLINE_BACKUP_MIRROR_CONSOLE", "1")
        self.process.setProcessEnvironment(environment)

        self.process.readyReadStandardOutput.connect(
            self._handle_process_output
        )
        self.process.readyReadStandardError.connect(
            self._handle_process_output
        )
        self.process.errorOccurred.connect(
            self._backup_process_error
        )
        self.process.finished.connect(
            self._backup_finished
        )

        self.process.start(
            "/bin/bash",
            [str(BACKUP_SCRIPT), "--config", str(self.config_path)],
        )

        self.status_label.setText("Running backup...")
        self.refresh_log()
        QTimer.singleShot(100, self.refresh_log)

    def run_docs_backup(self, extra_environment=None):
        self._activity_manual_view = False
        if (
            self.process
            and self.process.state() != QProcess.NotRunning
        ):
            QMessageBox.information(
                self,
                "Process running",
                "Another backup process is already running.",
            )
            return

        if not self.save_config():
            return

        self.activity_log.clear()
        self._log_lines.clear()
        self._last_activity_line = None
        self.status_label.setText("Starting docs backup...")
        self.current_step_label.setText("Starting docs backup...")

        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(ROOT))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("OFFLINE_BACKUP_MIRROR_CONSOLE", "1")
        for key, value in (extra_environment or {}).items():
            environment.insert(key, value)
        self.process.setProcessEnvironment(environment)
        self.process.readyReadStandardOutput.connect(self._handle_process_output)
        self.process.readyReadStandardError.connect(self._handle_process_output)
        self.process.errorOccurred.connect(self._backup_process_error)
        self.process.finished.connect(self._docs_backup_finished)
        self.process.start(
            sys.executable,
            [str(DOCS_BACKUP_SCRIPT), "--config", str(self.config_path)],
        )

    def _docs_backup_finished(self, exit_code, exit_status=None):
        if exit_code == 0:
            self._load_docs_servers_from_db()
            self.refresh_docs_servers()
            if self._refresh_open_docs_config:
                self._refresh_open_docs_config()
            self.status_label.setText("Docs backup completed")
            self.current_step_label.setText("Docs backup completed")
        else:
            self.status_label.setText(
                "Docs backup failed with exit code {}".format(exit_code)
            )
            self.current_step_label.setText("Docs backup failed")

        QTimer.singleShot(100, self.refresh_dashboard)

    def _backup_process_error(self, error):
        if not self.process:
            return

        message = self.process.errorString() or "Could not start backup process."
        self.backup_status_label.setText("Failed")
        self.current_step_label.setText("Process startup failed")
        self.status_label.setText(message)
        self._append_log_line("ERROR: {}".format(message), "error")

    def stop_backup(self):
        if (
            self.process
            and self.process.state() != QProcess.NotRunning
        ):
            self.process.terminate()

            self.backup_status_label.setText("Stopping")
            self.status_label.setText("Stopping backup...")

    def lan_up(self):
        interface = self._get_widget_value(
            "lan.interface",
            "text",
        ).strip()

        if not interface:
            QMessageBox.warning(
                self,
                "LAN",
                "LAN interface is empty.",
            )
            return

        result = subprocess.run(
            ["/usr/bin/pkexec", "/usr/sbin/ip", "link", "set", "dev", interface, "up"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            result = subprocess.run(
                ["/usr/bin/pkexec", "/usr/bin/networkctl", "reconfigure", interface],
                capture_output=True,
                text=True,
            )

        if result.returncode != 0:
            QMessageBox.warning(
                self,
                "LAN UP failed",
                result.stderr or "Could not enable LAN.",
            )
        else:
            self.status_label.setText(
                "LAN interface enabled."
            )
            self._append_log_line(
                "LAN interface enabled: {}".format(interface),
                "info",
            )

        QTimer.singleShot(
            1500,
            self.refresh_dashboard,
        )

    def lan_down(self):
        interface = self._get_widget_value(
            "lan.interface",
            "text",
        ).strip()

        if not interface:
            QMessageBox.warning(
                self,
                "LAN",
                "LAN interface is empty.",
            )
            return

        result = subprocess.run(
            ["/usr/bin/pkexec", "/usr/sbin/ip", "link", "set", "dev", interface, "down"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            QMessageBox.warning(
                self,
                "LAN DOWN failed",
                result.stderr or "Could not disable LAN.",
            )
        else:
            self.status_label.setText(
                "LAN interface disabled."
            )
            self._append_log_line(
                "LAN interface disabled: {}".format(interface),
                "info",
            )

        QTimer.singleShot(
            700,
            self.refresh_dashboard,
        )

    def refresh_dashboard(self):
        self.refresh_lan_status()
        if not self._activity_manual_view:
            self.refresh_log()

    def refresh_activity(self):
        self._activity_manual_view = True
        self.log_position = 0
        self.log_source_path = None
        self.activity_log.clear()
        self._log_lines.clear()
        self._last_activity_line = None
        self._refresh_activity_from_all_logs()
        self.status_label.setText("Activity log refreshed.")

    def _refresh_activity_from_all_logs(self):
        readable = []
        unreadable = []
        for path in self._log_file_candidates():
            if not path.exists():
                continue
            if not os.access(path, os.R_OK):
                try:
                    unreadable.append((path.stat().st_mtime, path))
                except OSError:
                    pass
                continue
            try:
                readable.append((path.stat().st_mtime, path))
            except OSError:
                continue

        if any(path == SYSTEM_LOG for _, path in unreadable):
            self._show_log_permission_warning(SYSTEM_LOG)

        if readable:
            candidates = []
            for mtime, path in readable:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        lines = handle.readlines()
                except OSError:
                    continue
                candidates.append((self._latest_log_timestamp(lines, mtime), path, lines))

            if not candidates:
                self.refresh_log()
                return

            _, path, lines = max(candidates, key=lambda item: item[0])

            recent_lines = self._latest_run_lines(lines)
            self._append_activity_text("".join(recent_lines))

        if unreadable:
            newest_unreadable = max(unreadable, key=lambda item: item[0])
            self._show_log_permission_warning(newest_unreadable[1])

        if not readable:
            self.refresh_log()

    def refresh_lan_status(self):
        try:
            interface = self._get_widget_value(
                "lan.interface",
                "text",
            ).strip()

            if not interface:
                self.lan_status_label.setText("Unknown")
                return

            result = subprocess.run(
                [
                    "/usr/sbin/ip",
                    "-4",
                    "-br",
                    "addr",
                    "show",
                    interface,
                ],
                capture_output=True,
                text=True,
            )

            output = result.stdout.strip()

            if " UP " in " {} ".format(output):
                self.lan_status_label.setText(
                    "UP - {}".format(output)
                )
            else:
                self.lan_status_label.setText("DOWN")

        except Exception as error:
            self.lan_status_label.setText(
                "Unknown ({})".format(error)
            )

    def refresh_log(self):
        try:
            log_file = self._get_log_file()

            if not log_file:
                return

            path = pathlib.Path(log_file)

            if self.log_source_path != str(path):
                self.log_source_path = str(path)
                self.log_position = 0
                self.activity_log.clear()
                self._log_lines.clear()
                self._last_activity_line = None

            if not path.exists():
                return

            size = path.stat().st_size

            if size < self.log_position:
                self.log_position = 0
                self.activity_log.clear()
                self._log_lines.clear()
                self._last_activity_line = None

            if self.log_position == 0:
                with open(
                    path,
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as handle:
                    lines = handle.readlines()

                recent_lines = self._latest_run_lines(lines)
                self.log_position = size
                self._append_activity_text("".join(recent_lines))

                self._refresh_worm_inventory_summary(path)
                return

            with open(
                path,
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                handle.seek(self.log_position)
                new_text = handle.read()
                self.log_position = handle.tell()

            if not new_text:
                return

            self._append_activity_text(new_text)

            self._refresh_worm_inventory_summary(path)

        except Exception as error:
            self.status_label.setText(
                "Activity log error: {}".format(error)
            )

    def _refresh_worm_inventory_summary(self, log_path=None):
        lines = self._build_worm_inventory_summary(log_path)
        if not lines:
            return

        signature = "\n".join(lines)
        if signature == self._last_inventory_signature:
            return

        self._last_inventory_signature = signature
        for line in lines:
            self._append_log_line(line)

    def _build_worm_inventory_summary(self, log_path=None):
        worm_root = self._get_widget_value("worm.root", "dir")
        if not worm_root:
            return []

        root = pathlib.Path(worm_root)
        if not root.exists():
            return []

        try:
            batches = sorted(
                child
                for child in root.iterdir()
                if child.is_dir()
            )
        except OSError:
            return []

        if not batches:
            return []

        newest = batches[-5:]
        batch_mtimes = []
        for batch in newest:
            try:
                batch_mtimes.append(batch.stat().st_mtime)
            except OSError:
                pass

        if not batch_mtimes:
            return []

        newest_mtime = max(batch_mtimes)
        log_mtime = 0
        if log_path and pathlib.Path(log_path).exists():
            log_mtime = pathlib.Path(log_path).stat().st_mtime

        if log_mtime and newest_mtime <= log_mtime:
            return []

        lines = [
            "Current WORM inventory is newer than the log file:",
        ]

        for batch in newest:
            try:
                file_count = sum(1 for item in batch.rglob("*") if item.is_file())
                modified = batch.stat().st_mtime
            except OSError:
                file_count = "unknown"
                modified = newest_mtime

            modified_text = datetime.fromtimestamp(modified).astimezone().strftime(
                "%Y-%m-%d %H:%M:%S %z"
            )
            lines.append(
                "WORM batch: {} ({} files, updated {})".format(
                    batch.name,
                    file_count,
                    modified_text,
                )
            )

        return lines

    def _update_dashboard_from_log(self, text):
        for line in text.splitlines():
            stripped = line.strip()

            if stripped.startswith("Step:"):
                step = stripped.split(":", 1)[1].strip()
                self.current_step_label.setText(step)

            if "SUCCESS:" in stripped:
                self.backup_status_label.setText("Success")

            if stripped in (
                "Docs backup completed.",
                "Docs server backup completed.",
            ):
                self.backup_status_label.setText("Success")

            if (
                "ERROR:" in stripped
                or "FAILED" in stripped
            ):
                self.backup_status_label.setText("Failed")

            if "Pull backup finished: nothing to transfer." in stripped:
                self.backup_status_label.setText("No Files")

    def _append_log_line(self, text, level=None):
        # determine level if not provided
        lvl = level
        s = text.strip()
        self._update_dashboard_from_log(text)
        if not lvl:
            if 'ERROR' in s or 'FAILED' in s or 'Failed' in s or 'ERROR:' in s:
                lvl = 'error'
            elif 'WARN' in s or 'Disk space low' in s or 'warning' in s:
                lvl = 'warn'
            else:
                lvl = 'info'

        color = '#9fff9f' if lvl == 'info' else ('#ffd86b' if lvl == 'warn' else '#ff6b6b')
        # keep plain message for dashboard parsing
        self._log_lines.append((text, lvl))
        # rebuild html
        parts = []
        for t, l in self._log_lines:
            c = '#9fff9f' if l == 'info' else ('#ffd86b' if l == 'warn' else '#ff6b6b')
            parts.append(f"<span style='color:{c};white-space:pre-wrap;'>{self._escape_html(t)}</span>")

        html = '<br>'.join(parts)
        self.activity_log.setHtml(html)
        # update status label with last line
        if text:
            self.status_label.setText(text.strip())

    def _is_summary_line(self, text):
        stripped = text.strip()
        if not stripped:
            return True

        # rsync progress and per-file rows belong in the Full Backup Log.
        if re.match(r"^\d+(?:\.\d+)?[KMGTP]?B?\s+\d+%", stripped):
            return False

        if re.match(r"^\d+\s+\S", stripped):
            return False

        noisy_prefixes = (
            "** WARNING:",
            "** This session",
            "** The server",
            "Number of ",
            "Total file size:",
            "Total transferred file size:",
            "Literal data:",
            "Matched data:",
            "File list ",
            "rsync ",
            "rsync:",
            "Timeout, server ",
            "sent ",
            "total size is ",
            "UWORM file:",
            "DONE file:",
            "WARNING: Latest log exists but cannot be read:",
        )
        if stripped.startswith(noisy_prefixes):
            return False

        if (
            stripped.startswith("ERROR: Docs backup failed: (")
            or stripped.startswith("ERROR detail: rsync ")
        ):
            return False

        return True

    def _append_activity_text(self, text, level=None):
        for raw_line in text.replace("\r", "\n").splitlines():
            line = raw_line.rstrip("\n")
            if not self._is_summary_line(line):
                continue
            if line == self._last_activity_line:
                continue
            self._last_activity_line = line
            self._append_log_line(line, level)

    def _latest_run_lines(self, lines):
        offline_start = None
        docs_start = None
        for index in range(len(lines) - 1, -1, -1):
            if offline_start is None and "Pull backup started:" in lines[index]:
                offline_start = max(index - 1, 0)
            if docs_start is None and (
                "Docs backup started:" in lines[index]
                or "Docs server backup started." in lines[index]
            ):
                docs_start = max(index - 1, 0)
            if offline_start is not None and docs_start is not None:
                break

        sections = []
        if docs_start is not None:
            sections.extend(self._compact_summary_lines(lines[docs_start:]))
        elif offline_start is not None:
            sections.extend(self._compact_summary_lines(lines[offline_start:]))

        latest = sections or lines
        if len(latest) > 300:
            return latest[-300:]
        return latest

    def _latest_log_timestamp(self, lines, fallback):
        timestamps = []
        for line in lines:
            match = re.search(
                r"(?:Pull backup started:|Docs backup started:)\s+(.+)$",
                line,
            )
            if not match:
                continue
            value = match.group(1).strip()
            for fmt in ("%Y-%m-%d %H:%M:%S %z", "%-d/%-m/%y %H:%M"):
                try:
                    timestamps.append(datetime.strptime(value, fmt).timestamp())
                    break
                except ValueError:
                    continue
        return max(timestamps, default=fallback)

    def _compact_summary_lines(self, lines):
        summary = [line for line in lines if self._is_summary_line(line)]
        if len(summary) <= 160:
            return summary
        return summary[:80] + ["...\n"] + summary[-79:]

    def _escape_html(self, text):
        return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))

    def _on_ws_message(self, message):
        try:
            import json
            obj = json.loads(message)
            if obj.get("_persisted"):
                return
            txt = obj.get('text') or obj.get('message') or str(obj)
            lvl = obj.get('level', 'info')
            self._append_activity_text(txt, lvl)
        except Exception:
            # fallback: append raw
            self._append_activity_text(message, None)

    def clear_activity_view(self):
        self._activity_manual_view = False
        self.activity_log.clear()
        self._log_lines.clear()
        self._last_activity_line = None
        self.status_label.setText("Activity view cleared.")

    def open_log_file(self):
        log_file = self._get_log_file()

        if not log_file:
            QMessageBox.information(
                self,
                "No log file",
                "local.logFile is empty.",
            )
            return

        path = pathlib.Path(log_file)

        if not path.exists():
            QMessageBox.information(
                self,
                "No log file",
                "The log file does not exist yet:\n{}".format(log_file),
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Full Backup Log - {}".format(log_file))
        dialog.resize(1000, 700)
        layout = QVBoxLayout(dialog)

        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setUndoRedoEnabled(False)
        viewer.setStyleSheet(
            "background: #000; color: #0f0; font-family: 'Courier New', monospace;"
        )
        layout.addWidget(viewer)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        try:
            handle = open(log_file, "r", encoding="utf-8", errors="replace")
        except Exception as error:
            QMessageBox.warning(self, "Open log failed", str(error))
            dialog.deleteLater()
            return

        state = {"finished": False}
        timer = QTimer(dialog)
        chunk_size = 64 * 1024

        def finish_loading():
            if state["finished"]:
                return
            state["finished"] = True
            timer.stop()
            try:
                inventory_lines = self._build_worm_inventory_summary(path)
                if inventory_lines:
                    viewer.appendPlainText(
                        "\n\n{}".format("\n".join(inventory_lines))
                    )
            finally:
                handle.close()
            self.status_label.setText("Full log loaded: {}".format(log_file))

        def load_chunk():
            if state["finished"]:
                return
            try:
                chunk = handle.read(chunk_size)
                if chunk:
                    viewer.insertPlainText(chunk)
                    viewer.ensureCursorVisible()
                    return
                finish_loading()
            except Exception as error:
                state["finished"] = True
                timer.stop()
                handle.close()
                dialog.reject()
                QMessageBox.warning(self, "Open log failed", str(error))

        def close_handle():
            if not state["finished"]:
                state["finished"] = True
                timer.stop()
                handle.close()

        dialog.finished.connect(close_handle)
        timer.timeout.connect(load_chunk)
        timer.start(0)
        self.status_label.setText("Loading full log: {}".format(log_file))
        dialog.exec()

    def _get_log_file(self):
        candidates = self._log_file_candidates()
        readable = []
        unreadable = []
        for path in candidates:
            try:
                if not path.exists():
                    continue
                mtime = path.stat().st_mtime
                if os.access(path, os.R_OK):
                    readable.append((mtime, path))
                else:
                    unreadable.append((mtime, path))
            except OSError:
                continue

        if readable:
            timestamped = []
            for mtime, path in readable:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        lines = handle.readlines()
                except OSError:
                    continue
                timestamped.append((self._latest_log_timestamp(lines, mtime), path))

            if timestamped:
                newest_readable = max(timestamped, key=lambda item: item[0])
                newest_readable_mtime = next(
                    (mtime for mtime, path in readable if path == newest_readable[1]),
                    newest_readable[0],
                )
            else:
                newest_readable = max(readable, key=lambda item: item[0])
                newest_readable_mtime = newest_readable[0]
            newest_unreadable = max(unreadable, key=lambda item: item[0], default=None)
            if newest_unreadable and newest_unreadable[0] > newest_readable_mtime:
                self._show_log_permission_warning(newest_unreadable[1])
            return str(newest_readable[1])

        if unreadable:
            self._show_log_permission_warning(max(unreadable, key=lambda item: item[0])[1])

        configured = self._get_widget_value("local.logFile", "file")
        return configured

    def _log_file_candidates(self):
        candidates = []
        configured = self._get_widget_value("local.logFile", "file")
        if configured:
            candidates.append(pathlib.Path(configured).expanduser())

        service_log = self._read_config_log_file(SYSTEM_CONFIG)
        if service_log:
            candidates.append(service_log)

        candidates.append(SYSTEM_LOG)

        seen = set()
        readable = []
        unreadable = []
        for path in candidates:
            path = pathlib.Path(path)
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            yield path

    def _read_config_log_file(self, config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return None

        log_file = read_nested(data, "local.logFile")
        if not log_file:
            return None
        return pathlib.Path(log_file).expanduser()

    def _show_log_permission_warning(self, path):
        message = "Latest log exists but cannot be read: {}".format(path)
        if message == self._last_log_permission_warning:
            return
        self._last_log_permission_warning = message
        self.status_label.setText(message)
        self._append_log_line("WARNING: {}".format(message), "warn")

    def _handle_process_output(self):
        if not self.process:
            return

        output = bytes(
            self.process.readAllStandardOutput()
        ).decode(errors="replace")

        error = bytes(
            self.process.readAllStandardError()
        ).decode(errors="replace")

        text = output + error

        if text.strip():
            self._append_activity_text(text)

    def _sync_log_position_to_end(self):
        log_file = self._get_log_file()
        if not log_file:
            return

        path = pathlib.Path(log_file)
        if not path.exists():
            return

        self.log_source_path = str(path)
        try:
            self.log_position = path.stat().st_size
        except OSError:
            pass

    def _backup_finished(
        self,
        exit_code,
        exit_status=None,
    ):
        # The orchestrator writes its final failure/success lines before exit.
        self.refresh_log()

        if exit_code == 0:
            self.backup_status_label.setText("Completed")
            self.status_label.setText("Backup completed")
        else:
            self.backup_status_label.setText("Failed")
            self.status_label.setText(
                "Backup failed with exit code {}".format(
                    exit_code
                )
            )

        QTimer.singleShot(
            100,
            self.refresh_dashboard,
        )

    def _get_widget_value(
        self,
        key,
        kind=None,
    ):
        item = self.widgets[key]
        widget = item["widget"]
        kind = kind or item["kind"]

        if kind == "bool":
            return widget.isChecked()

        if kind == "int":
            text = widget.text().strip()
            return int(text) if text else 0

        if kind == "lines":
            return [
                line.strip()
                for line
                in widget.toPlainText().splitlines()
                if line.strip()
            ]

        return widget.text()

    def _set_widget_value(
        self,
        key,
        value,
    ):
        item = self.widgets[key]
        widget = item["widget"]
        kind = item["kind"]

        if kind == "bool":
            widget.setChecked(bool(value))

        elif kind == "int":
            widget.setText(str(value or 0))

        elif kind == "lines":
            if isinstance(value, list):
                widget.setPlainText(
                    "\n".join(
                        str(item)
                        for item in value
                    )
                )
            else:
                widget.setPlainText(str(value))

        else:
            widget.setText(str(value))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Offline Backup")
    app.setApplicationDisplayName("Offline Backup")
    app.setDesktopFileName(APP_ID)
    if APP_ICON.exists():
        app.setWindowIcon(QIcon(str(APP_ICON)))

    window = BackupWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

import pathlib
import posixpath
import re
import shutil

from backup_lib.core.command_runner import CommandError
from backup_lib.core.time_utils import (
    epoch_seconds,
    format_batch_label,
    format_log_date,
    now,
)
from backup_lib.core.fs_utils import format_bytes
from backup_lib.services.command_checker import CommandChecker
from backup_lib.services.docs_backup import DocsBackup
from backup_lib.services.email_reporter import EmailReporter
from backup_lib.services.lan_service import LanService
from backup_lib.services.local_disk_service import LocalDiskService
from backup_lib.services.local_lock import LocalLock
from backup_lib.services.local_publisher import LocalPublisher
from backup_lib.services.remote_backup_service import RemoteBackupService
from backup_lib.services.rsync_service import RsyncService
from backup_lib.services.safety_guard import SafetyGuard
from backup_lib.services.worm_publisher import WormPublisher


class BackupOrchestrator:
    def __init__(self, config, config_path, logger, runner):
        self.config = config
        self.config_path = config_path
        self.logger = logger
        self.runner = runner
        self.current_step = "Initializing backup process"
        self.batch = ""
        self.requested_batch = ""

        self.command_checker = CommandChecker(config, logger)
        self.docs_backup = DocsBackup(config, runner, logger)
        self.lan = LanService(config, runner, logger)
        self.local_disk = LocalDiskService(config, runner, logger)
        self.local_lock = LocalLock(config["local"]["lockFile"], runner)
        self.local_publisher = LocalPublisher(config, logger)
        self.remote = RemoteBackupService(config, runner)
        self.rsync = RsyncService(config, runner)
        self.safety_guard = SafetyGuard(config, logger)
        self.worm_publisher = WormPublisher(config, runner, logger)
        self.email_reporter = EmailReporter(config, runner, logger)

    def run(self):
        start_epoch = epoch_seconds()
        self.write_header()
        self.logger.line("Config: {}".format(self.config_path))

        try:
            self.execute(start_epoch)
            return 0
        except Exception as error:
            exit_code = normalize_exit_code(error)
            self.handle_failure(error, exit_code, start_epoch)
            return exit_code
        finally:
            self.cleanup()

    def execute(self, start_epoch):
        self.set_step("Checking required commands")
        self.command_checker.verify()

        self.set_step("Enabling LAN connection")
        self.lan.enable()

        self.set_step("Verifying 4TB backup disk")
        self.local_disk.verify()

        self.set_step("Acquiring local backup lock")
        lock_acquired = self.local_lock.acquire()
        if not lock_acquired:
            self.logger.line("Another pull_backup.sh process is already running.")
            return

        self.requested_batch = format_batch_label(now())

        self.set_step("Freezing Developer In_Progress")
        prepare_result = self.remote.prepare_batch(self.requested_batch)

        if prepare_result == "NO_FILES":
            self.logger.line("No files found in Developer In_Progress.")
            self.log_storage_inventory()
            self.logger.line("Pull backup finished: nothing to transfer.")
            return

        if not prepare_result.startswith("BATCH:"):
            raise RuntimeError("Unexpected Developer response:\n{}".format(prepare_result))

        self.batch = prepare_result[len("BATCH:") :]

        remote_queue = posixpath.join(self.config["remote"]["queueRoot"], self.batch)
        remote_done = self.config["remote"]["doneRoot"]
        local_stage, local_old = self.local_publisher.prepare_batch_paths(self.batch)

        self.local_publisher.recover_previous_swap(local_old)

        self.logger.line("Processing batch: {}".format(self.batch))
        self.logger.line("Pulling files into hidden staging: {}".format(local_stage))

        self.set_step("Pulling files to hidden local staging")
        self.rsync.pull_queue_to_stage(remote_queue, local_stage)

        self.set_step("Verifying local staging checksum")
        local_diff = self.rsync.verify_remote_to_local(remote_queue, local_stage)
        if local_diff.strip():
            self.logger.line("ERROR: Local staging checksum verification failed.")
            self.logger.raw(local_diff)
            raise RuntimeError("Local staging checksum verification failed.")
        self.logger.line("Local staging checksum verification passed.")

        self.set_step("Running safety guard")
        self.safety_guard.verify(local_stage)

        self.set_step("Publishing latest local backup_temp")
        self.local_publisher.publish_latest(local_stage, local_old)

        self.set_step("Replacing Developer Done with latest only")
        self.remote.copy_queue_to_done(self.batch)

        self.set_step("Verifying Developer Done checksum")
        done_diff = self.rsync.verify_remote_to_local(remote_done, self.config["local"]["root"])
        if done_diff.strip():
            self.logger.line("ERROR: Developer Done checksum verification failed.")
            self.logger.raw(done_diff)
            self.logger.line("Remote transfer queue has been kept for recovery.")
            raise RuntimeError("Developer Done checksum verification failed.")
        self.logger.line("Developer Done checksum verification passed.")

        self.set_step("Publishing verified backup to WORM")
        self.logger.line("Publishing verified backup_temp to back_up_worm...")
        self.worm_publisher.publish(self.batch)
        self.logger.line("back_up_worm publish completed.")

        self.set_step("Clearing verified remote transfer queue")
        self.remote.clear_queue(self.batch)

        self.logger.line("==================================================")
        self.logger.line("SUCCESS: Batch {} completed.".format(self.batch))
        self.logger.line("Local latest : {}".format(self.config["local"]["root"]))
        self.logger.line("Remote latest: {}".format(remote_done))
        self.logger.line("Finish time: {}".format(format_log_date(now())))
        self.logger.line("==================================================")
        self.log_storage_inventory()

        self.set_step("Sending SUCCESS email report")
        sent = self.email_reporter.send(
            "SUCCESS",
            batch=self.batch,
            start_epoch=start_epoch,
        )

        if not sent:
            self.logger.line(
                "WARNING: Backup completed successfully, but the SUCCESS email could not be sent."
            )

        self.set_step("Running Docs Library backup")
        self.docs_backup.run()

    def log_storage_inventory(self):
        mount = self.config["local"]["mount"]
        usage = shutil.disk_usage(mount)
        self.logger.line("4TB disk: {} total, {} used, {} free".format(
            format_bytes(usage.total),
            format_bytes(usage.used),
            format_bytes(usage.free),
        ))
        self.log_local_inventory("UWORM", self.config["worm"]["root"])
        self.log_remote_inventory("DONE", self.config["remote"]["doneRoot"])

    def log_local_inventory(self, label, root):
        root_path = pathlib.Path(root)
        self.logger.line("{} contents: {}".format(label, root_path))
        try:
            files = sorted(path for path in root_path.rglob("*") if path.is_file())
        except OSError as error:
            self.logger.line("Could not inspect {}: {}".format(label, error))
            return

        total_bytes = 0
        for path in files:
            size = path.stat().st_size
            total_bytes += size
            self.logger.line("{} file: {} ({} / {} bytes)".format(
                label, path.relative_to(root_path), format_bytes(size), size
            ))
        self.logger.line("{} summary: {} files, {} ({} bytes)".format(
            label, len(files), format_bytes(total_bytes), total_bytes
        ))

    def log_remote_inventory(self, label, root):
        self.logger.line("{} contents: {}".format(label, root))
        try:
            output = self.remote.list_files(root)
        except Exception as error:
            self.logger.line("Could not inspect {}: {}".format(label, error))
            return

        total_bytes = 0
        file_count = 0
        for line in output.splitlines():
            size_text, path = line.split("\t", 1)
            size = int(size_text)
            total_bytes += size
            file_count += 1
            self.logger.line("{} file: {} ({} / {} bytes)".format(
                label, path, format_bytes(size), size
            ))
        self.logger.line("{} summary: {} files, {} ({} bytes)".format(
            label, file_count, format_bytes(total_bytes), total_bytes
        ))

    def handle_failure(self, error, exit_code, start_epoch):
        command = error.command_text if isinstance(error, CommandError) else "Unknown"

        self.logger.line("ERROR: pull_backup_v2.sh failed.")
        self.logger.line("Step: {}".format(self.current_step))
        self.logger.line("Line: Python orchestrator")
        self.logger.line("Command: {}".format(command))
        self.logger.line("Exit code: {}".format(exit_code))
        self.logger.line("Failure time: {}".format(format_log_date(now())))
        self.logger.line("Reason: {}".format(error))

        if isinstance(error, CommandError):
            log_command_output(self.logger, "stdout", error.stdout)
            log_command_output(self.logger, "stderr", error.stderr)

        batch_label = self.batch or self.requested_batch or "Unknown"
        failure_reason = truncate(
            re.sub(
                r"\s+",
                " ",
                "Exit code: {}; command: {}; message: {}".format(
                    exit_code,
                    command,
                    error,
                ),
            ),
            500,
        )

        self.logger.line("Attempting to send FAILED email report...")
        sent = self.email_reporter.send(
            "FAILED",
            batch=batch_label,
            start_epoch=start_epoch,
            failed_step=self.current_step,
            failure_reason=failure_reason,
        )

        if not sent:
            self.logger.line("WARNING: FAILED email report could not be sent.")

    def cleanup(self):
        self.set_step("Disabling LAN connection")

        try:
            self.lan.disable()
        except Exception as error:
            self.logger.line("WARNING: LAN cleanup failed: {}".format(error))

        self.local_lock.release()

    def set_step(self, step):
        self.current_step = step
        self.logger.line("Step: {}".format(step))

    def write_header(self):
        self.logger.line("")
        self.logger.line("==================================================")
        self.logger.line("Pull backup started: {}".format(format_log_date(now())))
        self.logger.line("==================================================")


def normalize_exit_code(error):
    exit_code = getattr(error, "exit_code", None)
    if isinstance(exit_code, int) and 0 < exit_code < 256:
        return exit_code
    return 1


def truncate(value, max_length):
    if len(value) > max_length:
        return value[:max_length]
    return value


def log_command_output(logger, name, output):
    if not output or not output.strip():
        return

    logger.line("Command {}:".format(name))
    logger.raw(output if output.endswith("\n") else output + "\n")

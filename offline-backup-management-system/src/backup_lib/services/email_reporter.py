import email.utils
import os
import posixpath
import re
import socket

from backup_lib.core.fs_utils import (
    count_files_and_bytes,
    exists,
    format_bytes,
    list_child_directories,
    list_relative_files,
)
from backup_lib.core.time_utils import (
    epoch_seconds,
    format_report_date,
    format_report_day,
    human_duration,
    now,
)


class EmailReporter:
    def __init__(self, config, runner, logger):
        self.config = config
        self.runner = runner
        self.logger = logger

    def send(self, status, batch="Unknown", start_epoch=None, failed_step="Unknown", failure_reason="No failure reason supplied"):
        if not self.email_available():
            self.logger.line("WARNING: Email configuration is unavailable.")
            return False

        try:
            report = self.build_report(
                status,
                batch=batch,
                start_epoch=start_epoch,
                failed_step=failed_step,
                failure_reason=failure_reason,
            )
            recipients = self.recipients()

            self.runner.run(
                self.config["email"]["msmtpBin"],
                recipients,
                input_text=report,
                capture_stderr=True,
                stream_output=False,
            )

            self.logger.line("Email report sent to {}".format(", ".join(recipients)))
            return True
        except Exception as error:
            self.logger.line("WARNING: Email report could not be sent: {}".format(error))
            return False

    def email_available(self):
        return os.access(self.config["email"]["msmtpBin"], os.X_OK) and os.access(
            self.config["email"]["msmtpConfig"],
            os.R_OK,
        )

    def build_report(self, status, batch, start_epoch, failed_step, failure_reason):
        current_time = now()
        finish_epoch = epoch_seconds(current_time)

        if isinstance(start_epoch, int):
            start_time = format_report_date_from_epoch(start_epoch)
            duration = human_duration(finish_epoch - start_epoch)
        else:
            start_time = "Not available"
            duration = "Not available"

        if status == "SUCCESS":
            subject = "[OFFLINE BACKUP] SUCCESS | {} | Batch: {}".format(
                format_report_day(current_time),
                batch,
            )
        else:
            subject = "[OFFLINE BACKUP] FAILED | {} | Action Required".format(
                format_report_day(current_time)
            )

        lines = [
            "From: {}".format(self.config["email"]["from"]),
            "To: {}".format(", ".join(self.recipients())),
            "Date: {}".format(email.utils.format_datetime(current_time)),
            "Subject: {}".format(subject),
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=UTF-8",
            "",
            "========================================================",
            "OFFLINE BACKUP DAILY REPORT",
            "========================================================",
            "",
            "Status          : {}".format(status),
            "Server          : {}".format(socket.gethostname()),
            "Batch           : {}".format(batch),
            "Start Time      : {}".format(start_time),
            "Finish Time     : {}".format(format_report_date(current_time)),
            "Duration        : {}".format(duration),
            "",
        ]

        if status == "SUCCESS":
            self.append_success_report(lines, batch)
        else:
            self.append_failure_report(lines, failed_step, failure_reason)

        lines.extend(
            [
                "",
                "========================================================",
                "This is an automated email from the Offline Backup System.",
                "Please do not reply.",
                "========================================================",
                "",
            ]
        )

        return "\n".join(lines)

    def append_success_report(self, lines, batch):
        batch_date = batch.split("_")[0]
        batch_dir = posixpath.join(self.config["worm"]["root"], batch_date)

        if not exists(batch_dir):
            raise RuntimeError("WORM batch missing for email report: {}".format(batch_dir))

        total = count_files_and_bytes(batch_dir)

        lines.extend(
            [
                "========================================================",
                "VERIFICATION",
                "========================================================",
                "",
                "[OK] Transfer Queue Completed",
                "[OK] Local Checksum Verified",
                "[OK] Safety Guard Passed",
                "[OK] Developer Done Updated",
                "[OK] Developer Done Checksum Verified",
                "[OK] Offline WORM Published",
                "[OK] WORM Retention Updated",
                "",
                "========================================================",
                "BACKUP SUMMARY",
                "========================================================",
                "",
                "Total Files     : {}".format(total["files"]),
                "Total Size      : {}".format(format_bytes(total["bytes"])),
                "",
            ]
        )

        for directory in list_child_directories(batch_dir):
            folder_name = posixpath.basename(directory)
            stats = count_files_and_bytes(directory)
            files = list_relative_files(directory)

            lines.extend(
                [
                    "--------------------------------------------------------",
                    folder_name,
                    "Files : {}".format(stats["files"]),
                    "Size  : {}".format(format_bytes(stats["bytes"])),
                    "",
                ]
            )

            for file_name in files:
                lines.append("- {}".format(file_name))

            lines.append("")

        lines.extend(
            [
                "========================================================",
                "CURRENT WORM RETENTION",
                "========================================================",
                "",
            ]
        )

        for retained_batch in self.list_retained_batch_dates():
            lines.append("[OK] {}".format(retained_batch))

        lines.extend(
            [
                "",
                "========================================================",
                "STORAGE INFORMATION",
                "========================================================",
                "",
            ]
        )

        df = self.runner.run(
            "df",
            ["-h", "--output=size,used,avail,pcent,target", self.config["local"]["mount"]],
            capture_stdout=True,
            stream_output=False,
            check=False,
        )

        if df.exit_code == 0:
            lines.append(df.stdout.rstrip())
        else:
            lines.append("Storage information unavailable.")

    def append_failure_report(self, lines, failed_step, failure_reason):
        lines.extend(
            [
                "========================================================",
                "FAILED STEP",
                "========================================================",
                "",
                "Step            : {}".format(failed_step),
                "Reason          : {}".format(failure_reason),
                "",
                "========================================================",
                "PROTECTION STATUS",
                "========================================================",
                "",
                "[OK] Previous successful backup remains protected",
                "[OK] Existing WORM backup remains unchanged",
                "[OK] Transfer Queue retained for investigation",
                "",
                "========================================================",
                "ACTION REQUIRED",
                "========================================================",
                "",
                "Manual investigation is required before the next run.",
            ]
        )

    def list_retained_batch_dates(self):
        worm_root = self.config["worm"]["root"]
        if not exists(worm_root):
            return []

        return sorted(
            entry
            for entry in os.listdir(worm_root)
            if os.path.isdir(posixpath.join(worm_root, entry))
            and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", entry)
        )

    def recipients(self):
        recipients = self.config["email"]["to"]
        if isinstance(recipients, list):
            return recipients
        return [recipients]


def format_report_date_from_epoch(epoch_value):
    import datetime

    value = datetime.datetime.fromtimestamp(epoch_value).astimezone()
    return format_report_date(value)

import os
import posixpath
import re

from backup_lib.core.fs_utils import (
    chmod_tree,
    count_files_and_bytes,
    ensure_dir,
    exists,
    format_bytes,
    has_any_file,
    parse_mode,
    remove_path,
)


class WormPublisher:
    def __init__(self, config, runner, logger):
        self.config = config
        self.runner = runner
        self.logger = logger

    def publish(self, requested_batch):
        batch_date = requested_batch.split("_")[0]
        target = posixpath.join(self.config["worm"]["root"], batch_date)
        new_batch = posixpath.join(
            self.config["local"]["mount"],
            ".worm_new_{}_{}".format(requested_batch, os.getpid()),
        )
        old_batch = posixpath.join(
            self.config["local"]["mount"],
            ".worm_old_{}_{}".format(requested_batch, os.getpid()),
        )

        self.logger.line("Publishing backup_temp to WORM batch: {}".format(batch_date))

        if not exists(self.config["local"]["root"]) or not has_any_file(self.config["local"]["root"]):
            raise RuntimeError("backup_temp is missing or empty.")

        self.ensure_owned_directory(
            self.config["worm"]["root"],
            parse_mode(self.config["worm"]["dirMode"]),
            self.config["worm"]["owner"],
            self.config["worm"]["group"],
        )

        if exists(new_batch) or exists(old_batch):
            raise RuntimeError("Temporary WORM recovery directory exists.")

        moved_local_root = False
        moved_old_target = False

        try:
            os.rename(self.config["local"]["root"], new_batch)
            moved_local_root = True

            self.runner.run(
                "chown",
                ["-R", "{}:{}".format(self.config["worm"]["owner"], self.config["worm"]["group"]), new_batch],
            )
            chmod_tree(
                new_batch,
                parse_mode(self.config["worm"]["dirMode"]),
                parse_mode(self.config["worm"]["fileMode"]),
            )

            if exists(target):
                os.rename(target, old_batch)
                moved_old_target = True

            os.rename(new_batch, target)
            moved_local_root = False

            self.ensure_owned_directory(
                self.config["local"]["root"],
                parse_mode(self.config["local"]["rootMode"]),
                self.config["local"]["owner"],
                self.config["local"]["group"],
            )

            if moved_old_target:
                remove_path(old_batch)
        except Exception:
            if moved_old_target and not exists(target) and exists(old_batch):
                try:
                    os.rename(old_batch, target)
                except OSError:
                    pass

            if moved_local_root and not exists(self.config["local"]["root"]) and exists(new_batch):
                try:
                    os.rename(new_batch, self.config["local"]["root"])
                except OSError:
                    pass

                self.runner.run(
                    "chown",
                    [
                        "-R",
                        "{}:{}".format(
                            self.config["local"]["owner"],
                            self.config["local"]["group"],
                        ),
                        self.config["local"]["root"],
                    ],
                    check=False,
                )

            raise

        batches = self.list_retained_batch_dates()

        while len(batches) > self.config["worm"]["keepDays"]:
            oldest = batches.pop(0)
            oldest_path = posixpath.join(self.config["worm"]["root"], oldest)
            self.logger.line("Deleting oldest WORM batch: {}".format(oldest_path))
            remove_path(oldest_path)

        stats = count_files_and_bytes(target)
        self.logger.line("WORM publish completed.")
        self.logger.line("Published batch: {}".format(target))
        self.logger.line("Batch files    : {}".format(stats["files"]))
        self.logger.line("Batch size     : {}".format(format_bytes(stats["bytes"])))
        self.logger.line("Batches kept   : {}".format(len(batches)))

    def list_retained_batch_dates(self):
        if not exists(self.config["worm"]["root"]):
            return []

        return sorted(
            entry
            for entry in os.listdir(self.config["worm"]["root"])
            if os.path.isdir(posixpath.join(self.config["worm"]["root"], entry))
            and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", entry)
        )

    def ensure_owned_directory(self, target, mode, owner, group):
        ensure_dir(target, mode)
        os.chmod(target, mode)
        self.runner.run("chown", ["{}:{}".format(owner, group), target])

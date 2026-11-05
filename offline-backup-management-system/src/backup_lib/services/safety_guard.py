from backup_lib.core.fs_utils import count_files_and_bytes


class SafetyGuard:
    def __init__(self, config, logger):
        self.config = config["safetyGuard"]
        self.logger = logger

    def verify(self, stage_path):
        stats = count_files_and_bytes(stage_path)

        self.logger.line("Safety guard:")
        self.logger.line("  Files       : {}".format(stats["files"]))
        self.logger.line("  Total bytes : {}".format(stats["bytes"]))

        if stats["files"] < self.config["minFiles"]:
            raise RuntimeError(
                "\n".join(
                    [
                        "Batch rejected by safety guard.",
                        "Reason: fewer than {} files.".format(self.config["minFiles"]),
                        "Developer Done and back_up_worm were not changed.",
                        "Remote transfer queue has been kept for review.",
                    ]
                )
            )

        if stats["bytes"] < self.config["minBytes"]:
            raise RuntimeError(
                "\n".join(
                    [
                        "Batch rejected by safety guard.",
                        "Reason: batch is smaller than {} bytes.".format(
                            self.config["minBytes"]
                        ),
                        "Developer Done and back_up_worm were not changed.",
                        "Remote transfer queue has been kept for review.",
                    ]
                )
            )

        self.logger.line("Safety guard passed.")

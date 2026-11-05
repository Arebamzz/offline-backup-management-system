import os


class LocalDiskService:
    def __init__(self, config, runner, logger):
        self.config = config
        self.runner = runner
        self.logger = logger

    def verify(self):
        local = self.config["local"]

        mountpoint = self.runner.run(
            "mountpoint",
            ["-q", local["mount"]],
            capture_stderr=True,
            stream_output=False,
            check=False,
        )

        if mountpoint.exit_code != 0:
            raise RuntimeError("{} is not mounted.".format(local["mount"]))

        uuid = self.runner.run(
            "findmnt",
            ["-n", "-o", "UUID", "--target", local["mount"]],
            capture_stdout=True,
            stream_output=False,
        )
        actual_uuid = uuid.stdout.strip()

        if actual_uuid != local["expectedUuid"]:
            raise RuntimeError(
                "\n".join(
                    [
                        "Unexpected disk mounted at {}".format(local["mount"]),
                        "Expected UUID: {}".format(local["expectedUuid"]),
                        "Actual UUID  : {}".format(actual_uuid),
                    ]
                )
            )

        require_access(local["root"], os.W_OK, "{} is missing or not writable.".format(local["root"]))
        require_access(
            self.config["ssh"]["key"],
            os.R_OK,
            "SSH private key is not readable: {}".format(self.config["ssh"]["key"]),
        )

        self.logger.line(
            "Verified backup disk: {} ({})".format(local["mount"], actual_uuid)
        )


def require_access(target, mode, message):
    if not os.access(target, mode):
        raise RuntimeError(message)

from backup_lib.core.ssh_options import build_rsync_remote_shell


class RsyncService:
    def __init__(self, config, runner):
        self.config = config
        self.runner = runner
        self.remote_shell = build_rsync_remote_shell(config["ssh"])

    def pull_queue_to_stage(self, remote_queue, local_stage):
        self.runner.run(
            "rsync",
            [
                "-a",
                "-v",
                "--delete",
                "--partial",
                "--append-verify",
                "--out-format=%l %n%L",
                "--info=progress2",
                "--stats",
                "--human-readable",
                "-e",
                self.remote_shell,
                "{}:{}".format(
                    self.config["remote"]["host"],
                    with_trailing_slash(remote_queue),
                ),
                with_trailing_slash(local_stage),
            ],
        )

    def verify_remote_to_local(self, remote_path, local_path):
        result = self.runner.run(
            "rsync",
            [
                "-rcn",
                "--delete",
                "--itemize-changes",
                "-e",
                self.remote_shell,
                "{}:{}".format(
                    self.config["remote"]["host"],
                    with_trailing_slash(remote_path),
                ),
                with_trailing_slash(local_path),
            ],
            capture_stdout=True,
            capture_stderr=True,
            stream_output=False,
        )

        return result.stdout


def with_trailing_slash(value):
    return value if value.endswith("/") else value + "/"

import pathlib

from backup_lib.core.ssh_options import build_ssh_args


class RemoteBackupService:
    def __init__(self, config, runner):
        self.config = config
        self.runner = runner
        self.scripts_root = pathlib.Path(__file__).resolve().parents[2] / "remote-scripts"

    def prepare_batch(self, requested_batch):
        script = self.read_script("prepare-batch.sh")
        result = self.run_script(
            script,
            [
                requested_batch,
                self.config["remote"]["base"],
                self.config["remote"]["inProgressPath"],
                self.config["remote"]["queueRoot"],
                self.config["remote"]["lockFile"],
            ]
            + list(self.config["remote"]["replacementDirs"]),
            capture=True,
        )

        return result.stdout.strip()

    def copy_queue_to_done(self, batch):
        script = self.read_script("copy-queue-to-done.sh")
        self.run_script(
            script,
            [
                batch,
                self.config["remote"]["queueRoot"],
                self.config["remote"]["doneRoot"],
                str(self.config["developerDone"]["reserveBytes"]),
            ],
        )

    def clear_queue(self, batch):
        script = self.read_script("clear-queue.sh")
        self.run_script(
            script,
            [
                batch,
                self.config["remote"]["queueRoot"],
                self.config["remote"]["doneRoot"],
            ],
        )

    def list_files(self, root):
        script = """set -e
ROOT="$1"
if [ ! -d "$ROOT" ]; then
    exit 0
fi
find -- "$ROOT" -type f -printf '%s\t%p\n' | sort
"""
        result = self.run_script(script, [root], capture=True)
        return result.stdout

    def read_script(self, file_name):
        return (self.scripts_root / file_name).read_text(encoding="utf-8")

    def run_script(self, script, args, capture=False):
        ssh_args = (
            build_ssh_args(self.config["ssh"])
            + [
                self.config["remote"]["host"],
                "bash",
                "-s",
                "--",
            ]
            + list(args)
        )

        return self.runner.run(
            "ssh",
            ssh_args,
            input_text=script,
            capture_stdout=bool(capture),
            capture_stderr=bool(capture),
            stream_output=not capture,
        )

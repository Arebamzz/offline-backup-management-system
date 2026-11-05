import os


class LocalLock:
    def __init__(self, lock_file, runner):
        self.lock_file = lock_file
        self.runner = runner
        self.fd = None

    def acquire(self):
        directory = os.path.dirname(self.lock_file)
        if directory:
            os.makedirs(directory, mode=0o750, exist_ok=True)

        self.fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o600)

        result = self.runner.run(
            "flock",
            ["-n", str(self.fd)],
            capture_stderr=True,
            stream_output=False,
            check=False,
            pass_fds=(self.fd,),
        )

        if result.exit_code != 0:
            self.release()
            return False

        return True

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

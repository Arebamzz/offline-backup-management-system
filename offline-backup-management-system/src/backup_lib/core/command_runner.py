import os
import select
import shlex
import signal
import subprocess


class CommandError(Exception):
    def __init__(self, message, command, args=None, exit_code=None, signal=None, stdout="", stderr=""):
        super().__init__(message)
        self.command = command
        self.command_args = args or []
        self.command_text = command_text(command, self.command_args)
        self.exit_code = exit_code
        self.signal = signal
        self.stdout = stdout or ""
        self.stderr = stderr or ""


class CommandResult:
    def __init__(self, exit_code, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout or ""
        self.stderr = stderr or ""


class CommandRunner:
    def __init__(self, logger):
        self.logger = logger
        self.active_process = None

    def terminate_active(self):
        process = self.active_process
        if not process or process.poll() is not None:
            return

        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass

    def run(
        self,
        command,
        args=None,
        input_text=None,
        capture_stdout=False,
        capture_stderr=False,
        stream_output=True,
        check=True,
        pass_fds=(),
        env=None,
    ):
        args = args or []

        try:
            process = subprocess.Popen(
                [command] + list(args),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env or os.environ.copy(),
                pass_fds=pass_fds,
                start_new_session=True,
            )
        except OSError as error:
            raise CommandError(
                "Could not start command: {}".format(command),
                command,
                args,
            ) from error

        self.active_process = process
        stdout_chunks = []
        stderr_chunks = []

        try:
            if input_text is not None:
                try:
                    process.stdin.write(input_text.encode("utf-8"))
                except OSError:
                    pass
            try:
                process.stdin.close()
            except OSError:
                pass

            streams = {
                process.stdout.fileno(): ("stdout", process.stdout),
                process.stderr.fileno(): ("stderr", process.stderr),
            }

            while streams:
                ready, _, _ = select.select(list(streams.keys()), [], [], 0.2)

                for fd in ready:
                    name, stream = streams[fd]
                    chunk = os.read(fd, 65536)

                    if not chunk:
                        stream.close()
                        streams.pop(fd)
                        continue

                    text = chunk.decode("utf-8", errors="replace")

                    if name == "stdout":
                        if capture_stdout:
                            stdout_chunks.append(text)
                    else:
                        if capture_stderr:
                            stderr_chunks.append(text)

                    if stream_output:
                        self.logger.raw(text)

            process.wait()
        finally:
            self.active_process = None

        captured_stdout = "".join(stdout_chunks)
        captured_stderr = "".join(stderr_chunks)

        result = CommandResult(process.returncode, captured_stdout, captured_stderr)

        if check and process.returncode != 0:
            raise CommandError(
                "Command failed with exit code {}: {}".format(
                    process.returncode,
                    command_text(command, args),
                ),
                command,
                args,
                exit_code=process.returncode,
                stdout=captured_stdout,
                stderr=captured_stderr,
            )

        return result


def command_text(command, args):
    return " ".join([shlex.quote(str(command))] + [shlex.quote(str(arg)) for arg in args])

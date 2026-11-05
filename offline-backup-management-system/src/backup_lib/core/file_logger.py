import os
import sys


class FileLogger:
    def __init__(self, file_path, mirror_to_console=False, group=None):
        self.file_path = file_path
        self.mirror_to_console = bool(mirror_to_console)
        self.group = group

        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, mode=0o750, exist_ok=True)

        self.stream = open(file_path, "a", encoding="utf-8")
        try:
            os.chmod(file_path, 0o644)
            if self.group:
                import grp
                os.chown(file_path, -1, grp.getgrnam(self.group).gr_gid)
        except OSError:
            pass

    def line(self, message=""):
        self.raw("{}\n".format(message))

    def raw(self, message):
        self.stream.write(message)
        self.stream.flush()

        if self.mirror_to_console:
            sys.stdout.write(message)
            sys.stdout.flush()

    def close(self):
        self.stream.close()

import os
import posixpath

from backup_lib.core.fs_utils import ensure_dir, exists, parse_mode, remove_path


class LocalPublisher:
    def __init__(self, config, logger):
        self.config = config["local"]
        self.logger = logger

    def prepare_batch_paths(self, batch):
        local_stage = posixpath.join(self.config["stageRoot"], batch)
        local_old = posixpath.join(self.config["mount"], ".backup_temp.old.{}".format(batch))

        ensure_dir(self.config["stageRoot"], 0o750)
        ensure_dir(local_stage, 0o750)

        return local_stage, local_old

    def recover_previous_swap(self, local_old):
        if not exists(local_old):
            return

        if not exists(self.config["root"]):
            self.logger.line("Restoring previous local latest folder.")
            os.rename(local_old, self.config["root"])
            return

        raise RuntimeError("Old local recovery folder already exists: {}".format(local_old))

    def publish_latest(self, local_stage, local_old):
        if not exists(self.config["root"]):
            raise RuntimeError("Current local latest folder is missing: {}".format(self.config["root"]))

        os.rename(self.config["root"], local_old)

        try:
            os.rename(local_stage, self.config["root"])
        except OSError:
            self.logger.line("ERROR: Could not publish the new local latest folder.")

            if not exists(self.config["root"]) and exists(local_old):
                try:
                    os.rename(local_old, self.config["root"])
                except OSError:
                    pass

            raise

        remove_path(local_old)

        try:
            os.rmdir(self.config["stageRoot"])
        except OSError:
            pass

        os.chmod(self.config["root"], parse_mode(self.config["rootMode"]))
        self.logger.line("Local backup_temp replaced with latest verified batch.")

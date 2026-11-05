#!/usr/bin/env python3

import os
import pathlib
import signal
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from backup_lib.config import load_config, usage
from backup_lib.core.command_runner import CommandError, CommandRunner
from backup_lib.core.file_logger import FileLogger
from backup_lib.services.docs_backup import DocsBackup


def main(argv):
    os.umask(0o077)

    if "--help" in argv or "-h" in argv:
        sys.stdout.write(usage())
        return 0

    try:
        config, config_path = load_config(argv)
    except Exception as error:
        sys.stderr.write("{}\n".format(error))
        return 1

    logger = None
    runner = None

    def stop_active_command(signum, _frame):
        if runner:
            runner.terminate_active()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, stop_active_command)
    signal.signal(signal.SIGTERM, stop_active_command)

    try:
        mirror_to_console = (
            config["logging"]["mirrorToConsole"]
            or os.environ.get("OFFLINE_BACKUP_MIRROR_CONSOLE") == "1"
        )
        logger = FileLogger(
            config["local"]["logFile"],
            mirror_to_console=mirror_to_console,
            group=config["local"].get("group"),
        )
        logger.line("Config: {}".format(config_path))
        runner = CommandRunner(logger)
        DocsBackup(config, runner, logger).run()
        return 0
    except Exception as error:
        if logger:
            logger.line("ERROR: Docs backup failed: {}".format(error))
            if isinstance(error, CommandError):
                detail = (error.stderr or error.stdout).strip()
                if detail:
                    logger.line("ERROR detail: {}".format(detail))
        else:
            sys.stderr.write("{}\n".format(error))
        return 1
    finally:
        if logger:
            logger.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

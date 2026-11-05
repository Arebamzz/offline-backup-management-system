#!/usr/bin/env python3

import os
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from backup_lib.backup_orchestrator import BackupOrchestrator
from backup_lib.config import load_config, usage
from backup_lib.core.command_runner import CommandRunner
from backup_lib.core.file_logger import FileLogger


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
    except Exception as error:
        sys.stderr.write("Could not open log file: {}\n".format(error))
        return 1

    try:
        runner = CommandRunner(logger)
        orchestrator = BackupOrchestrator(
            config=config,
            config_path=config_path,
            logger=logger,
            runner=runner,
        )
        return orchestrator.run()
    except Exception as error:
        sys.stderr.write("{}\n".format(error))
        return 1
    finally:
        logger.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

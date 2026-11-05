import copy
import json
import os
import pathlib
import posixpath


def usage():
    return "\n".join(
        [
            "Usage: pull-backup [--config <path>]",
            "",
            "Environment:",
            "  PULL_BACKUP_CONFIG  Alternative config path.",
            "  PYTHON_BIN          Python executable used by pull_backup_v2.sh.",
            "",
        ]
    )


def resolve_writable_log_path(log_path, fallback_root=None):
    fallback_root = pathlib.Path(fallback_root or pathlib.Path.home() / ".local" / "share" / "offline-backup")
    candidate = pathlib.Path(str(log_path or "")).expanduser()

    try:
        if str(candidate):
            parent = candidate.parent
            if parent.exists() and os.access(parent, os.W_OK | os.X_OK):
                if candidate.exists():
                    if os.access(candidate, os.R_OK | os.W_OK):
                        return str(candidate)
                else:
                    return str(candidate)
    except OSError:
        pass

    fallback_root.mkdir(parents=True, exist_ok=True)
    return str(fallback_root / "pull_backup.log")


def load_config(argv):
    config_path = resolve_config_path(argv)

    with open(config_path, "r", encoding="utf-8") as file_handle:
        raw = json.load(file_handle)

    config = with_derived_defaults(raw)
    validate_config(config, config_path)

    return config, config_path


def resolve_config_path(argv):
    cli_path = None
    index = 0

    while index < len(argv):
        arg = argv[index]

        if arg == "--config":
            if index + 1 >= len(argv):
                raise ValueError("Missing value for --config.\n{}".format(usage()))
            cli_path = argv[index + 1]
            index += 2
            continue

        if arg.startswith("--config="):
            cli_path = arg[len("--config=") :]
            if not cli_path:
                raise ValueError("Missing value for --config.\n{}".format(usage()))
            index += 1
            continue

        raise ValueError("Unknown argument: {}\n{}".format(arg, usage()))

    requested_path = (
        cli_path
        or os.environ.get("PULL_BACKUP_CONFIG")
        or str(pathlib.Path(__file__).resolve().parents[2] / "config" / "pull-backup.json")
    )

    return str(pathlib.Path(requested_path).resolve())


def with_derived_defaults(config):
    next_config = copy.deepcopy(config)

    next_config.setdefault("remote", {})
    next_config.setdefault("local", {})
    next_config.setdefault("ssh", {})
    next_config.setdefault("lan", {})
    next_config.setdefault("safetyGuard", {})
    next_config.setdefault("developerDone", {})
    next_config.setdefault("worm", {})
    next_config.setdefault("email", {})
    next_config.setdefault("logging", {})
    next_config.setdefault("docs", {})

    remote = next_config["remote"]
    local = next_config["local"]
    ssh = next_config["ssh"]
    lan = next_config["lan"]
    safety_guard = next_config["safetyGuard"]
    developer_done = next_config["developerDone"]
    worm = next_config["worm"]
    logging = next_config["logging"]
    docs = next_config["docs"]

    if remote.get("base"):
        remote.setdefault("inProgressPath", posixpath.join(remote["base"], "In_Progress"))
        remote.setdefault("queueRoot", posixpath.join(remote["inProgressPath"], ".Transfer_Queue"))
        remote.setdefault("lockFile", posixpath.join(remote["base"], ".FTP.lock"))

    if local.get("mount"):
        local.setdefault("root", posixpath.join(local["mount"], "backup_temp"))
        local.setdefault("stageRoot", posixpath.join(local["mount"], ".pull_staging"))
        worm.setdefault("root", posixpath.join(local["mount"], "back_up_worm"))
        docs.setdefault("localRoot", posixpath.join(local["mount"], "docs_backup"))

    remote.setdefault("replacementDirs", [])
    docs.setdefault("replacementDocs", [])
    if docs.get("localRoot"):
        docs.setdefault("dbPath", posixpath.join(docs["localRoot"], "docs.sqlite"))
    ssh.setdefault("connectTimeoutSeconds", 30)
    ssh.setdefault("identitiesOnly", True)
    ssh.setdefault("batchMode", True)
    ssh.setdefault("strictHostKeyChecking", True)
    lan.setdefault("enabled", True)
    lan.setdefault("waitSeconds", 90)
    lan.setdefault("requireDefaultRoute", True)
    safety_guard.setdefault("minFiles", 3)
    safety_guard.setdefault("minBytes", 100 * 1024 * 1024)
    developer_done.setdefault("reserveBytes", 2 * 1024 * 1024 * 1024)
    worm.setdefault("keepDays", 5)
    worm.setdefault("dirMode", "750")
    worm.setdefault("fileMode", "640")
    local.setdefault("rootMode", "750")
    local["logFile"] = resolve_writable_log_path(
        local.get("logFile"),
        pathlib.Path.home() / ".local" / "share" / "offline-backup",
    )
    logging.setdefault("mirrorToConsole", False)

    next_config.setdefault(
        "requiredCommands",
        [
            "bash",
            "ssh",
            "rsync",
            "findmnt",
            "mountpoint",
            "flock",
            "ip",
            "networkctl",
            "hostname",
            "df",
            "du",
            "chown",
        ],
    )

    return next_config


def validate_config(config, config_path):
    errors = []

    for key in [
        "remote.host",
        "remote.base",
        "remote.queueRoot",
        "remote.doneRoot",
        "remote.inProgressPath",
        "remote.lockFile",
        "local.mount",
        "local.root",
        "local.stageRoot",
        "local.expectedUuid",
        "local.lockFile",
        "local.logFile",
        "ssh.key",
        "ssh.knownHosts",
        "worm.root",
        "worm.owner",
        "worm.group",
        "email.from",
        "email.msmtpBin",
        "email.msmtpConfig",
    ]:
        require_string(errors, config, key)

    require_string_or_string_array(errors, config, "email.to")

    for key in [
        "ssh.connectTimeoutSeconds",
        "lan.waitSeconds",
        "safetyGuard.minFiles",
        "safetyGuard.minBytes",
        "developerDone.reserveBytes",
        "worm.keepDays",
    ]:
        require_positive_integer(errors, config, key)

    if config["lan"]["enabled"]:
        require_string(errors, config, "lan.interface")
        require_string(errors, config, "lan.ipv4")

    replacement_dirs = config["remote"].get("replacementDirs")
    if not isinstance(replacement_dirs, list):
        errors.append("remote.replacementDirs must be an array.")
    else:
        for directory in replacement_dirs:
            if not isinstance(directory, str) or not directory.strip() or directory.startswith("/"):
                errors.append("remote.replacementDirs entries must be non-empty relative paths.")

    docs = config.get("docs", {})
    replacement_docs = docs.get("replacementDocs")
    if not isinstance(replacement_docs, list):
        errors.append("docs.replacementDocs must be an array.")
    else:
        for entry in replacement_docs:
            if not isinstance(entry, str) or not entry.strip():
                errors.append("docs.replacementDocs entries must be non-empty paths.")

    for key in [
        "docs.localRoot",
        "docs.dbPath",
    ]:
        require_string(errors, config, key)

    if not isinstance(config.get("requiredCommands"), list):
        errors.append("requiredCommands must be an array.")

    if errors:
        raise ValueError("Invalid backup config: {}\n- {}".format(config_path, "\n- ".join(errors)))


def require_string(errors, config, key):
    value = read_path(config, key)
    if not isinstance(value, str) or not value.strip():
        errors.append("{} must be a non-empty string.".format(key))


def require_string_or_string_array(errors, config, key):
    value = read_path(config, key)
    valid_string = isinstance(value, str) and bool(value.strip())
    valid_array = (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, str) and item.strip() for item in value)
    )

    if not valid_string and not valid_array:
        errors.append("{} must be a non-empty string or array of strings.".format(key))


def require_positive_integer(errors, config, key):
    value = read_path(config, key)
    if not isinstance(value, int) or value <= 0:
        errors.append("{} must be a positive integer.".format(key))


def read_path(config, key):
    current = config
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current

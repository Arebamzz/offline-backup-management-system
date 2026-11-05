import shlex


def build_ssh_args(ssh_config):
    return [
        "-i",
        ssh_config["key"],
        "-o",
        option_value("IdentitiesOnly", ssh_config["identitiesOnly"]),
        "-o",
        option_value("BatchMode", ssh_config["batchMode"]),
        "-o",
        option_value("StrictHostKeyChecking", ssh_config["strictHostKeyChecking"]),
        "-o",
        "UserKnownHostsFile={}".format(ssh_config["knownHosts"]),
        "-o",
        "ConnectTimeout={}".format(ssh_config["connectTimeoutSeconds"]),
        "-o",
        "ServerAliveInterval={}".format(ssh_config.get("serverAliveIntervalSeconds", 30)),
        "-o",
        "ServerAliveCountMax={}".format(ssh_config.get("serverAliveCountMax", 10)),
    ]


def build_rsync_remote_shell(ssh_config):
    parts = ["ssh"] + build_ssh_args(ssh_config)
    return " ".join(shlex.quote(str(part)) for part in parts)


def option_value(name, value):
    return "{}={}".format(name, "yes" if value else "no")

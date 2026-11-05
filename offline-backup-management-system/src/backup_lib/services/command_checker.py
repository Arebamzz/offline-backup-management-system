import shutil


class CommandChecker:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger

    def verify(self):
        commands = self.required_commands()

        for command in commands:
            if shutil.which(command) is None:
                raise RuntimeError("Required command is missing: {}".format(command))

        self.logger.line("Required commands available: {}".format(", ".join(commands)))

    def required_commands(self):
        if self.config["lan"]["enabled"]:
            return list(self.config["requiredCommands"])

        return [
            command
            for command in self.config["requiredCommands"]
            if command not in ["ip", "networkctl"]
        ]

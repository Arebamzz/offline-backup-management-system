import time


class LanService:
    def __init__(self, config, runner, logger):
        self.config = config["lan"]
        self.runner = runner
        self.logger = logger
        self.enabled_by_this_run = False

    def enable(self):
        if not self.config["enabled"]:
            self.logger.line("LAN enable skipped by configuration.")
            return

        interface = self.config["interface"]
        self.logger.line("Enabling LAN interface: {}".format(interface))

        link = self.runner.run(
            "ip",
            ["link", "show", interface],
            capture_stderr=True,
            stream_output=False,
            check=False,
        )

        if link.exit_code != 0:
            raise RuntimeError("LAN interface does not exist: {}".format(interface))

        self.runner.run("ip", ["link", "set", "dev", interface, "up"])
        self.enabled_by_this_run = True

        self.runner.run(
            "networkctl",
            ["reconfigure", interface],
            stream_output=False,
            check=False,
        )

        deadline = time.monotonic() + self.config["waitSeconds"]

        while time.monotonic() < deadline:
            addr = self.runner.run(
                "ip",
                ["-4", "-o", "addr", "show", "dev", interface, "scope", "global"],
                capture_stdout=True,
                stream_output=False,
                check=False,
            )
            route = self.runner.run(
                "ip",
                ["route", "show", "default"],
                capture_stdout=True,
                stream_output=False,
                check=False,
            )

            has_address = self.config["ipv4"] in addr.stdout
            has_route = (
                not self.config["requireDefaultRoute"]
                or "dev {}".format(interface) in route.stdout
            )

            if has_address and has_route:
                self.logger.line("LAN connection ready.")
                self.logger.line("Address: {}".format(self.config["ipv4"]))
                self.runner.run("ip", ["-4", "-br", "addr", "show", interface])
                self.runner.run("ip", ["route", "show", "default"])
                return

            time.sleep(2)

        self.logger.line(
            "ERROR: LAN did not become ready within {}s.".format(
                self.config["waitSeconds"]
            )
        )
        self.runner.run(
            "ip",
            ["-4", "-br", "addr", "show", interface],
            check=False,
        )
        self.runner.run("ip", ["route"], check=False)
        raise RuntimeError(
            "LAN did not become ready within {}s.".format(self.config["waitSeconds"])
        )

    def disable(self):
        if not self.config["enabled"] or not self.enabled_by_this_run:
            return

        interface = self.config["interface"]
        self.logger.line("Disabling LAN interface: {}".format(interface))

        result = self.runner.run(
            "ip",
            ["link", "set", "dev", interface, "down"],
            check=False,
        )

        if result.exit_code != 0:
            self.logger.line("WARNING: Could not disable LAN interface.")
            return

        self.enabled_by_this_run = False
        self.logger.line("LAN interface disabled.")

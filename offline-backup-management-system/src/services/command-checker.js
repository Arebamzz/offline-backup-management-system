class CommandChecker {
  constructor({ config, runner, logger }) {
    this.config = config;
    this.runner = runner;
    this.logger = logger;
  }

  async verify() {
    const commands = this.requiredCommands();

    for (const command of commands) {
      const result = await this.runner.run(
        'bash',
        ['-lc', 'command -v "$1" >/dev/null 2>&1', 'bash', command],
        {
          captureStderr: true,
          streamOutput: false,
          check: false
        }
      );

      if (result.exitCode !== 0) {
        throw new Error(`Required command is missing: ${command}`);
      }
    }

    this.logger.line(`Required commands available: ${commands.join(', ')}`);
  }

  requiredCommands() {
    if (this.config.lan.enabled) {
      return this.config.requiredCommands;
    }

    return this.config.requiredCommands.filter((command) => !['ip', 'networkctl'].includes(command));
  }
}

module.exports = {
  CommandChecker
};

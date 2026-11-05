const { setTimeout: sleep } = require('timers/promises');

class LanService {
  constructor({ config, runner, logger }) {
    this.config = config.lan;
    this.runner = runner;
    this.logger = logger;
    this.enabledByThisRun = false;
  }

  async enable() {
    if (!this.config.enabled) {
      this.logger.line('LAN enable skipped by configuration.');
      return;
    }

    this.logger.line(`Enabling LAN interface: ${this.config.interface}`);

    const link = await this.runner.run('ip', ['link', 'show', this.config.interface], {
      captureStderr: true,
      streamOutput: false,
      check: false
    });

    if (link.exitCode !== 0) {
      throw new Error(`LAN interface does not exist: ${this.config.interface}`);
    }

    await this.runner.run('ip', ['link', 'set', 'dev', this.config.interface, 'up']);
    this.enabledByThisRun = true;

    await this.runner.run('networkctl', ['reconfigure', this.config.interface], {
      streamOutput: false,
      check: false
    });

    const deadline = Date.now() + this.config.waitSeconds * 1000;

    while (Date.now() < deadline) {
      const addr = await this.runner.run(
        'ip',
        ['-4', '-o', 'addr', 'show', 'dev', this.config.interface, 'scope', 'global'],
        { captureStdout: true, streamOutput: false, check: false }
      );

      const route = await this.runner.run(
        'ip',
        ['route', 'show', 'default'],
        { captureStdout: true, streamOutput: false, check: false }
      );

      const hasAddress = addr.stdout.includes(this.config.ipv4);
      const hasRoute = !this.config.requireDefaultRoute || route.stdout.includes(`dev ${this.config.interface}`);

      if (hasAddress && hasRoute) {
        this.logger.line('LAN connection ready.');
        this.logger.line(`Address: ${this.config.ipv4}`);
        await this.runner.run('ip', ['-4', '-br', 'addr', 'show', this.config.interface]);
        await this.runner.run('ip', ['route', 'show', 'default']);
        return;
      }

      await sleep(2000);
    }

    this.logger.line(`ERROR: LAN did not become ready within ${this.config.waitSeconds}s.`);
    await this.runner.run('ip', ['-4', '-br', 'addr', 'show', this.config.interface], { check: false });
    await this.runner.run('ip', ['route'], { check: false });
    throw new Error(`LAN did not become ready within ${this.config.waitSeconds}s.`);
  }

  async disable() {
    if (!this.config.enabled || !this.enabledByThisRun) {
      return;
    }

    this.logger.line(`Disabling LAN interface: ${this.config.interface}`);

    const result = await this.runner.run('ip', ['link', 'set', 'dev', this.config.interface, 'down'], {
      check: false
    });

    if (result.exitCode !== 0) {
      this.logger.line('WARNING: Could not disable LAN interface.');
      return;
    }

    this.enabledByThisRun = false;
    this.logger.line('LAN interface disabled.');
  }
}

module.exports = {
  LanService
};

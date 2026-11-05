const fs = require('fs');

class LocalDiskService {
  constructor({ config, runner, logger }) {
    this.config = config;
    this.runner = runner;
    this.logger = logger;
  }

  async verify() {
    const local = this.config.local;

    const mountpoint = await this.runner.run('mountpoint', ['-q', local.mount], {
      captureStderr: true,
      streamOutput: false,
      check: false
    });

    if (mountpoint.exitCode !== 0) {
      throw new Error(`${local.mount} is not mounted.`);
    }

    const uuid = await this.runner.run('findmnt', ['-n', '-o', 'UUID', '--target', local.mount], {
      captureStdout: true,
      streamOutput: false
    });

    const actualUuid = uuid.stdout.trim();
    if (actualUuid !== local.expectedUuid) {
      throw new Error([
        `Unexpected disk mounted at ${local.mount}`,
        `Expected UUID: ${local.expectedUuid}`,
        `Actual UUID  : ${actualUuid}`
      ].join('\n'));
    }

    await requireAccess(local.root, fs.constants.W_OK, `${local.root} is missing or not writable.`);
    await requireAccess(this.config.ssh.key, fs.constants.R_OK, `SSH private key is not readable: ${this.config.ssh.key}`);

    this.logger.line(`Verified backup disk: ${local.mount} (${actualUuid})`);
  }
}

async function requireAccess(target, mode, message) {
  try {
    await fs.promises.access(target, mode);
  } catch {
    throw new Error(message);
  }
}

module.exports = {
  LocalDiskService
};

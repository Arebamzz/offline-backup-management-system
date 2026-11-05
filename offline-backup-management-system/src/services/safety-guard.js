const { countFilesAndBytes } = require('../core/fs-utils');

class SafetyGuard {
  constructor({ config, logger }) {
    this.config = config.safetyGuard;
    this.logger = logger;
  }

  async verify(stagePath) {
    const stats = await countFilesAndBytes(stagePath);

    this.logger.line('Safety guard:');
    this.logger.line(`  Files       : ${stats.files}`);
    this.logger.line(`  Total bytes : ${stats.bytes}`);

    if (stats.files < this.config.minFiles) {
      throw new Error([
        'Batch rejected by safety guard.',
        `Reason: fewer than ${this.config.minFiles} files.`,
        'Developer Done and back_up_worm were not changed.',
        'Remote transfer queue has been kept for review.'
      ].join('\n'));
    }

    if (stats.bytes < this.config.minBytes) {
      throw new Error([
        'Batch rejected by safety guard.',
        `Reason: batch is smaller than ${this.config.minBytes} bytes.`,
        'Developer Done and back_up_worm were not changed.',
        'Remote transfer queue has been kept for review.'
      ].join('\n'));
    }

    this.logger.line('Safety guard passed.');
  }
}

module.exports = {
  SafetyGuard
};

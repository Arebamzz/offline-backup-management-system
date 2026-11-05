const fs = require('fs');
const path = require('path');

class LocalLock {
  constructor({ lockFile, runner }) {
    this.lockFile = lockFile;
    this.runner = runner;
    this.fd = null;
  }

  async acquire() {
    await fs.promises.mkdir(path.dirname(this.lockFile), {
      recursive: true,
      mode: 0o750
    });

    this.fd = fs.openSync(this.lockFile, 'w', 0o600);

    const result = await this.runner.run('flock', ['-n', '3'], {
      extraFd: this.fd,
      captureStderr: true,
      streamOutput: false,
      check: false
    });

    if (result.exitCode !== 0) {
      this.release();
      return false;
    }

    return true;
  }

  release() {
    if (this.fd !== null) {
      fs.closeSync(this.fd);
      this.fd = null;
    }
  }
}

module.exports = {
  LocalLock
};

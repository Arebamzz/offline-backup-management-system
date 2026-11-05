const fs = require('fs');
const path = require('path');
const { buildSshArgs } = require('../core/ssh-options');

class RemoteBackupService {
  constructor({ config, runner }) {
    this.config = config;
    this.runner = runner;
    this.scriptsRoot = path.resolve(__dirname, '..', 'remote-scripts');
  }

  async prepareBatch(requestedBatch) {
    const script = this.readScript('prepare-batch.sh');
    const result = await this.runScript(script, [
      requestedBatch,
      this.config.remote.base,
      this.config.remote.inProgressPath,
      this.config.remote.queueRoot,
      this.config.remote.lockFile,
      ...this.config.remote.replacementDirs
    ], { capture: true });

    return result.stdout.trim();
  }

  async copyQueueToDone(batch) {
    const script = this.readScript('copy-queue-to-done.sh');
    await this.runScript(script, [
      batch,
      this.config.remote.queueRoot,
      this.config.remote.doneRoot,
      String(this.config.developerDone.reserveBytes)
    ]);
  }

  async clearQueue(batch) {
    const script = this.readScript('clear-queue.sh');
    await this.runScript(script, [
      batch,
      this.config.remote.queueRoot,
      this.config.remote.doneRoot
    ]);
  }

  readScript(fileName) {
    return fs.readFileSync(path.join(this.scriptsRoot, fileName), 'utf8');
  }

  runScript(script, args, options = {}) {
    const sshArgs = [
      ...buildSshArgs(this.config.ssh),
      this.config.remote.host,
      'bash',
      '-s',
      '--',
      ...args
    ];

    return this.runner.run('ssh', sshArgs, {
      input: script,
      captureStdout: Boolean(options.capture),
      captureStderr: Boolean(options.capture),
      streamOutput: !options.capture
    });
  }
}

module.exports = {
  RemoteBackupService
};

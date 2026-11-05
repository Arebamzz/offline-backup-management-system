const { buildRsyncRemoteShell } = require('../core/ssh-options');

class RsyncService {
  constructor({ config, runner }) {
    this.config = config;
    this.runner = runner;
    this.remoteShell = buildRsyncRemoteShell(config.ssh);
  }

  async pullQueueToStage(remoteQueue, localStage) {
    await this.runner.run('rsync', [
      '-a',
      '--delete',
      '--partial',
      '--append-verify',
      '--info=progress2',
      '--stats',
      '--human-readable',
      '-e',
      this.remoteShell,
      `${this.config.remote.host}:${withTrailingSlash(remoteQueue)}`,
      withTrailingSlash(localStage)
    ]);
  }

  async verifyRemoteToLocal(remotePath, localPath) {
    const result = await this.runner.run('rsync', [
      '-rcn',
      '--delete',
      '--itemize-changes',
      '-e',
      this.remoteShell,
      `${this.config.remote.host}:${withTrailingSlash(remotePath)}`,
      withTrailingSlash(localPath)
    ], {
      captureStdout: true,
      captureStderr: true,
      streamOutput: false
    });

    return result.stdout;
  }
}

function withTrailingSlash(value) {
  return value.endsWith('/') ? value : `${value}/`;
}

module.exports = {
  RsyncService,
  withTrailingSlash
};

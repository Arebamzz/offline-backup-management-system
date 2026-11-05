const fs = require('fs');
const path = require('path');
const { ensureDir, exists, removePath, parseMode } = require('../core/fs-utils');

class LocalPublisher {
  constructor({ config, logger }) {
    this.config = config.local;
    this.logger = logger;
  }

  async prepareBatchPaths(batch) {
    const localStage = path.posix.join(this.config.stageRoot, batch);
    const localOld = path.posix.join(this.config.mount, `.backup_temp.old.${batch}`);

    await ensureDir(this.config.stageRoot, 0o750);
    await ensureDir(localStage, 0o750);

    return { localStage, localOld };
  }

  async recoverPreviousSwap(localOld) {
    if (!(await exists(localOld))) {
      return;
    }

    if (!(await exists(this.config.root))) {
      this.logger.line('Restoring previous local latest folder.');
      await fs.promises.rename(localOld, this.config.root);
      return;
    }

    throw new Error(`Old local recovery folder already exists: ${localOld}`);
  }

  async publishLatest(localStage, localOld) {
    const rootExists = await exists(this.config.root);

    if (!rootExists) {
      throw new Error(`Current local latest folder is missing: ${this.config.root}`);
    }

    await fs.promises.rename(this.config.root, localOld);

    try {
      await fs.promises.rename(localStage, this.config.root);
    } catch (error) {
      this.logger.line('ERROR: Could not publish the new local latest folder.');

      if (!(await exists(this.config.root)) && (await exists(localOld))) {
        await fs.promises.rename(localOld, this.config.root).catch(() => {});
      }

      throw error;
    }

    await removePath(localOld);

    try {
      await fs.promises.rmdir(this.config.stageRoot);
    } catch (error) {
      if (error.code !== 'ENOENT' && error.code !== 'ENOTEMPTY') {
        throw error;
      }
    }

    await fs.promises.chmod(this.config.root, parseMode(this.config.rootMode));
    this.logger.line('Local backup_temp replaced with latest verified batch.');
  }
}

module.exports = {
  LocalPublisher
};

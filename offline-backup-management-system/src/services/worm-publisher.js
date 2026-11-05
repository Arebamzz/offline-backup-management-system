const fs = require('fs');
const path = require('path');
const {
  chmodTree,
  countFilesAndBytes,
  ensureDir,
  exists,
  formatBytes,
  hasAnyFile,
  parseMode,
  removePath
} = require('../core/fs-utils');

class WormPublisher {
  constructor({ config, runner, logger }) {
    this.config = config;
    this.runner = runner;
    this.logger = logger;
  }

  async publish(requestedBatch) {
    const batchDate = requestedBatch.split('_')[0];
    const target = path.posix.join(this.config.worm.root, batchDate);
    const newBatch = path.posix.join(this.config.local.mount, `.worm_new_${requestedBatch}_${process.pid}`);
    const oldBatch = path.posix.join(this.config.local.mount, `.worm_old_${requestedBatch}_${process.pid}`);

    this.logger.line(`Publishing backup_temp to WORM batch: ${batchDate}`);

    if (!(await exists(this.config.local.root)) || !(await hasAnyFile(this.config.local.root))) {
      throw new Error('backup_temp is missing or empty.');
    }

    await this.ensureOwnedDirectory(
      this.config.worm.root,
      parseMode(this.config.worm.dirMode),
      this.config.worm.owner,
      this.config.worm.group
    );

    if ((await exists(newBatch)) || (await exists(oldBatch))) {
      throw new Error('Temporary WORM recovery directory exists.');
    }

    let movedLocalRoot = false;
    let movedOldTarget = false;

    try {
      await fs.promises.rename(this.config.local.root, newBatch);
      movedLocalRoot = true;

      await this.runner.run('chown', ['-R', `${this.config.worm.owner}:${this.config.worm.group}`, newBatch]);
      await chmodTree(newBatch, {
        dirMode: parseMode(this.config.worm.dirMode),
        fileMode: parseMode(this.config.worm.fileMode)
      });

      if (await exists(target)) {
        await fs.promises.rename(target, oldBatch);
        movedOldTarget = true;
      }

      await fs.promises.rename(newBatch, target);
      movedLocalRoot = false;

      await this.ensureOwnedDirectory(
        this.config.local.root,
        parseMode(this.config.local.rootMode),
        this.config.local.owner,
        this.config.local.group
      );

      if (movedOldTarget) {
        await removePath(oldBatch);
      }
    } catch (error) {
      if (movedOldTarget && !(await exists(target)) && (await exists(oldBatch))) {
        await fs.promises.rename(oldBatch, target).catch(() => {});
      }

      if (movedLocalRoot && !(await exists(this.config.local.root)) && (await exists(newBatch))) {
        await fs.promises.rename(newBatch, this.config.local.root).catch(() => {});
        await this.runner.run('chown', ['-R', `${this.config.local.owner}:${this.config.local.group}`, this.config.local.root], {
          check: false
        });
      }

      throw error;
    }

    const batches = await this.listRetainedBatchDates();

    while (batches.length > this.config.worm.keepDays) {
      const oldest = batches.shift();
      const oldestPath = path.posix.join(this.config.worm.root, oldest);
      this.logger.line(`Deleting oldest WORM batch: ${oldestPath}`);
      await removePath(oldestPath);
    }

    const stats = await countFilesAndBytes(target);
    this.logger.line('WORM publish completed.');
    this.logger.line(`Published batch: ${target}`);
    this.logger.line(`Batch files    : ${stats.files}`);
    this.logger.line(`Batch size     : ${formatBytes(stats.bytes)}`);
    this.logger.line(`Batches kept   : ${batches.length}`);
  }

  async listRetainedBatchDates() {
    if (!(await exists(this.config.worm.root))) {
      return [];
    }

    const entries = await fs.promises.readdir(this.config.worm.root, { withFileTypes: true });

    return entries
      .filter((entry) => entry.isDirectory() && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort();
  }

  async ensureOwnedDirectory(target, mode, owner, group) {
    await ensureDir(target, mode);
    await fs.promises.chmod(target, mode);
    await this.runner.run('chown', [`${owner}:${group}`, target]);
  }
}

module.exports = {
  WormPublisher
};

const path = require('path');
const { CommandError } = require('./core/command-runner');
const { epochSeconds, formatBatchLabel, formatLogDate } = require('./core/time');
const { CommandChecker } = require('./services/command-checker');
const { EmailReporter } = require('./services/email-reporter');
const { LanService } = require('./services/lan-service');
const { LocalDiskService } = require('./services/local-disk-service');
const { LocalLock } = require('./services/local-lock');
const { LocalPublisher } = require('./services/local-publisher');
const { RemoteBackupService } = require('./services/remote-backup-service');
const { RsyncService } = require('./services/rsync-service');
const { SafetyGuard } = require('./services/safety-guard');
const { WormPublisher } = require('./services/worm-publisher');

class BackupOrchestrator {
  constructor({ config, configPath, logger, runner }) {
    this.config = config;
    this.configPath = configPath;
    this.logger = logger;
    this.runner = runner;
    this.currentStep = 'Initializing backup process';
    this.state = {
      batch: '',
      requestedBatch: ''
    };

    this.commandChecker = new CommandChecker({ config, runner, logger });
    this.lan = new LanService({ config, runner, logger });
    this.localDisk = new LocalDiskService({ config, runner, logger });
    this.localLock = new LocalLock({ lockFile: config.local.lockFile, runner });
    this.localPublisher = new LocalPublisher({ config, logger });
    this.remote = new RemoteBackupService({ config, runner });
    this.rsync = new RsyncService({ config, runner });
    this.safetyGuard = new SafetyGuard({ config, logger });
    this.wormPublisher = new WormPublisher({ config, runner, logger });
    this.emailReporter = new EmailReporter({ config, runner, logger });
  }

  async run() {
    const startEpoch = epochSeconds();
    this.writeHeader();
    this.logger.line(`Config: ${this.configPath}`);

    try {
      await this.execute(startEpoch);
      return 0;
    } catch (error) {
      const exitCode = normalizeExitCode(error);
      await this.handleFailure(error, exitCode, startEpoch);
      return exitCode;
    } finally {
      await this.cleanup();
    }
  }

  async execute(startEpoch) {
    this.setStep('Checking required commands');
    await this.commandChecker.verify();

    this.setStep('Enabling LAN connection');
    await this.lan.enable();

    this.setStep('Verifying 4TB backup disk');
    await this.localDisk.verify();

    this.setStep('Acquiring local backup lock');
    const lockAcquired = await this.localLock.acquire();
    if (!lockAcquired) {
      this.logger.line('Another pull_backup.sh process is already running.');
      return;
    }

    this.state.requestedBatch = formatBatchLabel(new Date());

    this.setStep('Freezing Developer In_Progress');
    const prepareResult = await this.remote.prepareBatch(this.state.requestedBatch);

    if (prepareResult === 'NO_FILES') {
      this.logger.line('No files found in Developer In_Progress.');
      this.logger.line('Pull backup finished: nothing to transfer.');
      return;
    }

    if (!prepareResult.startsWith('BATCH:')) {
      throw new Error(`Unexpected Developer response:\n${prepareResult}`);
    }

    this.state.batch = prepareResult.slice('BATCH:'.length);

    const remoteQueue = path.posix.join(this.config.remote.queueRoot, this.state.batch);
    const remoteDone = this.config.remote.doneRoot;
    const { localStage, localOld } = await this.localPublisher.prepareBatchPaths(this.state.batch);

    await this.localPublisher.recoverPreviousSwap(localOld);

    this.logger.line(`Processing batch: ${this.state.batch}`);
    this.logger.line(`Pulling files into hidden staging: ${localStage}`);

    this.setStep('Pulling files to hidden local staging');
    await this.rsync.pullQueueToStage(remoteQueue, localStage);

    this.setStep('Verifying local staging checksum');
    const localDiff = await this.rsync.verifyRemoteToLocal(remoteQueue, localStage);
    if (localDiff.trim() !== '') {
      this.logger.line('ERROR: Local staging checksum verification failed.');
      this.logger.raw(localDiff);
      throw new Error('Local staging checksum verification failed.');
    }
    this.logger.line('Local staging checksum verification passed.');

    this.setStep('Running safety guard');
    await this.safetyGuard.verify(localStage);

    this.setStep('Publishing latest local backup_temp');
    await this.localPublisher.publishLatest(localStage, localOld);

    this.setStep('Replacing Developer Done with latest only');
    await this.remote.copyQueueToDone(this.state.batch);

    this.setStep('Verifying Developer Done checksum');
    const doneDiff = await this.rsync.verifyRemoteToLocal(remoteDone, this.config.local.root);
    if (doneDiff.trim() !== '') {
      this.logger.line('ERROR: Developer Done checksum verification failed.');
      this.logger.raw(doneDiff);
      this.logger.line('Remote transfer queue has been kept for recovery.');
      throw new Error('Developer Done checksum verification failed.');
    }
    this.logger.line('Developer Done checksum verification passed.');

    this.setStep('Publishing verified backup to WORM');
    this.logger.line('Publishing verified backup_temp to back_up_worm...');
    await this.wormPublisher.publish(this.state.batch);
    this.logger.line('back_up_worm publish completed.');

    this.setStep('Clearing verified remote transfer queue');
    await this.remote.clearQueue(this.state.batch);

    this.logger.line('==================================================');
    this.logger.line(`SUCCESS: Batch ${this.state.batch} completed.`);
    this.logger.line(`Local latest : ${this.config.local.root}`);
    this.logger.line(`Remote latest: ${remoteDone}`);
    this.logger.line(`Finish time: ${formatLogDate(new Date())}`);
    this.logger.line('==================================================');

    this.setStep('Sending SUCCESS email report');
    const sent = await this.emailReporter.send('SUCCESS', {
      batch: this.state.batch,
      startEpoch
    });

    if (!sent) {
      this.logger.line('WARNING: Backup completed successfully, but the SUCCESS email could not be sent.');
    }
  }

  async handleFailure(error, exitCode, startEpoch) {
    const command = error instanceof CommandError ? error.commandText : 'Unknown';

    this.logger.line('ERROR: pull_backup_v2.sh failed.');
    this.logger.line(`Step: ${this.currentStep}`);
    this.logger.line('Line: JavaScript orchestrator');
    this.logger.line(`Command: ${command}`);
    this.logger.line(`Exit code: ${exitCode}`);
    this.logger.line(`Failure time: ${formatLogDate(new Date())}`);
    this.logger.line(`Reason: ${error.message}`);

    if (error instanceof CommandError) {
      logCommandOutput(this.logger, 'stdout', error.stdout);
      logCommandOutput(this.logger, 'stderr', error.stderr);
    }

    const batchLabel = this.state.batch || this.state.requestedBatch || 'Unknown';
    const failureReason = truncate(
      `Exit code: ${exitCode}; command: ${command}; message: ${error.message}`.replace(/\s+/g, ' '),
      500
    );

    this.logger.line('Attempting to send FAILED email report...');
    const sent = await this.emailReporter.send('FAILED', {
      batch: batchLabel,
      startEpoch,
      failedStep: this.currentStep,
      failureReason
    });

    if (!sent) {
      this.logger.line('WARNING: FAILED email report could not be sent.');
    }
  }

  async cleanup() {
    this.setStep('Disabling LAN connection');

    try {
      await this.lan.disable();
    } catch (error) {
      this.logger.line(`WARNING: LAN cleanup failed: ${error.message}`);
    }

    this.localLock.release();
  }

  setStep(step) {
    this.currentStep = step;
    this.logger.line(`Step: ${step}`);
  }

  writeHeader() {
    this.logger.line('');
    this.logger.line('==================================================');
    this.logger.line(`Pull backup started: ${formatLogDate(new Date())}`);
    this.logger.line('==================================================');
  }
}

function normalizeExitCode(error) {
  if (Number.isInteger(error.exitCode) && error.exitCode > 0 && error.exitCode < 256) {
    return error.exitCode;
  }

  return 1;
}

function truncate(value, maxLength) {
  return value.length > maxLength ? value.slice(0, maxLength) : value;
}

function logCommandOutput(logger, name, output) {
  if (!output || output.trim() === '') {
    return;
  }

  logger.line(`Command ${name}:`);
  logger.raw(output.endsWith('\n') ? output : `${output}\n`);
}

module.exports = {
  BackupOrchestrator
};

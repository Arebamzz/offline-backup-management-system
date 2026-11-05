const fs = require('fs');
const path = require('path');
const {
  countFilesAndBytes,
  exists,
  formatBytes,
  listChildDirectories,
  listRelativeFiles
} = require('../core/fs-utils');
const {
  epochSeconds,
  formatReportDate,
  formatReportDay,
  humanDuration
} = require('../core/time');

class EmailReporter {
  constructor({ config, runner, logger }) {
    this.config = config;
    this.runner = runner;
    this.logger = logger;
  }

  async send(status, options = {}) {
    if (!(await this.emailAvailable())) {
      this.logger.line('WARNING: Email configuration is unavailable.');
      return false;
    }

    try {
      const report = await this.buildReport(status, options);
      const recipients = this.recipients();

      await this.runner.run(this.config.email.msmtpBin, recipients, {
        input: report,
        captureStderr: true,
        streamOutput: false
      });

      this.logger.line(`Email report sent to ${recipients.join(', ')}`);
      return true;
    } catch (error) {
      this.logger.line(`WARNING: Email report could not be sent: ${error.message}`);
      return false;
    }
  }

  async emailAvailable() {
    try {
      await fs.promises.access(this.config.email.msmtpBin, fs.constants.X_OK);
      await fs.promises.access(this.config.email.msmtpConfig, fs.constants.R_OK);
      return true;
    } catch {
      return false;
    }
  }

  async buildReport(status, options) {
    const batch = options.batch || 'Unknown';
    const startEpoch = options.startEpoch;
    const failedStep = options.failedStep || 'Unknown';
    const failureReason = options.failureReason || 'No failure reason supplied';
    const now = new Date();
    const finishEpoch = epochSeconds(now);
    const startTime = Number.isInteger(startEpoch)
      ? formatReportDate(new Date(startEpoch * 1000))
      : 'Not available';
    const duration = Number.isInteger(startEpoch)
      ? humanDuration(finishEpoch - startEpoch)
      : 'Not available';

    const subject = status === 'SUCCESS'
      ? `[OFFLINE BACKUP] SUCCESS | ${formatReportDay(now)} | Batch: ${batch}`
      : `[OFFLINE BACKUP] FAILED | ${formatReportDay(now)} | Action Required`;

    const lines = [
      `From: ${this.config.email.from}`,
      `To: ${this.recipients().join(', ')}`,
      `Date: ${now.toUTCString()}`,
      `Subject: ${subject}`,
      'MIME-Version: 1.0',
      'Content-Type: text/plain; charset=UTF-8',
      '',
      '========================================================',
      'OFFLINE BACKUP DAILY REPORT',
      '========================================================',
      '',
      `Status          : ${status}`,
      `Server          : ${await this.hostname()}`,
      `Batch           : ${batch}`,
      `Start Time      : ${startTime}`,
      `Finish Time     : ${formatReportDate(now)}`,
      `Duration        : ${duration}`,
      ''
    ];

    if (status === 'SUCCESS') {
      await this.appendSuccessReport(lines, batch);
    } else {
      this.appendFailureReport(lines, failedStep, failureReason);
    }

    lines.push(
      '',
      '========================================================',
      'This is an automated email from the Offline Backup System.',
      'Please do not reply.',
      '========================================================',
      ''
    );

    return `${lines.join('\n')}`;
  }

  async appendSuccessReport(lines, batch) {
    const batchDate = batch.split('_')[0];
    const batchDir = path.posix.join(this.config.worm.root, batchDate);

    if (!(await exists(batchDir))) {
      throw new Error(`WORM batch missing for email report: ${batchDir}`);
    }

    const total = await countFilesAndBytes(batchDir);

    lines.push(
      '========================================================',
      'VERIFICATION',
      '========================================================',
      '',
      '[OK] Transfer Queue Completed',
      '[OK] Local Checksum Verified',
      '[OK] Safety Guard Passed',
      '[OK] Developer Done Updated',
      '[OK] Developer Done Checksum Verified',
      '[OK] Offline WORM Published',
      '[OK] WORM Retention Updated',
      '',
      '========================================================',
      'BACKUP SUMMARY',
      '========================================================',
      '',
      `Total Files     : ${total.files}`,
      `Total Size      : ${formatBytes(total.bytes)}`,
      ''
    );

    const directories = await listChildDirectories(batchDir);
    for (const directory of directories) {
      const folderName = path.posix.basename(directory);
      const stats = await countFilesAndBytes(directory);
      const files = await listRelativeFiles(directory);

      lines.push(
        '--------------------------------------------------------',
        folderName,
        `Files : ${stats.files}`,
        `Size  : ${formatBytes(stats.bytes)}`,
        ''
      );

      for (const file of files) {
        lines.push(`- ${file}`);
      }

      lines.push('');
    }

    lines.push(
      '========================================================',
      'CURRENT WORM RETENTION',
      '========================================================',
      ''
    );

    for (const retainedBatch of await this.listRetainedBatchDates()) {
      lines.push(`[OK] ${retainedBatch}`);
    }

    lines.push(
      '',
      '========================================================',
      'STORAGE INFORMATION',
      '========================================================',
      ''
    );

    const df = await this.runner.run('df', ['-h', '--output=size,used,avail,pcent,target', this.config.local.mount], {
      captureStdout: true,
      streamOutput: false,
      check: false
    });

    if (df.exitCode === 0) {
      lines.push(df.stdout.trimEnd());
    } else {
      lines.push('Storage information unavailable.');
    }
  }

  appendFailureReport(lines, failedStep, failureReason) {
    lines.push(
      '========================================================',
      'FAILED STEP',
      '========================================================',
      '',
      `Step            : ${failedStep}`,
      `Reason          : ${failureReason}`,
      '',
      '========================================================',
      'PROTECTION STATUS',
      '========================================================',
      '',
      '[OK] Previous successful backup remains protected',
      '[OK] Existing WORM backup remains unchanged',
      '[OK] Transfer Queue retained for investigation',
      '',
      '========================================================',
      'ACTION REQUIRED',
      '========================================================',
      '',
      'Manual investigation is required before the next run.'
    );
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

  async hostname() {
    const result = await this.runner.run('hostname', [], {
      captureStdout: true,
      streamOutput: false,
      check: false
    });

    return result.exitCode === 0 ? result.stdout.trim() : 'Unknown';
  }

  recipients() {
    return Array.isArray(this.config.email.to)
      ? this.config.email.to
      : [this.config.email.to];
  }
}

module.exports = {
  EmailReporter
};

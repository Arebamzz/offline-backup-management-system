#!/usr/bin/env node

const { BackupOrchestrator } = require('../src/backup-orchestrator');
const { loadConfig, usage } = require('../src/config');
const { CommandRunner } = require('../src/core/command-runner');
const { FileLogger } = require('../src/core/file-logger');

async function main() {
  process.umask(0o077);

  if (process.argv.includes('--help') || process.argv.includes('-h')) {
    process.stdout.write(usage());
    return 0;
  }

  const { config, configPath } = loadConfig(process.argv.slice(2));
  const logger = new FileLogger(config.local.logFile, {
    mirrorToConsole: config.logging.mirrorToConsole
  });

  try {
    const runner = new CommandRunner(logger);
    const orchestrator = new BackupOrchestrator({
      config,
      configPath,
      logger,
      runner
    });

    return await orchestrator.run();
  } finally {
    await logger.close();
  }
}

main()
  .then((exitCode) => {
    process.exit(exitCode);
  })
  .catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exit(1);
  });

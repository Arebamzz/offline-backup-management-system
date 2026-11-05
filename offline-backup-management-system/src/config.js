const fs = require('fs');
const path = require('path');

function usage() {
  return [
    'Usage: pull-backup [--config <path>]',
    '',
    'Environment:',
    '  PULL_BACKUP_CONFIG  Alternative config path.',
    '  NODE_BIN            Node executable used by pull_backup_v2.sh.',
    ''
  ].join('\n');
}

function loadConfig(argv) {
  const configPath = resolveConfigPath(argv);
  const raw = fs.readFileSync(configPath, 'utf8');
  const config = withDerivedDefaults(JSON.parse(raw));

  validateConfig(config, configPath);

  return { config, configPath };
}

function resolveConfigPath(argv) {
  let cliPath;

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (arg === '--config') {
      cliPath = argv[index + 1];
      if (!cliPath) {
        throw new Error(`Missing value for --config.\n${usage()}`);
      }
      index += 1;
      continue;
    }

    if (arg.startsWith('--config=')) {
      cliPath = arg.slice('--config='.length);
      if (!cliPath) {
        throw new Error(`Missing value for --config.\n${usage()}`);
      }
      continue;
    }

    throw new Error(`Unknown argument: ${arg}\n${usage()}`);
  }

  const requestedPath = cliPath || process.env.PULL_BACKUP_CONFIG || path.resolve(__dirname, '..', 'config', 'pull-backup.json');
  return path.resolve(requestedPath);
}

function withDerivedDefaults(config) {
  const next = structuredClone(config);

  next.remote = next.remote || {};
  next.local = next.local || {};
  next.ssh = next.ssh || {};
  next.lan = next.lan || {};
  next.safetyGuard = next.safetyGuard || {};
  next.developerDone = next.developerDone || {};
  next.worm = next.worm || {};
  next.email = next.email || {};
  next.logging = next.logging || {};

  if (next.remote.base) {
    next.remote.inProgressPath = next.remote.inProgressPath || path.posix.join(next.remote.base, 'In_Progress');
    next.remote.queueRoot = next.remote.queueRoot || path.posix.join(next.remote.inProgressPath, '.Transfer_Queue');
    next.remote.lockFile = next.remote.lockFile || path.posix.join(next.remote.base, '.FTP.lock');
  }

  if (next.local.mount) {
    next.local.root = next.local.root || path.posix.join(next.local.mount, 'backup_temp');
    next.local.stageRoot = next.local.stageRoot || path.posix.join(next.local.mount, '.pull_staging');
    next.worm.root = next.worm.root || path.posix.join(next.local.mount, 'back_up_worm');
  }

  next.remote.replacementDirs = next.remote.replacementDirs || [];
  next.ssh.connectTimeoutSeconds = next.ssh.connectTimeoutSeconds ?? 30;
  next.ssh.identitiesOnly = next.ssh.identitiesOnly ?? true;
  next.ssh.batchMode = next.ssh.batchMode ?? true;
  next.ssh.strictHostKeyChecking = next.ssh.strictHostKeyChecking ?? true;
  next.lan.enabled = next.lan.enabled ?? true;
  next.lan.waitSeconds = next.lan.waitSeconds ?? 90;
  next.lan.requireDefaultRoute = next.lan.requireDefaultRoute ?? true;
  next.safetyGuard.minFiles = next.safetyGuard.minFiles ?? 3;
  next.safetyGuard.minBytes = next.safetyGuard.minBytes ?? 100 * 1024 * 1024;
  next.developerDone.reserveBytes = next.developerDone.reserveBytes ?? 2 * 1024 * 1024 * 1024;
  next.worm.keepDays = next.worm.keepDays ?? 5;
  next.worm.dirMode = next.worm.dirMode || '750';
  next.worm.fileMode = next.worm.fileMode || '640';
  next.local.rootMode = next.local.rootMode || '750';
  next.logging.mirrorToConsole = next.logging.mirrorToConsole ?? false;
  next.requiredCommands = next.requiredCommands || [
    'bash',
    'ssh',
    'rsync',
    'findmnt',
    'mountpoint',
    'flock',
    'ip',
    'networkctl',
    'hostname',
    'df',
    'du',
    'chown'
  ];

  return next;
}

function validateConfig(config, configPath) {
  const errors = [];

  requireString(errors, config, 'remote.host');
  requireString(errors, config, 'remote.base');
  requireString(errors, config, 'remote.queueRoot');
  requireString(errors, config, 'remote.doneRoot');
  requireString(errors, config, 'remote.inProgressPath');
  requireString(errors, config, 'remote.lockFile');
  requireString(errors, config, 'local.mount');
  requireString(errors, config, 'local.root');
  requireString(errors, config, 'local.stageRoot');
  requireString(errors, config, 'local.expectedUuid');
  requireString(errors, config, 'local.lockFile');
  requireString(errors, config, 'local.logFile');
  requireString(errors, config, 'ssh.key');
  requireString(errors, config, 'ssh.knownHosts');
  requireString(errors, config, 'worm.root');
  requireString(errors, config, 'worm.owner');
  requireString(errors, config, 'worm.group');
  requireString(errors, config, 'email.from');
  requireStringOrStringArray(errors, config, 'email.to');
  requireString(errors, config, 'email.msmtpBin');
  requireString(errors, config, 'email.msmtpConfig');
  requirePositiveInteger(errors, config, 'ssh.connectTimeoutSeconds');
  requirePositiveInteger(errors, config, 'lan.waitSeconds');
  requirePositiveInteger(errors, config, 'safetyGuard.minFiles');
  requirePositiveInteger(errors, config, 'safetyGuard.minBytes');
  requirePositiveInteger(errors, config, 'developerDone.reserveBytes');
  requirePositiveInteger(errors, config, 'worm.keepDays');

  if (config.lan.enabled) {
    requireString(errors, config, 'lan.interface');
    requireString(errors, config, 'lan.ipv4');
  }

  if (!Array.isArray(config.remote.replacementDirs)) {
    errors.push('remote.replacementDirs must be an array.');
  } else {
    for (const directory of config.remote.replacementDirs) {
      if (typeof directory !== 'string' || directory.trim() === '' || directory.startsWith('/')) {
        errors.push('remote.replacementDirs entries must be non-empty relative paths.');
      }
    }
  }

  if (!Array.isArray(config.requiredCommands)) {
    errors.push('requiredCommands must be an array.');
  }

  if (errors.length > 0) {
    throw new Error(`Invalid backup config: ${configPath}\n- ${errors.join('\n- ')}`);
  }
}

function requireString(errors, config, key) {
  const value = readPath(config, key);
  if (typeof value !== 'string' || value.trim() === '') {
    errors.push(`${key} must be a non-empty string.`);
  }
}

function requireStringOrStringArray(errors, config, key) {
  const value = readPath(config, key);
  const validString = typeof value === 'string' && value.trim() !== '';
  const validArray = Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'string' && item.trim() !== '');

  if (!validString && !validArray) {
    errors.push(`${key} must be a non-empty string or array of strings.`);
  }
}

function requirePositiveInteger(errors, config, key) {
  const value = readPath(config, key);
  if (!Number.isInteger(value) || value <= 0) {
    errors.push(`${key} must be a positive integer.`);
  }
}

function readPath(config, key) {
  return key.split('.').reduce((current, part) => current && current[part], config);
}

module.exports = {
  loadConfig,
  usage
};

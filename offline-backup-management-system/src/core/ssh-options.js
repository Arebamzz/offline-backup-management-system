const { quoteArg } = require('./command-runner');

function buildSshArgs(sshConfig) {
  const args = [
    '-i',
    sshConfig.key,
    '-o',
    optionValue('IdentitiesOnly', sshConfig.identitiesOnly),
    '-o',
    optionValue('BatchMode', sshConfig.batchMode),
    '-o',
    optionValue('StrictHostKeyChecking', sshConfig.strictHostKeyChecking),
    '-o',
    `UserKnownHostsFile=${sshConfig.knownHosts}`,
    '-o',
    `ConnectTimeout=${sshConfig.connectTimeoutSeconds}`
  ];

  return args;
}

function buildRsyncRemoteShell(sshConfig) {
  return [
    'ssh',
    '-i',
    sshConfig.key,
    '-o',
    optionValue('IdentitiesOnly', sshConfig.identitiesOnly),
    '-o',
    optionValue('BatchMode', sshConfig.batchMode),
    '-o',
    optionValue('StrictHostKeyChecking', sshConfig.strictHostKeyChecking),
    '-o',
    `UserKnownHostsFile=${sshConfig.knownHosts}`,
    '-o',
    `ConnectTimeout=${sshConfig.connectTimeoutSeconds}`
  ].map(quoteArg).join(' ');
}

function optionValue(name, value) {
  return `${name}=${value ? 'yes' : 'no'}`;
}

module.exports = {
  buildRsyncRemoteShell,
  buildSshArgs
};

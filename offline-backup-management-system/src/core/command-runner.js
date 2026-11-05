const { spawn } = require('child_process');

class CommandError extends Error {
  constructor(message, details) {
    super(message);
    this.name = 'CommandError';
    this.command = details.command;
    this.args = details.args || [];
    this.commandText = commandText(this.command, this.args);
    this.exitCode = details.exitCode;
    this.signal = details.signal;
    this.stdout = details.stdout || '';
    this.stderr = details.stderr || '';
    this.cause = details.cause;
  }
}

class CommandRunner {
  constructor(logger) {
    this.logger = logger;
  }

  run(command, args = [], options = {}) {
    const {
      input,
      captureStdout = false,
      captureStderr = false,
      streamOutput = true,
      check = true,
      extraFd,
      env = process.env
    } = options;

    return new Promise((resolve, reject) => {
      const stdio = ['pipe', 'pipe', 'pipe'];

      if (extraFd !== undefined) {
        stdio[3] = extraFd;
      }

      let child;
      let stdout = '';
      let stderr = '';

      try {
        child = spawn(command, args, { env, stdio });
      } catch (error) {
        reject(new CommandError(`Could not start command: ${command}`, {
          command,
          args,
          cause: error
        }));
        return;
      }

      child.on('error', (error) => {
        reject(new CommandError(`Could not start command: ${command}`, {
          command,
          args,
          cause: error
        }));
      });

      child.stdout.on('data', (chunk) => {
        const text = chunk.toString();
        if (captureStdout) {
          stdout += text;
        }
        if (streamOutput) {
          this.logger.raw(text);
        }
      });

      child.stderr.on('data', (chunk) => {
        const text = chunk.toString();
        if (captureStderr) {
          stderr += text;
        }
        if (streamOutput) {
          this.logger.raw(text);
        }
      });

      if (input !== undefined) {
        child.stdin.end(input);
      } else {
        child.stdin.end();
      }

      child.on('close', (exitCode, signal) => {
        const result = { exitCode, signal, stdout, stderr };

        if (check && exitCode !== 0) {
          reject(new CommandError(
            `Command failed with exit code ${exitCode}: ${commandText(command, args)}`,
            { command, args, exitCode, signal, stdout, stderr }
          ));
          return;
        }

        resolve(result);
      });
    });
  }
}

function commandText(command, args) {
  return [command, ...args].map(quoteArg).join(' ');
}

function quoteArg(value) {
  const text = String(value);
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(text)) {
    return text;
  }
  return `'${text.replace(/'/g, `'\\''`)}'`;
}

module.exports = {
  CommandError,
  CommandRunner,
  commandText,
  quoteArg
};

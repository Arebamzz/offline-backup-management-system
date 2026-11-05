const fs = require('fs');
const path = require('path');

class FileLogger {
  constructor(filePath, options = {}) {
    this.filePath = filePath;
    this.mirrorToConsole = Boolean(options.mirrorToConsole);

    fs.mkdirSync(path.dirname(filePath), { recursive: true, mode: 0o750 });
    this.stream = fs.createWriteStream(filePath, {
      flags: 'a',
      mode: 0o600
    });
  }

  line(message = '') {
    this.raw(`${message}\n`);
  }

  raw(message) {
    this.stream.write(message);

    if (this.mirrorToConsole) {
      process.stdout.write(message);
    }
  }

  close() {
    return new Promise((resolve) => {
      this.stream.end(resolve);
    });
  }
}

module.exports = {
  FileLogger
};

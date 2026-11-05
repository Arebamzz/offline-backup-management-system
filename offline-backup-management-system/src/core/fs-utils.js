const fs = require('fs');
const path = require('path');

async function exists(target) {
  try {
    await fs.promises.access(target);
    return true;
  } catch {
    return false;
  }
}

async function ensureDir(target, mode) {
  await fs.promises.mkdir(target, { recursive: true, mode });
}

async function hasAnyFile(root) {
  const stack = [root];

  while (stack.length > 0) {
    const current = stack.pop();
    let entries;

    try {
      entries = await fs.promises.readdir(current, { withFileTypes: true });
    } catch (error) {
      if (error.code === 'ENOENT') {
        return false;
      }
      throw error;
    }

    for (const entry of entries) {
      const entryPath = path.posix.join(current, entry.name);
      if (entry.isFile()) {
        return true;
      }
      if (entry.isDirectory()) {
        stack.push(entryPath);
      }
    }
  }

  return false;
}

async function countFilesAndBytes(root) {
  const stack = [root];
  let files = 0;
  let bytes = 0;

  while (stack.length > 0) {
    const current = stack.pop();
    const entries = await fs.promises.readdir(current, { withFileTypes: true });

    for (const entry of entries) {
      const entryPath = path.posix.join(current, entry.name);

      if (entry.isDirectory()) {
        stack.push(entryPath);
        continue;
      }

      if (entry.isFile()) {
        files += 1;
        const stat = await fs.promises.stat(entryPath);
        bytes += stat.size;
      }
    }
  }

  return { files, bytes };
}

async function listChildDirectories(root) {
  const entries = await fs.promises.readdir(root, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.posix.join(root, entry.name))
    .sort();
}

async function listRelativeFiles(root) {
  const stack = [root];
  const files = [];

  while (stack.length > 0) {
    const current = stack.pop();
    const entries = await fs.promises.readdir(current, { withFileTypes: true });

    for (const entry of entries) {
      const entryPath = path.posix.join(current, entry.name);

      if (entry.isDirectory()) {
        stack.push(entryPath);
        continue;
      }

      if (entry.isFile()) {
        files.push(path.posix.relative(root, entryPath));
      }
    }
  }

  return files.sort();
}

async function chmodTree(root, modes) {
  const stack = [root];

  while (stack.length > 0) {
    const current = stack.pop();
    await fs.promises.chmod(current, modes.dirMode);

    const entries = await fs.promises.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.posix.join(current, entry.name);

      if (entry.isDirectory()) {
        stack.push(entryPath);
        continue;
      }

      if (entry.isFile()) {
        await fs.promises.chmod(entryPath, modes.fileMode);
      }
    }
  }
}

async function removePath(target) {
  await fs.promises.rm(target, {
    recursive: true,
    force: true
  });
}

function parseMode(value) {
  if (typeof value === 'number') {
    return value;
  }

  return Number.parseInt(String(value), 8);
}

function formatBytes(bytes) {
  const units = ['B', 'K', 'M', 'G', 'T', 'P'];
  let value = bytes;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  if (unitIndex === 0) {
    return `${value}B`;
  }

  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)}${units[unitIndex]}`;
}

module.exports = {
  chmodTree,
  countFilesAndBytes,
  ensureDir,
  exists,
  formatBytes,
  hasAnyFile,
  listChildDirectories,
  listRelativeFiles,
  parseMode,
  removePath
};

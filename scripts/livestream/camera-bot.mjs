#!/usr/bin/env node
import { createRequire } from 'node:module';
import net from 'node:net';

const require = createRequire(import.meta.url);
const mineflayer = require('mineflayer');
const { mineflayer: mineflayerViewer } = require('prismarine-viewer');

const DEFAULTS = {
  host: '127.0.0.1',
  serverPort: 25565,
  viewerPort: 3007,
  username: 'CameraSpike',
  version: '1.21.6',
};

function usage() {
  console.log(`Usage: node camera-bot.mjs [options]

Options:
  --host <host>           Minecraft server host (default: ${DEFAULTS.host})
  --server-port <port>    Minecraft server port (default: ${DEFAULTS.serverPort})
  --viewer-port <port>    Prismarine Viewer HTTP port (default: ${DEFAULTS.viewerPort})
  --username <name>       Offline camera bot username (default: ${DEFAULTS.username})
  --version <version>     Minecraft protocol version (default: ${DEFAULTS.version})
  --help                  Show this help`);
}

function parseArgs(argv) {
  const config = { ...DEFAULTS };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) {
        throw new Error(`Missing value for ${arg}`);
      }
      i += 1;
      return value;
    };

    switch (arg) {
      case '--host':
        config.host = next();
        break;
      case '--server-port':
        config.serverPort = Number.parseInt(next(), 10);
        break;
      case '--viewer-port':
        config.viewerPort = Number.parseInt(next(), 10);
        break;
      case '--username':
        config.username = next();
        break;
      case '--version':
        config.version = next();
        break;
      case '--help':
      case '-h':
        usage();
        process.exit(0);
        break;
      default:
        throw new Error(`Unknown argument: ${arg}`);
    }
  }

  for (const [name, value] of [
    ['server-port', config.serverPort],
    ['viewer-port', config.viewerPort],
  ]) {
    if (!Number.isInteger(value) || value <= 0 || value > 65535) {
      throw new Error(`Invalid ${name}: ${value}`);
    }
  }

  return config;
}

function emit(event) {
  console.log(JSON.stringify(event));
}

function waitForPort(host, port, timeoutMs) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = net.createConnection({ host, port });

      socket.once('connect', () => {
        socket.end();
        resolve();
      });
      socket.once('error', () => {
        socket.destroy();
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timed out waiting for ${host}:${port}`));
          return;
        }
        setTimeout(attempt, 250);
      });
      socket.setTimeout(500, () => {
        socket.destroy();
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timed out waiting for ${host}:${port}`));
          return;
        }
        setTimeout(attempt, 250);
      });
    };

    attempt();
  });
}

let shuttingDown = false;
let byeEmitted = false;
let bot;

function emitBye(payload = {}) {
  if (byeEmitted) return;
  byeEmitted = true;
  emit({ event: 'BYE', ...payload });
}

function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  emitBye({ signal });

  if (bot) {
    try {
      bot.quit('camera prototype shutdown');
    } catch (error) {
      emit({ event: 'ERROR', stage: 'shutdown', message: String(error.message || error) });
    }
  }

  setTimeout(() => process.exit(0), 750).unref();
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

let config;
try {
  config = parseArgs(process.argv.slice(2));
} catch (error) {
  console.error(error.message);
  usage();
  process.exit(2);
}

bot = mineflayer.createBot({
  host: config.host,
  port: config.serverPort,
  username: config.username,
  auth: 'offline',
  version: config.version,
});

bot.once('spawn', async () => {
  try {
    mineflayerViewer(bot, { port: config.viewerPort, firstPerson: true });
    await waitForPort('127.0.0.1', config.viewerPort, 10_000);
    bot.chat('/gamemode spectator');
    emit({
      event: 'READY',
      port: config.viewerPort,
      version: config.version,
      username: config.username,
      viewerUrl: `http://127.0.0.1:${config.viewerPort}`,
    });
  } catch (error) {
    emit({
      event: 'ERROR',
      stage: 'viewer-start',
      message: String(error.message || error),
    });
    process.exitCode = 1;
    bot.quit('viewer failed');
  }
});

bot.on('kicked', (reason) => {
  emit({ event: 'ERROR', stage: 'kicked', message: String(reason) });
});

bot.on('error', (error) => {
  emit({ event: 'ERROR', stage: 'bot', message: String(error.message || error) });
});

bot.on('end', (reason) => {
  if (!shuttingDown) {
    process.exitCode = 1;
    emitBye({ reason: String(reason || 'disconnected'), exitCode: 1 });
    setTimeout(() => process.exit(1), 0);
    return;
  }

  process.exit(0);
});

#!/usr/bin/env node
/**
 * Replay collaborative build jobs through visible Mineflayer bot clients.
 *
 * This is intentionally separate from replay_headless_to_rcon.py. RCON is a
 * reliable invisible executor; this script is a watchability harness: the
 * agent usernames log in, chat their role/job lines, teleport near their work
 * chunks, and issue the block commands themselves.
 */

import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const require = createRequire(import.meta.url);
const PROJECT_ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../..');
const mineflayer = require(path.join(PROJECT_ROOT, 'mindcraft', 'node_modules', 'mineflayer'));

const DEFAULT_SIM_FOLDER =
  'snapshots/headless/20260606T042514Z_roman_colosseum_collab_roles_local_exact';
const DEFAULT_INTENT_ID = 'build-b7f86561fa2f';

function parseArgs(argv) {
  const args = {
    simFolder: DEFAULT_SIM_FOLDER,
    intentId: DEFAULT_INTENT_ID,
    host: process.env.MC_HOST || '127.0.0.1',
    port: Number.parseInt(process.env.MC_PORT || '25566', 10),
    mcVersion: process.env.MC_VERSION || process.env.MINECRAFT_VERSION || '1.21.6',
    throttleMs: 90,
    jobPauseMs: 900,
    label: null,
    dryRun: false,
    connectOnly: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--sim-folder') args.simFolder = argv[++i];
    else if (arg === '--intent-id') args.intentId = argv[++i];
    else if (arg === '--host') args.host = argv[++i];
    else if (arg === '--port') args.port = Number.parseInt(argv[++i], 10);
    else if (arg === '--mc-version') args.mcVersion = argv[++i];
    else if (arg === '--throttle-ms') args.throttleMs = Number.parseInt(argv[++i], 10);
    else if (arg === '--job-pause-ms') args.jobPauseMs = Number.parseInt(argv[++i], 10);
    else if (arg === '--label') args.label = argv[++i];
    else if (arg === '--dry-run') args.dryRun = true;
    else if (arg === '--connect-only') args.connectOnly = true;
    else if (arg === '--help' || arg === '-h') {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return args;
}

function printHelp() {
  console.log(`Usage:
  node scripts/minecraft/replay_collab_with_mineflayer.mjs \\
    --sim-folder snapshots/headless/<run> \\
  --intent-id build-... \\
    --host 127.0.0.1 --port 25566 --mc-version 1.21.6

Options:
  --mc-version V    Mineflayer protocol version (default MC_VERSION or 1.21.6)
  --throttle-ms N   Delay between bot-issued build commands (default 90)
  --job-pause-ms N  Delay between collaborative jobs (default 900)
  --label TEXT      Structure label used in bot chat (default: ledger structure_type)
  --connect-only    Connect named bots, announce online, then exit
  --dry-run         Parse and summarize without connecting bots
`);
}

function usernameFor(agentId) {
  const map = {
    alpha: 'Alpha',
    aurora: 'Aurora',
    fork: 'Fork',
    pixel: 'Pixel',
    rex: 'Rex',
    sentinel: 'Sentinel',
    vera: 'Vera',
  };
  return map[String(agentId).toLowerCase()] || String(agentId);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

async function readJson(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}

async function loadReplay(args) {
  const simFolder = path.resolve(PROJECT_ROOT, args.simFolder);
  const ledgerPath = path.join(simFolder, 'collaborative_builds', args.intentId, 'ledger.json');
  const ledger = await readJson(ledgerPath);
  const jobs = [];
  for (const job of ledger.jobs) {
    let script = null;
    if (job.role === 'builder' && job.script_path) {
      script = await readJson(path.join(simFolder, job.script_path));
    }
    jobs.push({ ...job, script });
  }
  return { simFolder, ledger, jobs };
}

function jobChat(ledger, job) {
  if (job.role === 'manager') {
    return `I am managing ${ledger.source_intent_id}: ${ledger.jobs.length} role jobs and ${ledger.total_source_commands} build commands.`;
  }
  if (job.role === 'resource_gatherer') {
    return `Resource job ${job.job_id}: staging ${materialsText(job.materials)}.`;
  }
  if (job.role === 'crafter') {
    return `Crafting job ${job.job_id}: preparing ${materialsText(job.materials)}.`;
  }
  if (job.role === 'builder') {
    return `Builder job ${job.job_id}: ${job.command_count} commands, ${job.total_blocks} blocks. Moving to my work zone.`;
  }
  if (job.role === 'inspector') {
    return `Inspection job ${job.job_id}: checking dimensions, gates, materials, and recognizable completion.`;
  }
  return `${job.title}: ${job.description}`;
}

function materialsText(materials) {
  const entries = Object.entries(materials || {}).slice(0, 4);
  if (!entries.length) return 'no block materials';
  const extra = Object.keys(materials || {}).length - entries.length;
  const base = entries.map(([name, count]) => `${count} ${name}`).join(', ');
  return extra > 0 ? `${base}, ${extra} more material types` : base;
}

function workPosition(job) {
  const b = job.bounds;
  if (!b) return { x: 60, y: 107, z: 136 };
  return {
    x: Math.round((b.min_x + b.max_x) / 2),
    y: Math.min(110, Math.max(66, b.max_y + 2)),
    z: Math.min(145, Math.max(6, b.max_z + 8)),
  };
}

function commandToMinecraft(command) {
  const p = command.position;
  if (command.kind === 'setblock') {
    return `/setblock ${p.x} ${p.y} ${p.z} minecraft:${normalizeBlock(command.block_type)}`;
  }
  if (command.kind === 'fill') {
    const r = command.region_to || command.position;
    return `/fill ${p.x} ${p.y} ${p.z} ${r.x} ${r.y} ${r.z} minecraft:${normalizeBlock(command.block_type)}`;
  }
  if (command.kind === 'wait') return null;
  return `/setblock ${p.x} ${p.y} ${p.z} minecraft:structure_void`;
}

function normalizeBlock(name) {
  if (!name) return 'stone';
  return String(name).trim().toLowerCase().replace(/^minecraft:/, '').replaceAll(' ', '_').replaceAll('-', '_');
}

async function connectBot(username, host, port, version) {
  const bot = mineflayer.createBot({
    host,
    port,
    version,
    username,
    auth: 'offline',
    hideErrors: false,
  });
  bot.on('kicked', (reason) => console.error(`[${username}] kicked: ${reason}`));
  bot.on('error', (err) => console.error(`[${username}] error: ${err?.message || err}`));
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`${username} spawn timeout`)), 30000);
    bot.once('spawn', () => {
      clearTimeout(timeout);
      resolve();
    });
    bot.once('end', () => reject(new Error(`${username} disconnected before spawn`)));
  });
  return bot;
}

async function safeChat(bot, text) {
  bot.chat(text.length > 240 ? `${text.slice(0, 237)}...` : text);
  await sleep(350);
}

async function main() {
  const args = parseArgs(process.argv);
  const { ledger, jobs } = await loadReplay(args);
  const label = args.label || ledger.structure_type || 'build';
  const owners = [...new Set(jobs.map((job) => usernameFor(job.owner_agent_id)))];
  const buildCommands = jobs.reduce(
    (count, job) => count + (job.script ? job.script.commands.length : 0),
    0,
  );
  console.log(
    `collab mineflayer replay: jobs=${jobs.length} owners=${owners.join(',')} build_commands=${buildCommands} version=${args.mcVersion}`,
  );

  if (args.dryRun) return;

  const bots = new Map();
  try {
    for (const username of owners) {
      console.log(`connecting ${username}...`);
      const bot = await connectBot(username, args.host, args.port, args.mcVersion);
      bots.set(username, bot);
      await safeChat(bot, `${username} online for collaborative ${label} replay.`);
      bot.chat('/gamemode creative @s');
      await sleep(250);
    }

    if (args.connectOnly) {
      console.log(`connected ${bots.size} bots; connect-only smoke complete`);
      return;
    }

    for (const job of jobs) {
      const username = usernameFor(job.owner_agent_id);
      const bot = bots.get(username);
      if (!bot) throw new Error(`missing bot for ${username}`);
      const pos = workPosition(job);
      bot.chat(`/tp @s ${pos.x} ${pos.y} ${pos.z}`);
      await sleep(350);
      await safeChat(bot, jobChat(ledger, job));
      if (job.script) {
        let sent = 0;
        for (const command of job.script.commands) {
          const text = commandToMinecraft(command);
          if (!text) {
            if (command.wait_seconds) await sleep(command.wait_seconds * 1000);
            continue;
          }
          bot.chat(text);
          bot.swingArm('right');
          sent += 1;
          if (sent % 100 === 0) {
            console.log(`${username} ${job.job_id}: sent ${sent}/${job.script.commands.length}`);
          }
          await sleep(args.throttleMs);
        }
      }
      await sleep(args.jobPauseMs);
    }

    const vera = bots.get('Vera') || [...bots.values()][0];
    await safeChat(vera, `Collaborative ${label} replay complete. Inspection handoff finished.`);
  } finally {
    for (const bot of bots.values()) {
      bot.quit('collaborative replay complete');
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

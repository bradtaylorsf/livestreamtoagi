#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '../..');

const args = new Set(process.argv.slice(2));
if (args.has('--help') || args.has('-h')) {
    console.log(`Usage:
  scripts/minecraft/setup-easy-spawn.mjs --write-access-only
  scripts/minecraft/setup-easy-spawn.mjs --terrain-only
  scripts/minecraft/setup-easy-spawn.mjs

Environment:
  SERVER_DIR       Paper server directory      (default: ./minecraft-server-easy)
  MINDCRAFT_DIR    Mindcraft checkout          (default: ./mindcraft)
  MC_HOST          Minecraft host              (default: 127.0.0.1)
  MC_PORT          Minecraft port              (default: SERVER_PORT or 25566)
  EASY_SETUP_BOT   Temporary op bot name       (default: WorldBuilder)
  EASY_SETUP_PLAYERS Space/comma player names  (default: character bot names)
  EASY_SETUP_OBSERVERS Extra human names to teleport into the safe meadow
  EASY_SETUP_OPERATORS Human names to op for gamemode/tp commands
  EASY_SETUP_SPECTATORS Human names to switch into spectator mode
`);
    process.exit(0);
}

const writeAccessOnly = args.has('--write-access-only');
const terrainOnly = args.has('--terrain-only');
const serverDir = path.resolve(process.env.SERVER_DIR || path.join(repoRoot, 'minecraft-server-easy'));
const mindcraftDir = path.resolve(process.env.MINDCRAFT_DIR || path.join(repoRoot, 'mindcraft'));
const setupBot = process.env.EASY_SETUP_BOT || 'WorldBuilder';
const host = process.env.MC_HOST || process.env.SERVER_HOST || '127.0.0.1';
const port = Number(process.env.MC_PORT || process.env.SERVER_PORT || 25566);
const minecraftVersion = process.env.MC_VERSION || '1.21.6';
const commandDelayMs = Number(process.env.EASY_SETUP_COMMAND_DELAY_MS || 250);
const onlineDelayMs = Number(process.env.EASY_SETUP_ONLINE_DELAY_MS || 0);
const players = parseNames(
    process.env.EASY_SETUP_PLAYERS || 'BridgeBot Alpha Vera Rex Aurora Pixel Fork Sentinel Grok',
);
const observers = parseNames(process.env.EASY_SETUP_OBSERVERS || '');
const operators = parseNames(process.env.EASY_SETUP_OPERATORS || '');
const spectators = parseNames(process.env.EASY_SETUP_SPECTATORS || '');

if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`Invalid MC_PORT/SERVER_PORT: ${process.env.MC_PORT || process.env.SERVER_PORT}`);
}

function parseNames(value) {
    return [...new Set(
        value
            .split(/[,\s]+/)
            .map((name) => name.trim())
            .filter(Boolean),
    )];
}

function offlineUuid(name) {
    const hash = crypto.createHash('md5').update(`OfflinePlayer:${name}`, 'utf8').digest();
    hash[6] = (hash[6] & 0x0f) | 0x30;
    hash[8] = (hash[8] & 0x3f) | 0x80;
    const hex = hash.toString('hex');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function readJsonArray(file) {
    try {
        const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
        return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
        if (error.code === 'ENOENT') return [];
        throw error;
    }
}

function writeJsonArray(file, rows) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, `${JSON.stringify(rows, null, 2)}\n`);
}

function upsertByName(rows, entry) {
    const index = rows.findIndex((row) => String(row.name || '').toLowerCase() === entry.name.toLowerCase());
    if (index >= 0) {
        rows[index] = { ...rows[index], ...entry };
    } else {
        rows.push(entry);
    }
}

function writeAccessFiles() {
    fs.mkdirSync(serverDir, { recursive: true });
    const accessNames = [...new Set([setupBot, ...players, ...observers, ...operators, ...spectators])];

    const whitelist = readJsonArray(path.join(serverDir, 'whitelist.json'));
    for (const name of accessNames) {
        upsertByName(whitelist, { uuid: offlineUuid(name), name });
    }
    writeJsonArray(path.join(serverDir, 'whitelist.json'), whitelist);

    const ops = readJsonArray(path.join(serverDir, 'ops.json'));
    for (const name of [setupBot, ...operators]) {
        upsertByName(ops, {
            uuid: offlineUuid(name),
            name,
            level: 4,
            bypassesPlayerLimit: true,
        });
    }
    writeJsonArray(path.join(serverDir, 'ops.json'), ops);

    console.log(`[easy-spawn] wrote ops.json/whitelist.json in ${serverDir}`);
}

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitForSpawn(bot, timeoutMs) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            cleanup();
            reject(new Error(`Timed out waiting for ${setupBot} to join ${host}:${port}`));
        }, timeoutMs);
        const cleanup = () => {
            clearTimeout(timer);
            bot.removeListener('spawn', onSpawn);
            bot.removeListener('kicked', onKicked);
            bot.removeListener('error', onError);
        };
        const onSpawn = () => {
            cleanup();
            resolve();
        };
        const onKicked = (reason) => {
            cleanup();
            reject(new Error(`${setupBot} was kicked: ${JSON.stringify(reason)}`));
        };
        const onError = (error) => {
            cleanup();
            reject(error);
        };
        bot.once('spawn', onSpawn);
        bot.once('kicked', onKicked);
        bot.once('error', onError);
    });
}

async function main() {
    writeAccessFiles();
    if (writeAccessOnly) return;

    const require = createRequire(path.join(mindcraftDir, 'package.json'));
    const mineflayer = require('mineflayer');
    const bot = mineflayer.createBot({
        host,
        port,
        username: setupBot,
        auth: 'offline',
        version: minecraftVersion,
    });

    bot.on('error', (error) => {
        console.error(`[easy-spawn] bot error: ${error.message || error}`);
    });
    bot.on('messagestr', (message) => {
        if (process.env.EASY_SETUP_VERBOSE === '1') {
            console.log(`[easy-spawn:chat] ${message}`);
        }
    });

    await waitForSpawn(bot, Number(process.env.EASY_SETUP_CONNECT_TIMEOUT_MS || 30000));

    const command = async (body) => {
        console.log(`[easy-spawn] ${body}`);
        bot.chat(body);
        await delay(commandDelayMs);
    };

    const terrainCommands = [
        '/gamerule doDaylightCycle false',
        '/gamerule doWeatherCycle false',
        '/gamerule doMobSpawning false',
        '/gamerule keepInventory true',
        '/gamerule spawnRadius 0',
        '/gamerule drowningDamage false',
        '/gamerule fallDamage false',
        '/gamerule freezeDamage false',
        '/difficulty peaceful',
        '/time set day',
        '/weather clear',
        '/setworldspawn 0 64 0',
        '/fill -24 64 -24 24 84 24 minecraft:air replace',
        '/fill -24 62 -24 24 62 24 minecraft:dirt replace',
        '/fill -22 63 -22 22 63 22 minecraft:grass_block replace',
        '/fill -23 64 -23 23 68 -23 minecraft:glass replace',
        '/fill -23 64 23 23 68 23 minecraft:glass replace',
        '/fill -23 64 -23 -23 68 23 minecraft:glass replace',
        '/fill 23 64 -23 23 68 23 minecraft:glass replace',
        '/fill -12 64 -12 -10 68 -10 minecraft:oak_log replace',
        '/fill -8 64 -12 -6 68 -10 minecraft:birch_log replace',
        '/fill -12 64 -8 -10 66 -6 minecraft:dirt replace',
        '/fill -8 64 -8 -6 66 -6 minecraft:cobblestone replace',
        '/fill 6 64 -12 8 66 -10 minecraft:sand replace',
        '/fill 10 64 -12 12 66 -10 minecraft:gravel replace',
        '/fill 10 64 5 10 68 5 minecraft:oak_log replace',
        '/fill 8 68 3 12 70 7 minecraft:oak_leaves replace',
        '/setblock 0 64 2 minecraft:crafting_table replace',
        '/setblock 1 64 2 minecraft:furnace replace',
        '/setblock -1 64 2 minecraft:chest replace',
        '/setblock 2 64 0 minecraft:torch replace',
        '/setblock -2 64 0 minecraft:torch replace',
    ];
    for (const body of terrainCommands) {
        await command(body);
    }

    if (!terrainOnly) {
        if (onlineDelayMs > 0) await delay(onlineDelayMs);
        const offsets = [
            [0, 64, 0],
            [2, 64, 0],
            [-2, 64, 0],
            [0, 64, 2],
            [0, 64, -2],
            [3, 64, 3],
            [-3, 64, 3],
            [3, 64, -3],
            [-3, 64, -3],
        ];
        const kitCommands = [
            '/spawnpoint @a 0 64 0',
            ...operators.map((name) => `/op ${name}`),
            ...players.map((name, index) => {
                const [x, y, z] = offsets[index % offsets.length];
                return `/tp ${name} ${x} ${y} ${z}`;
            }),
            ...observers.map((name) => `/tp ${name} 0 72 0`),
            ...spectators.map((name) => `/gamemode spectator ${name}`),
            '/spawnpoint @a 0 64 0',
            '/give @a minecraft:bread 16',
            '/give @a minecraft:oak_log 32',
            '/give @a minecraft:dirt 32',
            '/give @a minecraft:cobblestone 24',
            '/give @a minecraft:torch 16',
            '/give @a minecraft:crafting_table 1',
            '/give @a minecraft:stone_axe 1',
            '/give @a minecraft:stone_pickaxe 1',
        ];
        for (const body of kitCommands) {
            await command(body);
        }
    }

    bot.quit('easy spawn setup complete');
    await delay(250);
}

main().catch((error) => {
    console.error(`[easy-spawn] ${error.stack || error.message || error}`);
    process.exit(1);
});

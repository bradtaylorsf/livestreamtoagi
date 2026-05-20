// Read-only `!observe` perception query for E6-6 (#561).
//
// The action captures a schema-shaped perception snapshot and reports it over
// `perception.report`. It does not emit `action.result`: observing/inventory
// reads are queries, not mutating in-world actions.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import {
    DEFAULT_RADIUS_BLOCKS,
    inventorySnapshot,
    nearbyBlocks,
    nearbyEntities,
    perceptionObservation,
    PERCEPTION_SCOPES,
    poseFrom,
} from '../skills/perception.js';

const BRIDGE_REPORT_TIMEOUT_MS = 5000;

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function positiveNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : fallback;
}

function normalizedScope(value) {
    const scope = String(value || 'all').toLowerCase();
    return PERCEPTION_SCOPES.includes(scope) ? scope : 'all';
}

function bool(value) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') {
        return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
    }
    return value === 1;
}

function capturedTick(bot) {
    const tick = Number(
        (bot && bot.time && (bot.time.age ?? bot.time.timeOfDay)) ??
            (bot && (bot.tick ?? bot.captured_tick)),
    );
    return Number.isInteger(tick) && tick >= 0 ? tick : null;
}

function emptyInventory() {
    return { items: [], equipment: {}, used_slots: 0, total_slots: 0 };
}

function announce(agent, traceId, line, isError = false) {
    try {
        if (agent && typeof agent.openChat === 'function') agent.openChat(line);
    } catch {
        /* chat is cosmetic; never let it mask the bridge result */
    }
    const tagged = `[observe trace=${traceId}] ${line}`;
    if (isError) console.error(tagged);
    else console.log(tagged);
}

function bridgeErrorLine(prefix, err) {
    const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
    const detail = err && err.message ? err.message : String(err);
    return `${prefix} [${code}]: ${detail}`;
}

async function ensureBridge(agent, traceId) {
    await callBridge({
        service: 'bridge',
        method: 'ping',
        payload: { message: 'observe-preflight' },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
}

async function readObservation(agent, radius, scope, includeAir) {
    const bot = getBot(agent);
    const wantsBlocks = scope === 'all' || scope === 'nearby_blocks';
    const wantsEntities = scope === 'all' || scope === 'entities';
    const wantsInventory = scope === 'all' || scope === 'inventory';

    return perceptionObservation({
        pose: poseFrom(bot),
        blocks: wantsBlocks ? await nearbyBlocks(bot, radius, includeAir) : [],
        entities: wantsEntities ? nearbyEntities(bot, radius) : [],
        inventory: wantsInventory ? inventorySnapshot(bot, null, true) : emptyInventory(),
        radius,
        scope,
        includeAir,
        tick: capturedTick(bot),
    });
}

export const observeAction = {
    name: '!observe',
    description: 'Read nearby pose, blocks, entities, and inventory through perception.report.',
    params: {
        radius_blocks: {
            type: 'float',
            description: 'Optional perception radius in blocks.',
        },
        scope: {
            type: 'string',
            description: 'pose, nearby_blocks, entities, inventory, or all.',
        },
        include_air: {
            type: 'boolean',
            description: 'Whether nearby block results include air blocks.',
        },
    },
    perform: async function (agent, radius_blocks, scope, include_air) {
        const traceId = `trace-${randomUUID()}`;
        const radius = positiveNumber(radius_blocks, DEFAULT_RADIUS_BLOCKS);
        const requestedScope = normalizedScope(scope);
        const includeAir = bool(include_air);

        try {
            await ensureBridge(agent, traceId);
        } catch (err) {
            const line = bridgeErrorLine('bridge unavailable, safe-idling', err);
            announce(agent, traceId, line, true);
            return line;
        }

        try {
            const observation = await readObservation(agent, radius, requestedScope, includeAir);
            await callBridge({
                service: 'perception',
                method: 'report',
                payload: { observations: [observation] },
                deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
                agentId: agentId(agent),
                traceId,
            });
            const line =
                `observe ${requestedScope}: blocks=${observation.nearby_blocks.length}; ` +
                `entities=${observation.entities.length}; items=${observation.inventory.items.length}`;
            announce(agent, traceId, line);
            return line;
        } catch (err) {
            const line = bridgeErrorLine('observe report failed', err);
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default observeAction;

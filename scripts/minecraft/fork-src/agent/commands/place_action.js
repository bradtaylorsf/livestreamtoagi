// Verified `!place` action for E6-3 (#558).
//
// The action does not treat "command issued" as success. It reads the target
// block before and after placement, classifies the observed world state, sends
// the block observation over `perception.report`, then sends the terminal
// `action.result` over the E4-6 inbound channel.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import { classifyInterruption, messageFromError } from '../skills/action_interruption.js';
import {
    blockObservation,
    classifyPlace,
    normalizeBlockType,
    positionFrom,
    statusForBuildClass,
} from '../skills/building.js';

const DEFAULT_PLACE_TIMEOUT_MS = 10000;
const BRIDGE_REPORT_TIMEOUT_MS = 5000;

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function announce(agent, traceId, line, isError = false) {
    try {
        if (agent && typeof agent.openChat === 'function') agent.openChat(line);
    } catch {
        /* chat is cosmetic; never let it mask the verified outcome */
    }
    const tagged = `[place trace=${traceId}] ${line}`;
    if (isError) console.error(tagged);
    else console.log(tagged);
}

function bridgeErrorLine(prefix, err) {
    const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
    const detail = err && err.message ? err.message : String(err);
    return `${prefix} [${code}]: ${detail}`;
}

function parseJsonArgument(value, label) {
    if (typeof value !== 'string') return { value, error: null };
    const text = value.trim();
    if (!text) return { value: null, error: `${label} is required` };
    try {
        return { value: JSON.parse(text), error: null };
    } catch (err) {
        const detail = err && err.message ? err.message : String(err);
        return { value: null, error: `invalid_args: ${label} must be JSON: ${detail}` };
    }
}

function parsePositionArgument(value, label = 'position') {
    const parsed = parseJsonArgument(value, label);
    if (parsed.error) return { position: null, error: parsed.error };
    const position = positionFrom(parsed.value);
    if (!position) return { position: null, error: `invalid_args: ${label} must include finite x/y/z` };
    return { position, error: null };
}

async function ensureBridge(agent, traceId) {
    await callBridge({
        service: 'bridge',
        method: 'ping',
        payload: { message: 'building-preflight' },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
}

async function makeVec3(value) {
    const cell = positionFrom(value);
    if (!cell) return value;
    try {
        const mod = await import('vec3');
        const Vec3 = mod && (mod.Vec3 || (mod.default && mod.default.Vec3) || mod.default);
        if (typeof Vec3 === 'function') return new Vec3(cell.x, cell.y, cell.z);
    } catch {
        /* Test and static environments may not have the Mindcraft dependency. */
    }
    return cell;
}

async function readRawBlock(bot, position) {
    if (!bot || typeof bot.blockAt !== 'function') return null;
    return bot.blockAt(await makeVec3(position));
}

async function readBlockType(bot, position) {
    return normalizeBlockType(await readRawBlock(bot, position));
}

function faceVectorFrom(face) {
    const f = String(face || 'up').toLowerCase();
    const faces = {
        up: { x: 0, y: 1, z: 0 },
        top: { x: 0, y: 1, z: 0 },
        down: { x: 0, y: -1, z: 0 },
        bottom: { x: 0, y: -1, z: 0 },
        north: { x: 0, y: 0, z: -1 },
        south: { x: 0, y: 0, z: 1 },
        east: { x: 1, y: 0, z: 0 },
        west: { x: -1, y: 0, z: 0 },
    };
    return faces[f] || null;
}

function sourceSlotItem(bot, sourceSlot) {
    if (sourceSlot === undefined || sourceSlot === null || sourceSlot === '') return null;
    const slot = Number(sourceSlot);
    if (!Number.isInteger(slot) || slot < 0) return null;
    return bot && bot.inventory && Array.isArray(bot.inventory.slots)
        ? bot.inventory.slots[slot] || null
        : null;
}

function inventoryItems(bot) {
    if (!bot || !bot.inventory) return [];
    if (typeof bot.inventory.items === 'function') return bot.inventory.items();
    if (Array.isArray(bot.inventory.slots)) return bot.inventory.slots.filter(Boolean);
    return [];
}

function findInventoryItem(bot, blockType, sourceSlot) {
    const expected = normalizeBlockType(blockType);
    const slotted = sourceSlotItem(bot, sourceSlot);
    if (slotted) {
        return normalizeBlockType(slotted) === expected ? slotted : null;
    }
    return inventoryItems(bot).find((item) => normalizeBlockType(item) === expected) || null;
}

async function equipBlock(bot, blockType, sourceSlot) {
    if (!bot || typeof bot.equip !== 'function') {
        return { failureClass: 'tool-missing', detail: 'equip unavailable' };
    }
    const item = findInventoryItem(bot, blockType, sourceSlot);
    if (!item) return { failureClass: 'tool-missing', detail: `missing ${blockType} in inventory` };
    try {
        await bot.equip(item, 'hand');
        return { failureClass: null, detail: `equipped ${normalizeBlockType(item)}` };
    } catch (err) {
        const message = messageFromError(err);
        return { failureClass: classifyInterruption(err) || classifyError(message), detail: message };
    }
}

function classifyError(message) {
    const lower = String(message || '').toLowerCase();
    if (
        lower.includes('inventory') ||
        lower.includes('equip') ||
        lower.includes('missing') ||
        lower.includes('no item')
    ) {
        return 'tool-missing';
    }
    if (lower.includes('protect') || lower.includes('permission') || lower.includes('claim')) {
        return 'protected';
    }
    if (lower.includes('timed out') || lower.includes('timeout')) return 'timed-out';
    return 'blocked';
}

async function withTimeout(promise, timeoutMs) {
    let timer;
    try {
        return await Promise.race([
            promise,
            new Promise((_resolve, reject) => {
                timer = setTimeout(
                    () => reject(new Error(`place timed out after ${timeoutMs}ms`)),
                    timeoutMs,
                );
            }),
        ]);
    } finally {
        if (timer) clearTimeout(timer);
    }
}

async function placeBlockAt(bot, target, face, timeoutMs) {
    if (!bot || typeof bot.placeBlock !== 'function') {
        return { failureClass: 'blocked', detail: 'placeBlock unavailable' };
    }
    const faceVector = faceVectorFrom(face);
    if (!faceVector) return { failureClass: 'invalid', detail: `invalid face ${face}` };
    const referencePosition = {
        x: target.x - faceVector.x,
        y: target.y - faceVector.y,
        z: target.z - faceVector.z,
    };
    const referenceBlock = await readRawBlock(bot, referencePosition);
    if (!referenceBlock) {
        return { failureClass: 'blocked', detail: 'reference block unavailable' };
    }
    try {
        await withTimeout(bot.placeBlock(referenceBlock, await makeVec3(faceVector)), timeoutMs);
        return { failureClass: null, detail: `placed against ${normalizeBlockType(referenceBlock)}` };
    } catch (err) {
        const message = messageFromError(err);
        return { failureClass: classifyInterruption(err) || classifyError(message), detail: message };
    }
}

function outcomeDetail(outcomeClass, observation, extraDetail) {
    const position = observation.position
        ? `${observation.position.x},${observation.position.y},${observation.position.z}`
        : 'unknown';
    const suffix = extraDetail ? `; ${extraDetail}` : '';
    return (
        `${outcomeClass}: position=${position}; expected=${observation.expected_block_type}; ` +
        `before=${observation.before_block}; after=${observation.after_block}${suffix}`
    );
}

async function emitPlaceOutcome({
    agent,
    traceId,
    actionId,
    position,
    beforeBlock,
    afterBlock,
    expectedBlockType,
    outcomeClass,
    extraDetail,
}) {
    const observation = blockObservation({
        action: 'place',
        actionId,
        position,
        beforeBlock,
        afterBlock,
        expectedBlockType,
        outcomeClass,
    });
    const detail = outcomeDetail(outcomeClass, observation, extraDetail);
    await callBridge({
        service: 'perception',
        method: 'report',
        payload: { observations: [observation] },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    await callBridge({
        service: 'action',
        method: 'result',
        payload: {
            action_id: actionId,
            status: statusForBuildClass(outcomeClass),
            outcome_class: outcomeClass,
            detail,
        },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    return detail;
}

export const placeAction = {
    name: '!place',
    description: 'Place a block and report verified placed/blocked/protected/partial.',
    params: {
        action_id: {
            type: 'string',
            description: 'Caller-provided action id echoed in action.result.',
        },
        block_type: {
            type: 'string',
            description: 'Block type to place, for example stone or minecraft:oak_planks.',
        },
        position: {
            type: 'string',
            description: 'Target block cell as JSON with x/y/z coordinates.',
        },
        face: {
            type: 'string',
            description: 'Reference face to place against: up, down, north, south, east, west.',
        },
        source_slot: {
            type: 'int',
            description: 'Optional inventory slot containing the block to place.',
        },
    },
    perform: async function (agent, action_id, block_type, position, face, source_slot) {
        const traceId = `trace-${randomUUID()}`;
        const actionId =
            action_id === undefined || action_id === null || action_id === ''
                ? `place-${randomUUID()}`
                : String(action_id);
        const bot = getBot(agent);
        const parsedPosition = parsePositionArgument(position);
        const target = parsedPosition.position;
        const expectedBlockType = normalizeBlockType(block_type);
        const timeout = DEFAULT_PLACE_TIMEOUT_MS;

        try {
            await ensureBridge(agent, traceId);
        } catch (err) {
            const line = bridgeErrorLine('bridge unavailable, safe-idling', err);
            announce(agent, traceId, line, true);
            return line;
        }

        const missingActionId = action_id === undefined || action_id === null || action_id === '';
        const invalidBlock = !expectedBlockType || expectedBlockType === 'air';
        if (missingActionId || invalidBlock || !target) {
            const before = target ? await readBlockType(bot, target) : null;
            const invalidOutcomeClass = missingActionId
                ? 'wrong_args'
                : parsedPosition.error
                  ? 'invalid_args'
                  : 'invalid';
            try {
                const detail = await emitPlaceOutcome({
                    agent,
                    traceId,
                    actionId,
                    position: target,
                    beforeBlock: before,
                    afterBlock: before,
                    expectedBlockType,
                    outcomeClass: invalidOutcomeClass,
                    extraDetail: missingActionId
                        ? 'missing action_id'
                        : parsedPosition.error || 'invalid block_type or position',
                });
                announce(agent, traceId, `place ${actionId} ${detail}`, true);
                return `place ${actionId} ${detail}`;
            } catch (err) {
                const line = bridgeErrorLine(`place ${actionId} invalid but report failed`, err);
                announce(agent, traceId, line, true);
                return line;
            }
        }

        const before = await readBlockType(bot, target);
        const equipped = await equipBlock(bot, expectedBlockType, source_slot);
        let placement = equipped;
        if (!equipped.failureClass) {
            placement = await placeBlockAt(bot, target, face, timeout);
        }
        const after = await readBlockType(bot, target);
        const outcomeClass = classifyPlace({
            beforeBlock: before,
            afterBlock: after,
            blockType: expectedBlockType,
            failureClass: placement.failureClass,
        });

        try {
            const detail = await emitPlaceOutcome({
                agent,
                traceId,
                actionId,
                position: target,
                beforeBlock: before,
                afterBlock: after,
                expectedBlockType,
                outcomeClass,
                extraDetail: placement.detail,
            });
            const line = `place ${actionId} ${detail}`;
            announce(agent, traceId, line, outcomeClass !== 'placed');
            return line;
        } catch (err) {
            const line = bridgeErrorLine(`place ${actionId} completed but report failed`, err);
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default placeAction;

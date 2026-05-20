// Verified `!break` action for E6-3 (#558).
//
// The action reports success only when the target block is observed as gone
// after digging. It emits the post-action block observation through
// `perception.report` before the terminal `action.result`.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import {
    blockObservation,
    classifyBreak,
    isAirBlock,
    normalizeBlockType,
    positionFrom,
    statusForBuildClass,
} from '../skills/building.js';

const DEFAULT_BREAK_TIMEOUT_MS = 10000;
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
    const tagged = `[break trace=${traceId}] ${line}`;
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

function toolSlotItem(bot, toolSlot) {
    if (toolSlot === undefined || toolSlot === null || toolSlot === '') return null;
    const slot = Number(toolSlot);
    if (!Number.isInteger(slot) || slot < 0) return null;
    return bot && bot.inventory && Array.isArray(bot.inventory.slots)
        ? bot.inventory.slots[slot] || null
        : null;
}

async function equipTool(bot, toolSlot) {
    if (toolSlot === undefined || toolSlot === null || toolSlot === '') {
        return { failureClass: null, detail: '' };
    }
    if (!bot || typeof bot.equip !== 'function') {
        return { failureClass: 'tool-missing', detail: 'equip unavailable' };
    }
    const item = toolSlotItem(bot, toolSlot);
    if (!item) return { failureClass: 'tool-missing', detail: `missing tool slot ${toolSlot}` };
    try {
        await bot.equip(item, 'hand');
        return { failureClass: null, detail: `equipped ${normalizeBlockType(item)}` };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        return { failureClass: classifyError(message), detail: message };
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
                    () => reject(new Error(`break timed out after ${timeoutMs}ms`)),
                    timeoutMs,
                );
            }),
        ]);
    } finally {
        if (timer) clearTimeout(timer);
    }
}

async function digBlock(bot, block, timeoutMs) {
    if (!bot || typeof bot.dig !== 'function') {
        return { failureClass: 'blocked', detail: 'dig unavailable' };
    }
    try {
        await withTimeout(bot.dig(block), timeoutMs);
        return { failureClass: null, detail: `dug ${normalizeBlockType(block)}` };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        return { failureClass: classifyError(message), detail: message };
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

async function emitBreakOutcome({
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
        action: 'break',
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
            detail,
        },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    return detail;
}

export const breakAction = {
    name: '!break',
    description: 'Break a block and report verified removed/blocked/protected/partial.',
    params: {
        action_id: {
            type: 'string',
            description: 'Caller-provided action id echoed in action.result.',
        },
        position: {
            type: 'object',
            description: 'Target block cell with x/y/z coordinates.',
        },
        expected_block_type: {
            type: 'string',
            description: 'Optional expected block type at the target before digging.',
        },
        tool_slot: {
            type: 'number',
            description: 'Optional inventory slot containing the tool to use.',
        },
    },
    perform: async function (agent, action_id, position, expected_block_type, tool_slot) {
        const traceId = `trace-${randomUUID()}`;
        const actionId =
            action_id === undefined || action_id === null || action_id === ''
                ? `break-${randomUUID()}`
                : String(action_id);
        const bot = getBot(agent);
        const target = positionFrom(position);
        const requestedBlockType = normalizeBlockType(expected_block_type);

        try {
            await ensureBridge(agent, traceId);
        } catch (err) {
            const line = bridgeErrorLine('bridge unavailable, safe-idling', err);
            announce(agent, traceId, line, true);
            return line;
        }

        const missingActionId = action_id === undefined || action_id === null || action_id === '';
        if (missingActionId || !target) {
            try {
                const detail = await emitBreakOutcome({
                    agent,
                    traceId,
                    actionId,
                    position: target,
                    beforeBlock: null,
                    afterBlock: null,
                    expectedBlockType: requestedBlockType,
                    outcomeClass: 'invalid',
                    extraDetail: missingActionId ? 'missing action_id' : 'invalid position',
                });
                announce(agent, traceId, `break ${actionId} ${detail}`, true);
                return `break ${actionId} ${detail}`;
            } catch (err) {
                const line = bridgeErrorLine(`break ${actionId} invalid but report failed`, err);
                announce(agent, traceId, line, true);
                return line;
            }
        }

        const beforeRaw = await readRawBlock(bot, target);
        const before = normalizeBlockType(beforeRaw);
        const expectedBlockType = requestedBlockType || before;
        let breakAttempt = { failureClass: null, detail: '' };

        if (!beforeRaw || isAirBlock(before)) {
            breakAttempt = { failureClass: 'invalid', detail: 'target block is empty' };
        } else if (requestedBlockType && before !== requestedBlockType) {
            breakAttempt = {
                failureClass: 'invalid',
                detail: `expected ${requestedBlockType}, found ${before}`,
            };
        } else {
            const equipped = await equipTool(bot, tool_slot);
            breakAttempt = equipped.failureClass
                ? equipped
                : await digBlock(bot, beforeRaw, DEFAULT_BREAK_TIMEOUT_MS);
        }

        const after = await readBlockType(bot, target);
        const outcomeClass = classifyBreak({
            beforeBlock: before,
            afterBlock: after,
            expectedBlockType,
            failureClass: breakAttempt.failureClass,
        });

        try {
            const detail = await emitBreakOutcome({
                agent,
                traceId,
                actionId,
                position: target,
                beforeBlock: before,
                afterBlock: after,
                expectedBlockType,
                outcomeClass,
                extraDetail: breakAttempt.detail,
            });
            const line = `break ${actionId} ${detail}`;
            announce(agent, traceId, line, outcomeClass !== 'removed');
            return line;
        } catch (err) {
            const line = bridgeErrorLine(`break ${actionId} completed but report failed`, err);
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default breakAction;

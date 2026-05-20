// Verified `!buildFromPlan` action for E6-4 (#559).
//
// The action expands a structured plan into verified break/place steps, emits
// per-step block observations and action results, then performs a final world
// read to report actual-vs-intended structure completion.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import {
    blockObservation,
    classifyBreak,
    classifyPlace,
    isAirBlock,
    normalizeBlockType,
    positionFrom,
    statusForBuildClass,
} from '../skills/building.js';
import {
    classifyPlan,
    completionMetric,
    normalizePlan,
    statusForPlanClass,
    structureObservation,
} from '../skills/build_plan.js';

const DEFAULT_BUILD_TIMEOUT_MS = 30000;
const DEFAULT_STEP_TIMEOUT_MS = 10000;
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
    const tagged = `[build-from-plan trace=${traceId}] ${line}`;
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
        payload: { message: 'build-plan-preflight' },
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
    try {
        return bot.blockAt(await makeVec3(position));
    } catch {
        return null;
    }
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
        const message = err && err.message ? err.message : String(err);
        return { failureClass: classifyError(message), detail: message };
    }
}

async function equipTool(bot, toolSlot) {
    if (toolSlot === undefined || toolSlot === null || toolSlot === '') {
        return { failureClass: null, detail: '' };
    }
    if (!bot || typeof bot.equip !== 'function') {
        return { failureClass: 'tool-missing', detail: 'equip unavailable' };
    }
    const item = sourceSlotItem(bot, toolSlot);
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

function planFailureClass(value) {
    const cls = String(value || '').toLowerCase();
    if (cls === 'timed-out') return 'timed-out';
    if (cls === 'invalid') return 'invalid';
    if (cls === 'bridge-down') return 'bridge-down';
    return 'blocked';
}

async function withTimeout(promise, timeoutMs, label) {
    let timer;
    try {
        return await Promise.race([
            promise,
            new Promise((_resolve, reject) => {
                timer = setTimeout(
                    () => reject(new Error(`${label} timed out after ${timeoutMs}ms`)),
                    timeoutMs,
                );
            }),
        ]);
    } finally {
        if (timer) clearTimeout(timer);
    }
}

async function placeBlockAt(bot, target, timeoutMs) {
    if (!bot || typeof bot.placeBlock !== 'function') {
        return { failureClass: 'blocked', detail: 'placeBlock unavailable' };
    }
    const faceVector = faceVectorFrom('up');
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
        await withTimeout(bot.placeBlock(referenceBlock, await makeVec3(faceVector)), timeoutMs, 'place');
        return { failureClass: null, detail: `placed against ${normalizeBlockType(referenceBlock)}` };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        return { failureClass: classifyError(message), detail: message };
    }
}

async function digBlock(bot, block, timeoutMs) {
    if (!bot || typeof bot.dig !== 'function') {
        return { failureClass: 'blocked', detail: 'dig unavailable' };
    }
    try {
        await withTimeout(bot.dig(block), timeoutMs, 'break');
        return { failureClass: null, detail: `dug ${normalizeBlockType(block)}` };
    } catch (err) {
        const message = err && err.message ? err.message : String(err);
        return { failureClass: classifyError(message), detail: message };
    }
}

function stepDetail(outcomeClass, observation, extraDetail) {
    const position = observation.position
        ? `${observation.position.x},${observation.position.y},${observation.position.z}`
        : 'unknown';
    const suffix = extraDetail ? `; ${extraDetail}` : '';
    return (
        `${outcomeClass}: position=${position}; expected=${observation.expected_block_type}; ` +
        `before=${observation.before_block}; after=${observation.after_block}${suffix}`
    );
}

async function emitBlockStepOutcome({
    agent,
    traceId,
    actionId,
    step,
    beforeBlock,
    afterBlock,
    expectedBlockType,
    outcomeClass,
    extraDetail,
}) {
    const observation = blockObservation({
        action: step.action,
        actionId,
        position: step.position,
        beforeBlock,
        afterBlock,
        expectedBlockType,
        outcomeClass,
    });
    const detail = stepDetail(outcomeClass, observation, extraDetail);
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

function finalDetail(outcomeClass, metric) {
    return (
        `${outcomeClass}: intended=${metric.intended_count}; present=${metric.blocks_present}; ` +
        `missing=${metric.blocks_missing}; unexpected=${metric.blocks_unexpected}; ` +
        `verified=${metric.steps_verified}; abandoned=${metric.steps_abandoned}; ` +
        `completion=${metric.completion_ratio.toFixed(3)}`
    );
}

async function emitStructureOutcome({ agent, traceId, actionId, origin, steps, metric, outcomeClass }) {
    const observation = structureObservation({
        action: 'build-from-plan',
        actionId,
        origin,
        steps,
        metric,
        outcomeClass,
    });
    const detail = finalDetail(outcomeClass, metric);
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
            status: statusForPlanClass(outcomeClass),
            detail,
        },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    return detail;
}

async function performBreakStep(bot, step, timeoutMs) {
    const beforeRaw = await readRawBlock(bot, step.position);
    const before = normalizeBlockType(beforeRaw);
    let breakAttempt = { failureClass: null, detail: '' };
    let outcomeClass;

    if (!beforeRaw || isAirBlock(before)) {
        outcomeClass = 'removed';
        breakAttempt = { failureClass: null, detail: 'already clear' };
    } else {
        const equipped = await equipTool(bot, step.tool_slot);
        breakAttempt = equipped.failureClass ? equipped : await digBlock(bot, beforeRaw, timeoutMs);
    }

    const after = await readBlockType(bot, step.position);
    if (!outcomeClass) {
        outcomeClass = classifyBreak({
            beforeBlock: before,
            afterBlock: after,
            expectedBlockType: before,
            failureClass: breakAttempt.failureClass,
        });
    }

    return {
        ...step,
        before_block: before,
        after_block: after,
        class: outcomeClass,
        detail: breakAttempt.detail,
    };
}

async function performPlaceStep(bot, step, timeoutMs) {
    const expectedBlockType = normalizeBlockType(step.block_type);
    const before = await readBlockType(bot, step.position);
    let placement = { failureClass: null, detail: 'already present' };

    if (before !== expectedBlockType) {
        const equipped = await equipBlock(bot, expectedBlockType, step.source_slot);
        placement = equipped.failureClass
            ? equipped
            : await placeBlockAt(bot, step.position, timeoutMs);
    }

    const after = await readBlockType(bot, step.position);
    const outcomeClass = classifyPlace({
        beforeBlock: before,
        afterBlock: after,
        blockType: expectedBlockType,
        failureClass: placement.failureClass,
    });

    return {
        ...step,
        before_block: before,
        after_block: after,
        class: outcomeClass,
        detail: placement.detail,
    };
}

function maxStepsFrom(value, fallback) {
    if (value === undefined || value === null || value === '') return fallback;
    const n = Number(value);
    return Number.isInteger(n) && n >= 0 ? Math.min(n, fallback) : fallback;
}

function positiveNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : fallback;
}

function uniqueStepPositions(steps) {
    const seen = new Set();
    const positions = [];
    for (const step of steps) {
        const cell = positionFrom(step && step.position);
        if (!cell) continue;
        const key = `${cell.x},${cell.y},${cell.z}`;
        if (seen.has(key)) continue;
        seen.add(key);
        positions.push(cell);
    }
    return positions;
}

async function readFinalBlocks(bot, steps) {
    const blocks = [];
    for (const position of uniqueStepPositions(steps)) {
        blocks.push({
            position,
            block_type: await readBlockType(bot, position),
        });
    }
    return blocks;
}

function attachFinalBlocks(steps, finalBlocks) {
    const byKey = new Map(
        finalBlocks.map((entry) => [
            `${entry.position.x},${entry.position.y},${entry.position.z}`,
            normalizeBlockType(entry.block_type),
        ]),
    );
    return steps.map((step) => {
        const cell = positionFrom(step.position);
        const key = cell ? `${cell.x},${cell.y},${cell.z}` : null;
        return {
            ...step,
            final_block: key && byKey.has(key) ? byKey.get(key) : step.after_block,
        };
    });
}

export const buildFromPlanAction = {
    name: '!buildFromPlan',
    description:
        'Execute a structured multi-block build plan and report actual-vs-intended completion.',
    params: {
        action_id: {
            type: 'string',
            description: 'Caller-provided action id echoed in the final action.result.',
        },
        origin: {
            type: 'object',
            description: 'Absolute origin block cell with x/y/z coordinates.',
        },
        plan: {
            type: 'object',
            description:
                'Structured plan with blocks[{dx,dy,dz,block_type}], optional palette, and optional clear[].',
        },
        max_steps: {
            type: 'int',
            description: 'Optional cap on attempted expanded steps.',
        },
        timeout_ms: {
            type: 'float',
            description: 'Optional total build deadline in milliseconds.',
        },
    },
    perform: async function (agent, action_id, origin, plan, max_steps, timeout_ms) {
        const traceId = `trace-${randomUUID()}`;
        const actionId =
            action_id === undefined || action_id === null || action_id === ''
                ? `build-plan-${randomUUID()}`
                : String(action_id);
        const bot = getBot(agent);
        const timeout = positiveNumber(timeout_ms, DEFAULT_BUILD_TIMEOUT_MS);
        const deadline = Date.now() + timeout;

        try {
            await ensureBridge(agent, traceId);
        } catch (err) {
            const line = bridgeErrorLine('bridge unavailable, safe-idling', err);
            announce(agent, traceId, line, true);
            return line;
        }

        const missingActionId = action_id === undefined || action_id === null || action_id === '';
        let normalized;
        let invalidDetail = '';
        try {
            normalized = normalizePlan({ origin, plan });
        } catch (err) {
            invalidDetail = err && err.message ? err.message : String(err);
        }

        if (missingActionId || !normalized) {
            const metric = completionMetric({ steps: [], finalBlocks: [] });
            try {
                const detail = await emitStructureOutcome({
                    agent,
                    traceId,
                    actionId,
                    origin,
                    steps: [],
                    metric,
                    outcomeClass: 'invalid',
                });
                const extra = missingActionId ? 'missing action_id' : invalidDetail;
                const line = `build-from-plan ${actionId} ${detail}; ${extra}`;
                announce(agent, traceId, line, true);
                return line;
            } catch (err) {
                const line = bridgeErrorLine(
                    `build-from-plan ${actionId} invalid but report failed`,
                    err,
                );
                announce(agent, traceId, line, true);
                return line;
            }
        }

        const stepLimit = maxStepsFrom(max_steps, normalized.steps.length);
        const executedSteps = [];
        let failureClass = null;

        for (const step of normalized.steps) {
            if (executedSteps.length >= stepLimit) {
                failureClass = 'partial';
                break;
            }
            const remaining = deadline - Date.now();
            if (remaining <= 0) {
                failureClass = 'timed-out';
                break;
            }
            const stepTimeout = Math.max(1, Math.min(DEFAULT_STEP_TIMEOUT_MS, remaining));
            const stepActionId = `${actionId}#${step.index + 1}`;
            const result =
                step.action === 'break'
                    ? await performBreakStep(bot, step, stepTimeout)
                    : await performPlaceStep(bot, step, stepTimeout);
            executedSteps.push(result);

            try {
                await emitBlockStepOutcome({
                    agent,
                    traceId,
                    actionId: stepActionId,
                    step: result,
                    beforeBlock: result.before_block,
                    afterBlock: result.after_block,
                    expectedBlockType: result.expected_block_type || result.block_type,
                    outcomeClass: result.class,
                    extraDetail: result.detail,
                });
            } catch (err) {
                const line = bridgeErrorLine(
                    `build-from-plan ${actionId} step report failed, safe-idling`,
                    err,
                );
                announce(agent, traceId, line, true);
                return line;
            }

            if (result.class !== 'placed' && result.class !== 'removed') {
                failureClass = planFailureClass(result.class);
            }
        }

        const abandonedSteps = normalized.steps.slice(executedSteps.length).map((step) => ({
            ...step,
            abandoned: true,
            class: failureClass === 'timed-out' ? 'timed-out' : 'blocked',
        }));
        const allSteps = [...executedSteps, ...abandonedSteps];
        const finalBlocks = await readFinalBlocks(bot, allSteps);
        const finalSteps = attachFinalBlocks(allSteps, finalBlocks);
        const metric = completionMetric({ steps: finalSteps, finalBlocks });
        const outcomeClass = classifyPlan({ metric, failureClass });

        try {
            const detail = await emitStructureOutcome({
                agent,
                traceId,
                actionId,
                origin: normalized.origin,
                steps: finalSteps,
                metric,
                outcomeClass,
            });
            const line = `build-from-plan ${actionId} ${detail}`;
            announce(agent, traceId, line, outcomeClass !== 'success');
            return line;
        } catch (err) {
            const line = bridgeErrorLine(
                `build-from-plan ${actionId} completed but report failed`,
                err,
            );
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default buildFromPlanAction;

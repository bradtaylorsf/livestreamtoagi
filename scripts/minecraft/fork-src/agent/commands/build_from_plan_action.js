// Verified `!buildFromPlan` action for E6-4 (#559).
//
// The action expands a structured plan into verified break/place steps, emits
// per-step block observations and action results, then performs a final world
// read to report actual-vs-intended structure completion.

import { randomUUID } from 'node:crypto';

import {
    BridgeClientError,
    bridgeIsKillActive,
    callBridge,
    startKillSwitchWatch,
} from '../bridge/python_bridge.js';
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

const DEFAULT_BUILD_TIMEOUT_MS = 120000;
const DEFAULT_STEP_TIMEOUT_MS = 10000;
const DEFAULT_NAVIGATION_TIMEOUT_MS = 20000;
const DEFAULT_NAVIGATION_MS_PER_BLOCK = 800;
const DEFAULT_PLACE_SETTLE_MS = 150;
const DEFAULT_PLACE_ATTEMPTS = 3;
const DEFAULT_PLACE_REACH_BLOCKS = 4.25;
const DEFAULT_NAVIGATION_TOLERANCE_BLOCKS = 1;
const DEFAULT_RECONCILE_PASSES = 2;
const BRIDGE_REPORT_TIMEOUT_MS = 5000;
const REPLACEABLE_BLOCK_TYPES = new Set([
    'grass',
    'short_grass',
    'tall_grass',
    'fern',
    'large_fern',
    'dead_bush',
    'snow',
    'snow_layer',
    'vine',
]);

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

function parseJsonArgument(value, label) {
    if (value === undefined || value === null || value === '') {
        return { value: null, error: `wrong_args: ${label} is required`, outcomeClass: 'wrong_args' };
    }
    if (typeof value !== 'string') return { value, error: null, outcomeClass: null };
    const text = value.trim();
    if (!text) {
        return { value: null, error: `wrong_args: ${label} is required`, outcomeClass: 'wrong_args' };
    }
    try {
        return { value: JSON.parse(text), error: null, outcomeClass: null };
    } catch (err) {
        const detail = err && err.message ? err.message : String(err);
        return {
            value: null,
            error: `invalid_args: ${label} must be JSON: ${detail}`,
            outcomeClass: 'invalid_args',
        };
    }
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

function messageFromError(err) {
    if (!err) return '';
    return err && err.message ? String(err.message) : String(err);
}

async function makeGoalNear(target, tolerance) {
    try {
        const mod = await import('mineflayer-pathfinder');
        const goals = (mod && mod.goals) || (mod && mod.default && mod.default.goals);
        const GoalNear = goals && goals.GoalNear;
        if (GoalNear) return new GoalNear(target.x, target.y, target.z, tolerance);
    } catch {
        /* Test and static environments may not have the Mindcraft dependency. */
    }
    return { x: target.x, y: target.y, z: target.z, range: tolerance };
}

async function ensurePathfinder(bot) {
    if (bot && bot.pathfinder && typeof bot.pathfinder.goto === 'function') return true;
    try {
        const mod = await import('mineflayer-pathfinder');
        if (bot && typeof bot.loadPlugin === 'function' && mod && mod.pathfinder) {
            bot.loadPlugin(mod.pathfinder);
        }
    } catch {
        return false;
    }
    return !!(bot && bot.pathfinder && typeof bot.pathfinder.goto === 'function');
}

function destructivePathsAllowed() {
    const raw = String(process.env.MINECRAFT_ALLOW_DESTRUCTIVE_PATHS || '1').trim().toLowerCase();
    return !['0', 'false', 'no', 'off'].includes(raw);
}

function clearReplaceableBeforePlaceEnabled() {
    const raw = String(process.env.MINECRAFT_BUILD_FROM_PLAN_CLEAR_REPLACEABLE || '1')
        .trim()
        .toLowerCase();
    return !['0', 'false', 'no', 'off'].includes(raw);
}

function repairWrongTargetBeforePlaceEnabled() {
    const raw = String(process.env.MINECRAFT_BUILD_FROM_PLAN_REPAIR_WRONG_TARGET || '1')
        .trim()
        .toLowerCase();
    return !['0', 'false', 'no', 'off'].includes(raw);
}

function isReplaceableBlock(value) {
    const blockType = normalizeBlockType(value);
    return blockType !== null && REPLACEABLE_BLOCK_TYPES.has(blockType);
}

async function configureMovementSafety(bot) {
    if (destructivePathsAllowed()) return;
    try {
        const mod = await import('mineflayer-pathfinder');
        const Movements = (mod && mod.Movements) || (mod && mod.default && mod.default.Movements);
        if (Movements && bot && bot.pathfinder && typeof bot.pathfinder.setMovements === 'function') {
            const movements = new Movements(bot);
            movements.canDig = false;
            movements.allow1by1towers = false;
            bot.pathfinder.setMovements(movements);
        }
    } catch {
        /* Navigation will still report pathfinder failures normally. */
    }
}

function botPosition(bot) {
    return positionFrom(bot && bot.entity && bot.entity.position);
}

function distanceSquared(a, b) {
    if (!a || !b) return Number.POSITIVE_INFINITY;
    const dx = Number(a.x) - Number(b.x);
    const dy = Number(a.y) - Number(b.y);
    const dz = Number(a.z) - Number(b.z);
    return dx * dx + dy * dy + dz * dz;
}

function positionKey(position) {
    const cell = positionFrom(position);
    return cell ? `${cell.x},${cell.y},${cell.z}` : null;
}

function positionFromKey(key) {
    const parts = String(key || '')
        .split(',')
        .map((part) => Number(part));
    if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return null;
    return { x: parts[0], y: parts[1], z: parts[2] };
}

function isTorchLike(value) {
    return normalizeBlockType(value) === 'torch';
}

function structuralPositionKeys(steps) {
    const keys = new Set();
    for (const step of Array.isArray(steps) ? steps : []) {
        if (!step || step.action !== 'place') continue;
        if (isTorchLike(step.block_type || step.expected_block_type)) continue;
        const key = positionKey(step.position);
        if (key) keys.add(key);
    }
    return keys;
}

function protectedTorchCleanupPositions(target, protectedPositions) {
    const targetCell = positionFrom(target);
    if (!targetCell || !protectedPositions || protectedPositions.size <= 0) return [];
    const positions = [];
    for (const key of protectedPositions) {
        const cell = positionFromKey(key);
        if (!cell) continue;
        const horizontal = Math.abs(cell.x - targetCell.x) + Math.abs(cell.z - targetCell.z);
        const vertical = Math.abs(cell.y - targetCell.y);
        if (horizontal <= 1 && vertical <= 1) positions.push(cell);
    }
    return positions;
}

function withinBuildReach(bot, target) {
    const current = botPosition(bot);
    if (!current) return true;
    const reach = placeReachBlocks();
    return distanceSquared(current, target) <= reach * reach;
}

function navigationTimeoutMs(bot, target, remainingMs) {
    const configured = positiveNumber(
        process.env.MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_TIMEOUT_MS,
        DEFAULT_NAVIGATION_TIMEOUT_MS,
    );
    const msPerBlock = positiveNumber(
        process.env.MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_MS_PER_BLOCK,
        DEFAULT_NAVIGATION_MS_PER_BLOCK,
    );
    const current = botPosition(bot);
    const distance = current ? Math.sqrt(distanceSquared(current, target)) : 0;
    const scaled = Math.max(configured, Math.ceil(distance * msPerBlock));
    return Math.max(1, Math.min(scaled, remainingMs));
}

async function moveWithinBuildReach(agent, target, timeoutMs) {
    const bot = getBot(agent);
    if (withinBuildReach(bot, target)) return { failureClass: null, detail: 'already within reach' };
    if (!(await ensurePathfinder(bot))) {
        return { failureClass: 'unreachable', detail: 'pathfinder unavailable' };
    }
    await configureMovementSafety(bot);
    const goal = await makeGoalNear(target, navigationToleranceBlocks());
    try {
        await withTimeout(bot.pathfinder.goto(goal), timeoutMs, 'navigation');
    } catch (err) {
        const message = messageFromError(err);
        const lower = message.toLowerCase();
        if (lower.includes('timed out') || lower.includes('timeout')) {
            return { failureClass: 'timed-out', detail: message };
        }
        if (lower.includes('unreachable') || lower.includes('no path')) {
            return { failureClass: 'unreachable', detail: message };
        }
        return { failureClass: 'blocked', detail: message };
    }
    if (!withinBuildReach(bot, target)) {
        return { failureClass: 'unreachable', detail: 'pathfinder stopped outside build reach' };
    }
    return { failureClass: null, detail: 'moved within build reach' };
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

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function placementSettleMs() {
    return positiveNumber(process.env.MINECRAFT_BUILD_FROM_PLAN_PLACE_SETTLE_MS, DEFAULT_PLACE_SETTLE_MS);
}

function placeReachBlocks() {
    return positiveNumber(process.env.MINECRAFT_BUILD_FROM_PLAN_PLACE_REACH_BLOCKS, DEFAULT_PLACE_REACH_BLOCKS);
}

function navigationToleranceBlocks() {
    return positiveNumber(
        process.env.MINECRAFT_BUILD_FROM_PLAN_NAVIGATION_TOLERANCE_BLOCKS,
        DEFAULT_NAVIGATION_TOLERANCE_BLOCKS,
    );
}

function placeAttempts() {
    const attempts = positiveNumber(
        process.env.MINECRAFT_BUILD_FROM_PLAN_PLACE_ATTEMPTS,
        DEFAULT_PLACE_ATTEMPTS,
    );
    return Math.max(1, Math.min(5, Math.floor(attempts)));
}

function reconcilePasses() {
    const passes = positiveNumber(
        process.env.MINECRAFT_BUILD_FROM_PLAN_RECONCILE_PASSES,
        DEFAULT_RECONCILE_PASSES,
    );
    return Math.max(0, Math.min(3, Math.floor(passes)));
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

async function cleanupMisplacedProtectedTorch(bot, step, protectedPositions, timeoutMs) {
    if (!isTorchLike(step && (step.block_type || step.expected_block_type))) return '';
    const details = [];
    for (const position of protectedTorchCleanupPositions(step.position, protectedPositions)) {
        const raw = await readRawBlock(bot, position);
        if (!isTorchLike(raw)) continue;
        const cleaned = await digBlock(bot, raw, timeoutMs);
        const key = positionKey(position) || 'unknown';
        if (cleaned.failureClass) {
            details.push(`misplaced torch cleanup failed at ${key}: ${cleaned.detail}`);
        } else {
            details.push(`removed misplaced torch from protected support ${key}`);
        }
    }
    return details.join('; ');
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
            outcome_class: outcomeClass,
            detail,
        },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    return detail;
}

function finalDetail(outcomeClass, metric, extraDetail = '') {
    const suffix = extraDetail ? `; ${extraDetail}` : '';
    return (
        `${outcomeClass}: intended=${metric.intended_count}; present=${metric.blocks_present}; ` +
        `missing=${metric.blocks_missing}; unexpected=${metric.blocks_unexpected}; ` +
        `verified=${metric.steps_verified}; abandoned=${metric.steps_abandoned}; ` +
        `completion=${metric.completion_ratio.toFixed(3)}${suffix}`
    );
}

async function emitStructureOutcome({
    agent,
    traceId,
    actionId,
    origin,
    steps,
    metric,
    outcomeClass,
    extraDetail,
}) {
    const observation = structureObservation({
        action: 'build-from-plan',
        actionId,
        origin,
        steps,
        metric,
        outcomeClass,
    });
    const detail = finalDetail(outcomeClass, metric, extraDetail);
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
            outcome_class: outcomeClass,
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

async function performPlaceStep(bot, step, timeoutMs, protectedPositions = new Set()) {
    const expectedBlockType = normalizeBlockType(step.block_type);
    const initialBeforeRaw = await readRawBlock(bot, step.position);
    const before = normalizeBlockType(initialBeforeRaw);
    let placement = { failureClass: null, detail: 'already present' };
    let after = before;
    const details = [];

    for (let attempt = 0; attempt < placeAttempts(); attempt += 1) {
        const beforeRaw = await readRawBlock(bot, step.position);
        const current = normalizeBlockType(beforeRaw);
        if (current === expectedBlockType) {
            placement = { failureClass: null, detail: details.join('; ') || 'already present' };
            after = current;
            break;
        }
        if (
            beforeRaw &&
            !isAirBlock(beforeRaw) &&
            ((isReplaceableBlock(beforeRaw) && clearReplaceableBeforePlaceEnabled()) ||
                (repairWrongTargetBeforePlaceEnabled() && current !== expectedBlockType))
        ) {
            const cleared = await digBlock(bot, beforeRaw, timeoutMs);
            details.push(`${isReplaceableBlock(beforeRaw) ? 'cleared' : 'repaired'} ${current}`);
            if (cleared.failureClass) {
                placement = {
                    failureClass: cleared.failureClass,
                    detail: cleared.detail,
                };
                after = await readBlockType(bot, step.position);
                break;
            }
        }
        const currentAfterClear = await readBlockType(bot, step.position);
        const equipped =
            placement.failureClass || currentAfterClear === expectedBlockType
                ? placement
                : await equipBlock(bot, expectedBlockType, step.source_slot);
        if (equipped.failureClass || currentAfterClear === expectedBlockType) {
            placement = equipped.failureClass
                ? equipped
                : { failureClass: null, detail: details.join('; ') || 'already present' };
            after = await readBlockType(bot, step.position);
            break;
        }
        const settleMs = placementSettleMs();
        if (settleMs > 0) await sleep(settleMs);
        placement = await placeBlockAt(bot, step.position, timeoutMs);
        if (settleMs > 0) await sleep(settleMs);
        const cleanupDetail = await cleanupMisplacedProtectedTorch(
            bot,
            step,
            protectedPositions,
            timeoutMs,
        );
        if (cleanupDetail) details.push(cleanupDetail);
        after = await readBlockType(bot, step.position);
        if (after === expectedBlockType || placement.failureClass) break;
        if (attempt + 1 < placeAttempts()) details.push(`retry ${attempt + 1}: saw ${after || 'air'}`);
    }

    if (details.length && placement.detail) {
        placement.detail = `${details.join('; ')}; ${placement.detail}`;
    } else if (details.length) {
        placement.detail = details.join('; ');
    }

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

function reconcileOrder(executedSteps) {
    return executedSteps
        .map((step, index) => ({ step, index }))
        .sort((left, right) => {
            const leftTorch = isTorchLike(left.step && (left.step.block_type || left.step.expected_block_type));
            const rightTorch = isTorchLike(
                right.step && (right.step.block_type || right.step.expected_block_type),
            );
            if (leftTorch !== rightTorch) return leftTorch ? -1 : 1;
            return left.index - right.index;
        });
}

export async function performBuildFromPlan(agent, action_id, origin, plan, max_steps, timeout_ms) {
    const traceId = `trace-${randomUUID()}`;
    const actionId =
        action_id === undefined || action_id === null || action_id === ''
            ? `build-plan-${randomUUID()}`
            : String(action_id);
    const bot = getBot(agent);
    const timeout = positiveNumber(timeout_ms, DEFAULT_BUILD_TIMEOUT_MS);
    const deadline = Date.now() + timeout;
    await startKillSwitchWatch();
    if (bridgeIsKillActive()) {
        const line = 'kill switch active, safe-idling [kill_switch_active]';
        announce(agent, traceId, line, true);
        return line;
    }

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
    let invalidOutcomeClass = 'invalid_args';
    const parsedOrigin = parseJsonArgument(origin, 'origin');
    const parsedPlan = parseJsonArgument(plan, 'plan');
    try {
        if (parsedOrigin.error || parsedPlan.error) {
            invalidDetail = [parsedOrigin.error, parsedPlan.error].filter(Boolean).join('; ');
            invalidOutcomeClass =
                parsedOrigin.outcomeClass === 'wrong_args' || parsedPlan.outcomeClass === 'wrong_args'
                    ? 'wrong_args'
                    : 'invalid_args';
        } else {
            normalized = normalizePlan({ origin: parsedOrigin.value, plan: parsedPlan.value });
        }
    } catch (err) {
        invalidDetail = err && err.message ? err.message : String(err);
    }

    if (missingActionId || !normalized) {
        const metric = completionMetric({ steps: [], finalBlocks: [] });
        const extra = missingActionId ? 'wrong_args: missing action_id' : invalidDetail;
        const outcomeClass = missingActionId ? 'wrong_args' : invalidOutcomeClass;
        try {
            const detail = await emitStructureOutcome({
                agent,
                traceId,
                actionId,
                origin: parsedOrigin.value,
                steps: [],
                metric,
                outcomeClass,
                extraDetail: extra,
            });
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
    let suppressStepBridgeReports = false;
    const reportWarnings = [];
    const protectedPositions = structuralPositionKeys(normalized.steps);

    for (const step of normalized.steps) {
        if (bridgeIsKillActive()) {
            const line = 'kill switch active, safe-idling [kill_switch_active]';
            announce(agent, traceId, line, true);
            return line;
        }
        if (executedSteps.length >= stepLimit) {
            failureClass = 'partial';
            break;
        }
        let remaining = deadline - Date.now();
        if (remaining <= 0) {
            failureClass = 'timed-out';
            break;
        }
        const stepActionId = `${actionId}#${step.index + 1}`;
        const navigation = await moveWithinBuildReach(
            agent,
            step.position,
            navigationTimeoutMs(bot, step.position, remaining),
        );
        remaining = deadline - Date.now();
        if (remaining <= 0) {
            failureClass = 'timed-out';
            break;
        }
        let result;
        if (navigation.failureClass) {
            const before = await readBlockType(bot, step.position);
            result = {
                ...step,
                before_block: before,
                after_block: before,
                class: navigation.failureClass,
                detail: `navigation: ${navigation.detail}`,
            };
        } else {
            const stepTimeout = Math.max(1, Math.min(DEFAULT_STEP_TIMEOUT_MS, remaining));
            result =
                step.action === 'break'
                    ? await performBreakStep(bot, step, stepTimeout)
                    : await performPlaceStep(bot, step, stepTimeout, protectedPositions);
            if (navigation.detail && navigation.detail !== 'already within reach') {
                result.detail = result.detail
                    ? `${navigation.detail}; ${result.detail}`
                    : navigation.detail;
            }
        }
        executedSteps.push(result);

        if (!suppressStepBridgeReports) {
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
                suppressStepBridgeReports = true;
                const warning = bridgeErrorLine(`build-from-plan ${actionId} step report warning`, err);
                reportWarnings.push(warning);
                result.detail = result.detail ? `${result.detail}; ${warning}` : warning;
                console.warn(`[build-from-plan trace=${traceId}] ${warning}`);
            }
        }

        if (result.class !== 'placed' && result.class !== 'removed') {
            failureClass = planFailureClass(result.class);
        }
    }

    let abandonedSteps = normalized.steps.slice(executedSteps.length).map((step) => ({
        ...step,
        abandoned: true,
        class: failureClass === 'timed-out' ? 'timed-out' : 'blocked',
    }));
    let allSteps = [...executedSteps, ...abandonedSteps];
    let finalBlocks = await readFinalBlocks(bot, allSteps);
    let finalSteps = attachFinalBlocks(allSteps, finalBlocks);
    let metric = completionMetric({ steps: finalSteps, finalBlocks });
    for (let pass = 0; pass < reconcilePasses() && metric.blocks_missing > 0; pass += 1) {
        if (deadline - Date.now() <= 0) break;
        let repaired = false;
        for (const { step, index } of reconcileOrder(executedSteps)) {
            if (!step || step.action !== 'place') continue;
            const expected = normalizeBlockType(step.block_type || step.expected_block_type);
            const actual = await readBlockType(bot, step.position);
            if (actual === expected) continue;
            const remaining = deadline - Date.now();
            if (remaining <= 0) break;
            const navigation = await moveWithinBuildReach(
                agent,
                step.position,
                navigationTimeoutMs(bot, step.position, remaining),
            );
            let repair;
            if (navigation.failureClass) {
                const before = await readBlockType(bot, step.position);
                repair = {
                    ...step,
                    before_block: before,
                    after_block: before,
                    class: navigation.failureClass,
                    detail: `reconcile pass ${pass + 1}; navigation: ${navigation.detail}`,
                };
            } else {
                const afterNavigationRemaining = deadline - Date.now();
                if (afterNavigationRemaining <= 0) break;
                repair = await performPlaceStep(
                    bot,
                    step,
                    Math.max(1, Math.min(DEFAULT_STEP_TIMEOUT_MS, afterNavigationRemaining)),
                    protectedPositions,
                );
                const details = [`reconcile pass ${pass + 1}`];
                if (navigation.detail && navigation.detail !== 'already within reach') {
                    details.push(navigation.detail);
                }
                if (repair.detail) details.push(repair.detail);
                repair.detail = details.join('; ');
            }
            executedSteps[index] = repair;
            repaired = true;
            if (!suppressStepBridgeReports) {
                try {
                    await emitBlockStepOutcome({
                        agent,
                        traceId,
                        actionId: `${actionId}#${step.index + 1}r${pass + 1}`,
                        step: repair,
                        beforeBlock: repair.before_block,
                        afterBlock: repair.after_block,
                        expectedBlockType: repair.expected_block_type || repair.block_type,
                        outcomeClass: repair.class,
                        extraDetail: repair.detail,
                    });
                } catch (err) {
                    suppressStepBridgeReports = true;
                    const warning = bridgeErrorLine(
                        `build-from-plan ${actionId} reconcile report warning`,
                        err,
                    );
                    reportWarnings.push(warning);
                    repair.detail = repair.detail ? `${repair.detail}; ${warning}` : warning;
                    console.warn(`[build-from-plan trace=${traceId}] ${warning}`);
                }
            }
        }
        if (!repaired) break;
        abandonedSteps = normalized.steps.slice(executedSteps.length).map((step) => ({
            ...step,
            abandoned: true,
            class: failureClass === 'timed-out' ? 'timed-out' : 'blocked',
        }));
        allSteps = [...executedSteps, ...abandonedSteps];
        finalBlocks = await readFinalBlocks(bot, allSteps);
        finalSteps = attachFinalBlocks(allSteps, finalBlocks);
        metric = completionMetric({ steps: finalSteps, finalBlocks });
    }
    const outcomeClass = classifyPlan({ metric, failureClass });
    const reportWarningDetail =
        reportWarnings.length > 0
            ? `${reportWarnings[0]}${
                  reportWarnings.length > 1
                      ? `; additional_report_warnings=${reportWarnings.length - 1}`
                      : ''
              }`
            : '';

    try {
        const detail = await emitStructureOutcome({
            agent,
            traceId,
            actionId,
            origin: normalized.origin,
            steps: finalSteps,
            metric,
            outcomeClass,
            extraDetail: reportWarningDetail,
        });
        const line = `build-from-plan ${actionId} ${detail}`;
        announce(agent, traceId, line, outcomeClass !== 'success');
        return line;
    } catch (err) {
        const warning = bridgeErrorLine(`build-from-plan ${actionId} structure report warning`, err);
        const detail = finalDetail(
            outcomeClass,
            metric,
            [reportWarningDetail, warning].filter(Boolean).join('; '),
        );
        const line = `build-from-plan ${actionId} ${detail}`;
        console.warn(`[build-from-plan trace=${traceId}] ${warning}`);
        announce(agent, traceId, line, outcomeClass !== 'success');
        return line;
    }
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
            type: 'string',
            description: 'Absolute origin block cell as JSON with x/y/z coordinates.',
        },
        plan: {
            type: 'string',
            description:
                'JSON plan with blocks[{dx,dy,dz,block_type}], optional palette, and optional clear[].',
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
    perform: performBuildFromPlan,
};

export default buildFromPlanAction;

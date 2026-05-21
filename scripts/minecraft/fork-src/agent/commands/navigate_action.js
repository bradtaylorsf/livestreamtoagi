// Verified `!navigate` action for E6-2 (#557).
//
// This reports success only when the post-action pose is observed within the
// requested arrival tolerance. The richer reached/blocked/timed-out/etc class
// is carried in the pose observation and action-result detail while the bridge
// contract status remains success/failure/partial.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import { classifyInterruption, messageFromError } from '../skills/action_interruption.js';
import {
    classifyMovement,
    DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
    poseFrom,
    poseObservation,
    statusForMovementClass,
} from '../skills/movement.js';

const DEFAULT_NAVIGATE_TIMEOUT_MS = 20000;
const DEFAULT_NAVIGATE_TOLERANCE_BLOCKS = 1.0;
const BRIDGE_REPORT_TIMEOUT_MS = 5000;

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function readPose(agent) {
    const bot = getBot(agent);
    return poseFrom(bot && bot.entity && bot.entity.position);
}

function positiveNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : fallback;
}

function announce(agent, traceId, line, isError = false) {
    try {
        if (agent && typeof agent.openChat === 'function') agent.openChat(line);
    } catch {
        /* chat is cosmetic; never let it mask the verified outcome */
    }
    const tagged = `[navigate trace=${traceId}] ${line}`;
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

function blockPosition(bot, target) {
    if (!bot || typeof bot.findBlock !== 'function') {
        return { failureClass: 'unreachable', detail: 'block lookup unavailable' };
    }
    const blockName = String(target.block || '');
    const blockDef = bot.registry && bot.registry.blocksByName && bot.registry.blocksByName[blockName];
    if (!blockDef || blockDef.id === undefined) {
        return { failureClass: 'invalid', detail: `unknown block target ${blockName}` };
    }
    const block = bot.findBlock({
        matching: blockDef.id,
        maxDistance: positiveNumber(target.max_distance_blocks, 64),
    });
    const position = block && poseFrom(block.position);
    if (!position) return { failureClass: 'unreachable', detail: `no ${blockName} block found nearby` };
    return { position, detail: `nearest block ${blockName}` };
}

function entityPosition(bot, target) {
    if (!bot || !bot.entities) {
        return { failureClass: 'unreachable', detail: 'entity lookup unavailable' };
    }
    const wanted = String(target.entity_id || '');
    const entities = Object.values(bot.entities);
    const entity = entities.find((e) => {
        if (!e) return false;
        return [e.id, e.uuid, e.username, e.name].some((value) => String(value) === wanted);
    });
    const position = entity && poseFrom(entity.position);
    if (!position) return { failureClass: 'unreachable', detail: `entity ${wanted} not found` };
    return { position, detail: `entity ${wanted}` };
}

function resolveTarget(agent, rawTarget) {
    const parsed = parseJsonArgument(rawTarget, 'target');
    if (parsed.error) return { failureClass: 'invalid_args', detail: parsed.error };
    const target = parsed.value;
    const coordinateTarget = poseFrom(target);
    if (coordinateTarget) return { position: coordinateTarget, detail: 'coordinate target' };
    if (target === null || target === undefined || typeof target !== 'object') {
        return { failureClass: 'invalid', detail: 'target must be coordinates, block, or entity_id' };
    }
    const bot = getBot(agent);
    if (target.block) return blockPosition(bot, target);
    if (target.entity_id) return entityPosition(bot, target);
    return { failureClass: 'invalid', detail: 'target must include x/y/z, block, or entity_id' };
}

async function ensureBridge(agent, traceId) {
    await callBridge({
        service: 'bridge',
        method: 'ping',
        payload: { message: 'movement-preflight' },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
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
        /* If safety setup is unavailable, normal pathfinder failure handling still applies. */
    }
}

async function pathfindTo(agent, target, tolerance, timeoutMs) {
    const bot = getBot(agent);
    if (!(await ensurePathfinder(bot))) {
        return { failureClass: 'unreachable', detail: 'pathfinder unavailable' };
    }
    await configureMovementSafety(bot);

    const goal = await makeGoalNear(target, tolerance);
    let timer;
    let pathfinderStopObserved = false;
    let restoreStop = null;
    let originalStop = null;
    if (typeof bot.pathfinder.stop === 'function') {
        originalStop = bot.pathfinder.stop.bind(bot.pathfinder);
        bot.pathfinder.stop = (...args) => {
            pathfinderStopObserved = true;
            return originalStop(...args);
        };
        restoreStop = () => {
            bot.pathfinder.stop = originalStop;
        };
    }
    try {
        await Promise.race([
            bot.pathfinder.goto(goal),
            new Promise((_resolve, reject) => {
                timer = setTimeout(
                    () => reject(new Error(`navigation timed out after ${timeoutMs}ms`)),
                    timeoutMs,
                );
            }),
        ]);
        return { failureClass: null, detail: '' };
    } catch (err) {
        const message = messageFromError(err);
        const interruptionClass = classifyInterruption(err);
        let result;
        if (interruptionClass) {
            result = { failureClass: interruptionClass, detail: message };
        } else {
            const lower = message.toLowerCase();
            if (lower.includes('timed out')) {
                result = { failureClass: 'timed-out', detail: message };
            } else if (lower.includes('unreachable') || lower.includes('no path')) {
                result = { failureClass: 'unreachable', detail: message };
            } else if (pathfinderStopObserved) {
                result = { failureClass: 'interrupted', detail: message || 'pathfinder stopped' };
            } else {
                result = { failureClass: 'blocked', detail: message };
            }
        }
        try {
            if (originalStop) originalStop();
            else if (bot.pathfinder && typeof bot.pathfinder.stop === 'function') bot.pathfinder.stop();
        } catch {
            /* stopping pathfinder is best-effort */
        }
        return result;
    } finally {
        if (timer) clearTimeout(timer);
        if (restoreStop) restoreStop();
    }
}

function outcomeDetail(outcomeClass, observation, extraDetail) {
    const distance =
        observation.distance === null ? 'unknown' : `${observation.distance.toFixed(3)} blocks`;
    const delta =
        observation.delta === null ? 'unknown' : `${observation.delta.distance.toFixed(3)} blocks`;
    const suffix = extraDetail ? `; ${extraDetail}` : '';
    return `${outcomeClass}: distance_to_target=${distance}; delta=${delta}${suffix}`;
}

async function emitNavigationOutcome({
    agent,
    traceId,
    actionId,
    before,
    after,
    target,
    tolerance,
    outcomeClass,
    extraDetail,
}) {
    const observation = poseObservation({
        action: 'navigate',
        actionId,
        before,
        after,
        target,
        tolerance,
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
            status: statusForMovementClass(outcomeClass),
            outcome_class: outcomeClass,
            detail,
        },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    return detail;
}

export const navigateAction = {
    name: '!navigate',
    description:
        'Navigate to a target and report verified reached/blocked/timed-out/unreachable.',
    params: {
        action_id: {
            type: 'string',
            description: 'Caller-provided action id echoed in action.result.',
        },
        target: {
            type: 'string',
            description: 'JSON coordinates {x,y,z}, a block target, or an entity_id target.',
        },
        arrive_within_blocks: {
            type: 'float',
            description: 'Arrival tolerance in blocks.',
        },
        timeout_ms: {
            type: 'float',
            description: 'Navigation deadline in milliseconds.',
        },
    },
    perform: async function (agent, action_id, target, arrive_within_blocks, timeout_ms) {
        const traceId = `trace-${randomUUID()}`;
        const actionId =
            action_id === undefined || action_id === null || action_id === ''
                ? `navigate-${randomUUID()}`
                : String(action_id);
        const timeout = positiveNumber(timeout_ms, DEFAULT_NAVIGATE_TIMEOUT_MS);
        const tolerance = positiveNumber(
            arrive_within_blocks,
            DEFAULT_NAVIGATE_TOLERANCE_BLOCKS,
        );
        const before = readPose(agent);

        try {
            await ensureBridge(agent, traceId);
        } catch (err) {
            const line = bridgeErrorLine('bridge unavailable, safe-idling', err);
            announce(agent, traceId, line, true);
            return line;
        }

        const resolved = resolveTarget(agent, target);
        const missingActionId = action_id === undefined || action_id === null || action_id === '';
        if (missingActionId || !resolved.position) {
            try {
                const detail = await emitNavigationOutcome({
                    agent,
                    traceId,
                    actionId,
                    before,
                    after: before,
                    target: resolved.position,
                    tolerance,
                    outcomeClass: missingActionId ? 'wrong_args' : resolved.failureClass || 'invalid',
                    extraDetail: missingActionId ? 'missing action_id' : resolved.detail,
                });
                announce(agent, traceId, `navigate ${actionId} ${detail}`, true);
                return `navigate ${actionId} ${detail}`;
            } catch (err) {
                const line = bridgeErrorLine(`navigate ${actionId} invalid but report failed`, err);
                announce(agent, traceId, line, true);
                return line;
            }
        }

        const movement = await pathfindTo(agent, resolved.position, tolerance, timeout);
        const after = readPose(agent) || before;
        const outcomeClass = classifyMovement({
            before,
            after,
            target: resolved.position,
            tolerance,
            failureClass: movement.failureClass,
        });

        try {
            const detail = await emitNavigationOutcome({
                agent,
                traceId,
                actionId,
                before,
                after,
                target: resolved.position,
                tolerance,
                outcomeClass,
                extraDetail: movement.detail || resolved.detail,
            });
            const line = `navigate ${actionId} ${detail}`;
            announce(agent, traceId, line, outcomeClass !== 'reached');
            return line;
        } catch (err) {
            const line = bridgeErrorLine(`navigate ${actionId} completed but report failed`, err);
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default navigateAction;

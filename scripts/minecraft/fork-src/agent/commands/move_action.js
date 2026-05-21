// Verified `!move` action for E6-2 (#557).
//
// The action does not treat "command issued" as success. It reads the bot pose
// before and after movement, classifies the observed delta, sends the pose over
// `perception.report`, then sends the terminal `action.result` over the E4-6
// inbound channel.

import { randomUUID } from 'node:crypto';

import {
    BridgeClientError,
    bridgeIsKillActive,
    callBridge,
    startKillSwitchWatch,
} from '../bridge/python_bridge.js';
import {
    classifyMovement,
    DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
    poseFrom,
    poseObservation,
    statusForMovementClass,
    targetFromMove,
} from '../skills/movement.js';

const DEFAULT_MOVE_TIMEOUT_MS = 10000;
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

function readYaw(agent) {
    const bot = getBot(agent);
    const yaw = Number(bot && bot.entity && bot.entity.yaw);
    return Number.isFinite(yaw) ? yaw : 0;
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
    const tagged = `[move trace=${traceId}] ${line}`;
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

async function pathfindTo(agent, target, tolerance, timeoutMs) {
    const bot = getBot(agent);
    if (!(await ensurePathfinder(bot))) {
        return { failureClass: 'unreachable', detail: 'pathfinder unavailable' };
    }

    const goal = await makeGoalNear(target, tolerance);
    let timer;
    try {
        await Promise.race([
            bot.pathfinder.goto(goal),
            new Promise((_resolve, reject) => {
                timer = setTimeout(
                    () => reject(new Error(`movement timed out after ${timeoutMs}ms`)),
                    timeoutMs,
                );
            }),
        ]);
        return { failureClass: null, detail: '' };
    } catch (err) {
        try {
            if (bot.pathfinder && typeof bot.pathfinder.stop === 'function') bot.pathfinder.stop();
        } catch {
            /* stopping pathfinder is best-effort */
        }
        const message = err && err.message ? err.message : String(err);
        const lower = message.toLowerCase();
        if (lower.includes('timed out')) return { failureClass: 'timed-out', detail: message };
        if (lower.includes('unreachable') || lower.includes('no path')) {
            return { failureClass: 'unreachable', detail: message };
        }
        return { failureClass: 'blocked', detail: message };
    } finally {
        if (timer) clearTimeout(timer);
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

async function emitMovementOutcome({
    agent,
    traceId,
    actionId,
    before,
    after,
    target,
    tolerance,
    outcomeClass,
    requestedDistance,
    extraDetail,
}) {
    const observation = poseObservation({
        action: 'move',
        actionId,
        before,
        after,
        target,
        tolerance,
        outcomeClass,
        requestedDistance,
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
            detail,
        },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: agentId(agent),
        traceId,
    });
    return detail;
}

export const moveAction = {
    name: '!move',
    description:
        'Move a verified number of blocks and report reached/blocked/timed-out/partial.',
    params: {
        action_id: {
            type: 'string',
            description: 'Caller-provided action id echoed in action.result.',
        },
        direction: {
            type: 'string',
            description:
                'forward, back, left, right, up, down, north, south, east, or west.',
        },
        distance_blocks: {
            type: 'number',
            description: 'Requested movement distance in blocks.',
        },
        timeout_ms: {
            type: 'number',
            description: 'Optional movement deadline in milliseconds.',
        },
    },
    perform: async function (agent, action_id, direction, distance_blocks, timeout_ms) {
        const traceId = `trace-${randomUUID()}`;
        const actionId =
            action_id === undefined || action_id === null || action_id === ''
                ? `move-${randomUUID()}`
                : String(action_id);
        const timeout = positiveNumber(timeout_ms, DEFAULT_MOVE_TIMEOUT_MS);
        const before = readPose(agent);
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
        const target = targetFromMove(before, direction, distance_blocks, readYaw(agent));
        if (missingActionId || !target) {
            try {
                const detail = await emitMovementOutcome({
                    agent,
                    traceId,
                    actionId,
                    before,
                    after: before,
                    target,
                    tolerance: DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
                    outcomeClass: 'invalid',
                    requestedDistance: distance_blocks,
                    extraDetail: missingActionId
                        ? 'missing action_id'
                        : 'invalid direction, distance, or starting pose',
                });
                announce(agent, traceId, `move ${actionId} ${detail}`, true);
                return `move ${actionId} ${detail}`;
            } catch (err) {
                const line = bridgeErrorLine(`move ${actionId} invalid but report failed`, err);
                announce(agent, traceId, line, true);
                return line;
            }
        }

        const movement = await pathfindTo(
            agent,
            target,
            DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
            timeout,
        );
        const after = readPose(agent) || before;
        const outcomeClass = classifyMovement({
            before,
            after,
            target,
            tolerance: DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
            failureClass: movement.failureClass,
        });

        try {
            const detail = await emitMovementOutcome({
                agent,
                traceId,
                actionId,
                before,
                after,
                target,
                tolerance: DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
                outcomeClass,
                requestedDistance: distance_blocks,
                extraDetail: movement.detail,
            });
            const line = `move ${actionId} ${detail}`;
            announce(agent, traceId, line, outcomeClass !== 'reached');
            return line;
        } catch (err) {
            const line = bridgeErrorLine(`move ${actionId} completed but report failed`, err);
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default moveAction;

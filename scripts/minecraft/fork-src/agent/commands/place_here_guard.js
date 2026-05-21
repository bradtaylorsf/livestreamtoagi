// Guard upstream Mindcraft actions whose implementations are not under this
// fork overlay. Expected Mineflayer path/action interruptions become a
// structured action.result instead of bubbling to Mindcraft's process exit path.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import { classifyInterruption, interruptionDetail } from '../skills/action_interruption.js';

const BRIDGE_REPORT_TIMEOUT_MS = 5000;

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function cleanActionName(actionName) {
    return String(actionName || 'action')
        .replace(/^!/, '')
        .replace(/[^A-Za-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'action';
}

function actionNameFrom(action, fallback = '!action') {
    return (action && action.name) || fallback;
}

function bridgeErrorLine(prefix, err) {
    const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
    const detail = err && err.message ? err.message : String(err);
    return `${prefix} [${code}]: ${detail}`;
}

async function emitInterruptedActionResult(agent, actionName, outcomeClass, err) {
    const actionId = `${cleanActionName(actionName)}-interrupt-${randomUUID()}`;
    const traceId = `trace-${randomUUID()}`;
    const detail = interruptionDetail(outcomeClass, err);
    try {
        await callBridge({
            service: 'action',
            method: 'result',
            payload: {
                action_id: actionId,
                status: 'failure',
                outcome_class: outcomeClass,
                detail,
            },
            deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
            agentId: agentId(agent),
            traceId,
        });
    } catch (bridgeErr) {
        const line = bridgeErrorLine(`${actionName} ${detail}; action.result failed`, bridgeErr);
        console.error(`[action-interruption trace=${traceId}] ${line}`);
        return line;
    }
    console.warn(`[action-interruption trace=${traceId}] ${actionName} ${actionId} ${detail}`);
    return `${actionName} ${actionId} ${detail}`;
}

export function wrapPlaceHere(originalPerform, actionName = '!placeHere') {
    if (typeof originalPerform !== 'function') return originalPerform;
    return async function guardedPlaceHere(agent, ...args) {
        try {
            return await originalPerform.apply(this, [agent, ...args]);
        } catch (err) {
            const outcomeClass = classifyInterruption(err);
            if (!outcomeClass) throw err;
            return emitInterruptedActionResult(agent, actionName, outcomeClass, err);
        }
    };
}

export function wrapInterruptedAction(action) {
    if (!action || typeof action.perform !== 'function' || action.__ltagInterruptionWrapped) {
        return action;
    }
    const actionName = actionNameFrom(action);
    const originalPerform = action.perform;
    action.perform = async function guardedInterruptedAction(agent, ...args) {
        try {
            return await originalPerform.apply(this, [agent, ...args]);
        } catch (err) {
            const outcomeClass = classifyInterruption(err);
            if (!outcomeClass) throw err;
            return emitInterruptedActionResult(agent, actionName, outcomeClass, err);
        }
    };
    Object.defineProperty(action, '__ltagInterruptionWrapped', {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
    return action;
}

export function wrapInterruptedActions(actionsList) {
    if (!Array.isArray(actionsList)) return actionsList;
    for (const action of actionsList) wrapInterruptedAction(action);
    return actionsList;
}

export default wrapPlaceHere;

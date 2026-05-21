// Guard upstream Mindcraft actions whose implementations are not under this
// fork overlay. Expected Mineflayer path/action interruptions become a
// structured action.result instead of bubbling to Mindcraft's process exit path.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import { classifyInterruption, interruptionDetail } from '../skills/action_interruption.js';

const BRIDGE_REPORT_TIMEOUT_MS = 5000;
const COMMAND_PARSE_GUARD_MARKER = 'LTAG E8-16 command parse guard';
const recentPlaceFailures = new Map();
const serializedActionNames = new Set([
    '!move',
    '!navigate',
    '!place',
    '!break',
    '!buildFromPlan',
    '!planAndBuild',
    '!executeCode',
    '!runErrand',
]);

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

function timeoutForAction(actionName) {
    if (actionName === '!buildFromPlan' || actionName === '!planAndBuild') return 5;
    if (actionName === '!executeCode') return Number(process.env.MINECRAFT_EXECUTE_CODE_TIMEOUT_MINS || 2);
    return 1;
}

function bridgeErrorLine(prefix, err) {
    const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
    const detail = err && err.message ? err.message : String(err);
    return `${prefix} [${code}]: ${detail}`;
}

function messageFromUnknown(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    return value && value.message ? String(value.message) : String(value);
}

function classifyCommandFailure(value) {
    const message = messageFromUnknown(value);
    if (/unknown\s+type|unsupported[_ -]?arg|unsupported\s+.*type|type:\s*object/i.test(message)) {
        return 'unsupported_arg_type';
    }
    if (/was given\b|requires\s+\d+\s+args?\b|wrong[_ -]?args?|too (few|many)|missing .*arg/i.test(message)) {
        return 'wrong_args';
    }
    return 'invalid_args';
}

function commandFailureDetail(outcomeClass, value) {
    const message = messageFromUnknown(value);
    return message ? `${outcomeClass}: ${message}` : `${outcomeClass}: invalid action arguments`;
}

function rememberPlaceHereResult(agent, blockType, result) {
    const text = String(result || '');
    const failed = text.match(/Failed to place\s+([A-Za-z0-9_:-]+)\s+at\s+\(([^)]+)\)/i);
    const missing = text.match(/Don'?t have any\s+([A-Za-z0-9_:-]+)\s+to place/i);
    if (!failed && !missing) {
        if (/Placed\s+[A-Za-z0-9_:-]+\s+at\s+\(/i.test(text)) {
            recentPlaceFailures.clear();
        }
        return result;
    }
    const item = (failed && failed[1]) || (missing && missing[1]) || blockType || 'block';
    const target = (failed && failed[2]) || 'inventory';
    const key = `${agentId(agent)}:${item}:${target}`;
    const count = (recentPlaceFailures.get(key) || 0) + 1;
    recentPlaceFailures.set(key, count);
    if (count < 2) return result;
    return (
        `${text}\nrepeated_failure: ${item} at ${target} failed ${count} times; ` +
        'inspect nearby blocks or choose a different target before retrying.'
    );
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

async function emitCommandFailureResult(agent, actionName, err) {
    const outcomeClass = classifyCommandFailure(err);
    const actionId = `${cleanActionName(actionName)}-parse-${randomUUID()}`;
    const traceId = `trace-${randomUUID()}`;
    const detail = commandFailureDetail(outcomeClass, err);
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
        console.error(`[command-parse-guard trace=${traceId}] ${line}`);
        return line;
    }
    console.warn(
        `[command-parse-guard trace=${traceId}] ${COMMAND_PARSE_GUARD_MARKER}: ${actionName} ${actionId} ${detail}`,
    );
    return `${actionName} ${actionId} ${detail}`;
}

export function wrapPlaceHere(originalPerform, actionName = '!placeHere') {
    if (typeof originalPerform !== 'function') return originalPerform;
    return async function guardedPlaceHere(agent, ...args) {
        try {
            const result = await originalPerform.apply(this, [agent, ...args]);
            return rememberPlaceHereResult(agent, args[0], result);
        } catch (err) {
            const outcomeClass = classifyInterruption(err);
            return outcomeClass
                ? emitInterruptedActionResult(agent, actionName, outcomeClass, err)
                : emitCommandFailureResult(agent, actionName, err);
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
            if (
                serializedActionNames.has(actionName) &&
                agent &&
                agent.actions &&
                typeof agent.actions.runAction === 'function'
            ) {
                let actionResult = '';
                const codeReturn = await agent.actions.runAction(
                    `action:${cleanActionName(actionName)}`,
                    async () => {
                        actionResult = await originalPerform.apply(this, [agent, ...args]);
                        if (actionResult && agent.bot) {
                            agent.bot.output = `${agent.bot.output || ''}${String(actionResult)}\n`;
                        }
                    },
                    { timeout: timeoutForAction(actionName) },
                );
                if (codeReturn && codeReturn.interrupted && !codeReturn.timedout) {
                    return codeReturn.message || `interrupted: ${actionName} interrupted before completion`;
                }
                return actionResult || (codeReturn && codeReturn.message) || '';
            }
            return await originalPerform.apply(this, [agent, ...args]);
        } catch (err) {
            const outcomeClass = classifyInterruption(err);
            return outcomeClass
                ? emitInterruptedActionResult(agent, actionName, outcomeClass, err)
                : emitCommandFailureResult(agent, actionName, err);
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

// Alpha `!runErrand` executor for E7-3 (#567).
//
// The action is non-verbal: it polls for one structured errand, runs the
// verified action surface step-by-step, and reports a typed errand completion
// to Python. It logs to the console only.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';
import { navigateAction } from './navigate_action.js';
import { placeAction } from './place_action.js';
import { deriveOverallStatus, parseErrandPlan } from '../skills/errand_plan.js';

const BRIDGE_REPORT_TIMEOUT_MS = 5000;
const ALPHA_AGENT_ID = 'alpha';
const SYMBOLS = new Set(['✓', '✗', '?']);
const CHAT_METHOD = ['open', 'Chat'].join('');

function announce(traceId, line, isError = false) {
    const tagged = `[runErrand trace=${traceId}] ${line}`;
    if (isError) console.error(tagged);
    else console.log(tagged);
}

function bridgeCode(err) {
    return err instanceof BridgeClientError ? err.code : 'bridge_unknown';
}

function bridgeErrorLine(prefix, err) {
    const code = bridgeCode(err);
    const detail = err && err.message ? err.message : String(err);
    return `${prefix} [${code}]: ${detail}`;
}

function isBridgeUnavailable(err) {
    const code = bridgeCode(err);
    return code === 'bridge_unreachable' || code === 'bridge_overloaded';
}

function alphaOnly(agent) {
    if (agent === null || agent === undefined) return agent;
    const kind = typeof agent;
    if (kind !== 'object' && kind !== 'function') return agent;
    return new Proxy(agent, {
        get(target, prop, receiver) {
            if (prop === CHAT_METHOD) return undefined;
            return Reflect.get(target, prop, receiver);
        },
    });
}

async function pollErrand(traceId) {
    const response = await callBridge({
        service: 'errand',
        method: 'poll',
        payload: { agent_id: ALPHA_AGENT_ID },
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: ALPHA_AGENT_ID,
        costContext: {
            agent_tier: 'errand',
            budget_bucket: 'bridge',
            estimated_cost_usd: 0.0,
        },
        traceId,
    });
    return response && response.payload ? response.payload : {};
}

async function reportCompletion(traceId, payload) {
    return callBridge({
        service: 'errand',
        method: 'complete',
        payload,
        deadlineMs: BRIDGE_REPORT_TIMEOUT_MS,
        agentId: ALPHA_AGENT_ID,
        costContext: {
            agent_tier: 'errand',
            budget_bucket: 'bridge',
            estimated_cost_usd: 0.0,
        },
        traceId,
    });
}

function lineHasAny(line, needles) {
    const haystack = String(line || '').toLowerCase();
    return needles.some((needle) => haystack.includes(needle));
}

function classifyStepResult(step, line) {
    const detail = String(line || '');
    const bridgeDown = lineHasAny(detail, ['bridge unavailable', 'safe-idling']);
    if (bridgeDown) {
        return {
            action_id: step.action_id,
            status: 'failure',
            detail: `bridge unavailable: ${detail}`,
            bridge_unavailable: true,
        };
    }

    if (step.action === 'navigate') {
        if (lineHasAny(detail, ['reached:'])) {
            return { action_id: step.action_id, status: 'success', detail };
        }
        if (lineHasAny(detail, ['partial:'])) {
            return { action_id: step.action_id, status: 'partial', detail };
        }
        return { action_id: step.action_id, status: 'failure', detail };
    }

    if (step.action === 'place') {
        if (lineHasAny(detail, ['placed:'])) {
            return { action_id: step.action_id, status: 'success', detail };
        }
        if (lineHasAny(detail, ['partial:'])) {
            return { action_id: step.action_id, status: 'partial', detail };
        }
        return { action_id: step.action_id, status: 'failure', detail };
    }

    return { action_id: step.action_id, status: 'failure', detail: `unknown step ${step.action}` };
}

async function performStep(agent, step) {
    if (step.action === 'navigate') {
        return navigateAction.perform(
            agent,
            step.action_id,
            step.navigate.target,
            step.navigate.arrive_within_blocks,
            step.navigate.timeout_ms,
        );
    }
    if (step.action === 'place') {
        return placeAction.perform(
            agent,
            step.action_id,
            step.place.block_type,
            step.place.position,
            step.place.face,
            step.place.source_slot,
        );
    }
    return `invalid: unknown step ${step.action}`;
}

function completionPayload(taskId, overall, detail, stepResults) {
    const symbol = SYMBOLS.has(overall.symbol) ? overall.symbol : '?';
    return {
        task_id: taskId,
        status: overall.status,
        symbol,
        detail,
        step_results: stepResults.map((step) => ({
            action_id: step.action_id,
            status: step.status,
            detail: step.detail || '',
        })),
    };
}

async function finish(traceId, taskId, overall, detail, stepResults) {
    const payload = completionPayload(taskId, overall, detail, stepResults);
    await reportCompletion(traceId, payload);
    const line = `errand ${taskId} ${payload.symbol} ${payload.status}: ${detail}`;
    announce(traceId, line, payload.status !== 'success');
    return line;
}

export const runErrandAction = {
    name: '!runErrand',
    description: 'Poll, execute, and report one structured Alpha errand.',
    params: {},
    perform: async function (agent) {
        const traceId = `trace-${randomUUID()}`;
        let pending;
        try {
            pending = await pollErrand(traceId);
        } catch (err) {
            const line = bridgeErrorLine(
                isBridgeUnavailable(err)
                    ? 'bridge unavailable, safe-idling'
                    : 'run errand poll failed',
                err,
            );
            announce(traceId, line, true);
            return line;
        }

        if (!pending.task_id) {
            const idle = 'no errand pending';
            announce(traceId, idle);
            return idle;
        }

        const taskId = String(pending.task_id);
        const parsed = parseErrandPlan(String(pending.task || ''));
        if (parsed.error) {
            const detail = `malformed errand plan: ${parsed.error}`;
            try {
                return await finish(
                    traceId,
                    taskId,
                    { status: 'failure', symbol: '?' },
                    detail,
                    [],
                );
            } catch (err) {
                const line = bridgeErrorLine(`errand ${taskId} ? completion failed`, err);
                announce(traceId, line, true);
                return line;
            }
        }

        const actor = alphaOnly(agent);
        const stepResults = [];
        let bridgeAbort = false;
        for (const step of parsed.steps) {
            try {
                const line = await performStep(actor, step);
                const result = classifyStepResult(step, line);
                stepResults.push(result);
                announce(traceId, `${step.action} ${step.action_id}: ${result.status}`);
                if (result.bridge_unavailable) {
                    bridgeAbort = true;
                    break;
                }
            } catch (err) {
                const detail = bridgeErrorLine(`${step.action} ${step.action_id} failed`, err);
                stepResults.push({
                    action_id: step.action_id,
                    status: 'failure',
                    detail,
                    bridge_unavailable: isBridgeUnavailable(err),
                });
                announce(traceId, detail, true);
                if (isBridgeUnavailable(err)) {
                    bridgeAbort = true;
                    break;
                }
            }
        }

        const overall = bridgeAbort
            ? { status: 'failure', symbol: '?' }
            : deriveOverallStatus(stepResults);
        const detail = bridgeAbort
            ? 'bridge unavailable'
            : `${stepResults.length}/${parsed.steps.length} steps finished`;

        try {
            return await finish(traceId, taskId, overall, detail, stepResults);
        } catch (err) {
            const line = bridgeErrorLine(`errand ${taskId} completion failed`, err);
            announce(traceId, line, true);
            return line;
        }
    },
};

export default runErrandAction;

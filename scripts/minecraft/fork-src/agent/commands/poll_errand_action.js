// Alpha `!pollErrand` bridge action for E7-2 (#566).
//
// This is a non-verbal action: it logs the pending errand and returns a status
// string to Mindcraft, but it does not send Minecraft chat. A down or saturated
// bridge degrades to safe-idle and never throws out of perform.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';

const BRIDGE_REPORT_TIMEOUT_MS = 5000;
const ALPHA_AGENT_ID = 'alpha';

function announce(traceId, line, isError = false) {
    const tagged = `[pollErrand trace=${traceId}] ${line}`;
    if (isError) console.error(tagged);
    else console.log(tagged);
}

function bridgeErrorLine(prefix, err) {
    const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
    const detail = err && err.message ? err.message : String(err);
    return `${prefix} [${code}]: ${detail}`;
}

export const pollErrandAction = {
    name: '!pollErrand',
    description: 'Poll the Python bridge for Alpha errands.',
    params: {},
    perform: async function (_agent) {
        const traceId = `trace-${randomUUID()}`;

        try {
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
            const payload = response && response.payload ? response.payload : {};
            if (!payload.task_id) {
                const idle = 'no errand pending';
                announce(traceId, idle);
                return idle;
            }
            const line = `errand ${payload.task_id}: ${payload.task}`;
            announce(traceId, line);
            return line;
        } catch (err) {
            const code = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
            if (code === 'bridge_unreachable' || code === 'bridge_overloaded') {
                const idle = bridgeErrorLine('bridge unavailable, safe-idling', err);
                announce(traceId, idle, true);
                return idle;
            }
            const line = bridgeErrorLine('poll errand failed', err);
            announce(traceId, line, true);
            return line;
        }
    },
};

export default pollErrandAction;


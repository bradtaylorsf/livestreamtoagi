// `!executeCode` custom Mindcraft action for E6-5 (#560).
//
// This keeps code-writing as a tool alongside embodied building by routing the
// action through the Python bridge's `code.execute` verb. Python delegates to
// the existing ExecuteCodeTool sandbox; this action does not create a second
// sandbox and never treats a bridge outage as permission to run code locally.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';

const DEFAULT_CODE_DEADLINE_MS = 35000;
const DEADLINE_GRACE_MS = 5000;
const MAX_SNIPPET_CHARS = 240;

function agentId(agent) {
    const bot = agent && agent.bot ? agent.bot : agent;
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function positiveInteger(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
}

function snippet(value) {
    if (value === undefined || value === null || value === '') return '';
    const text = String(value).replace(/\s+/g, ' ').trim();
    return text.length <= MAX_SNIPPET_CHARS ? text : `${text.slice(0, MAX_SNIPPET_CHARS)}...`;
}

function announce(agent, traceId, line, isError = false) {
    try {
        if (agent && typeof agent.openChat === 'function') agent.openChat(line);
    } catch {
        /* chat is cosmetic; never let it mask the bridge result */
    }
    const tagged = `[executeCode trace=${traceId}] ${line}`;
    if (isError) console.error(tagged);
    else console.log(tagged);
}

function bridgeErrorCode(err) {
    return err instanceof BridgeClientError ? err.code : 'bridge_unknown';
}

function bridgeErrorDetail(err) {
    return err && err.message ? err.message : String(err);
}

export const executeCodeAction = {
    name: '!executeCode',
    description: 'Run Python or JavaScript through the Python sandbox bridge.',
    params: {
        language: {
            type: 'string',
            description: 'python or javascript.',
        },
        code: {
            type: 'string',
            description: 'Source code to execute in the sandbox.',
        },
        timeout: {
            type: 'number',
            description: 'Optional sandbox timeout in seconds.',
        },
    },
    perform: async function (agent, language, code, timeout) {
        const traceId = `trace-${randomUUID()}`;
        const runtime = language === undefined || language === null ? 'python' : String(language);
        const payload = {
            language: runtime,
            code: code === undefined || code === null ? '' : String(code),
        };
        const timeoutSeconds = positiveInteger(timeout);
        if (timeoutSeconds !== null) payload.timeout = timeoutSeconds;

        try {
            const response = await callBridge({
                service: 'code',
                method: 'execute',
                payload,
                deadlineMs:
                    timeoutSeconds === null
                        ? DEFAULT_CODE_DEADLINE_MS
                        : timeoutSeconds * 1000 + DEADLINE_GRACE_MS,
                agentId: agentId(agent),
                traceId,
            });
            const result = response && response.payload ? response.payload : {};
            const status = result.status || 'unknown';
            let line;
            if (status === 'ok') {
                const output = snippet(result.stdout || result.stderr || '');
                line = `code execution ok (exit ${result.exit_code}): ${output}`;
            } else {
                line = `code execution ${status}: ${result.reason || 'no detail'}`;
            }
            announce(agent, traceId, line, status !== 'ok');
            return line;
        } catch (err) {
            const codeValue = bridgeErrorCode(err);
            const detail = bridgeErrorDetail(err);
            if (codeValue === 'bridge_unreachable' || codeValue === 'bridge_overloaded') {
                const line = `bridge unavailable, safe-idling [${codeValue}]: ${detail}`;
                announce(agent, traceId, line, true);
                return line;
            }
            const line = `code execution failed [${codeValue}]: ${detail}`;
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default executeCodeAction;

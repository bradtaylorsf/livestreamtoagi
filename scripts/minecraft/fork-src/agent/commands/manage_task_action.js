// `!manageTask` custom Mindcraft action for E21-7g.
//
// Bridges the embodied Mindcraft bots to the shared task board (the Python
// `manage_task` / SharedWorkingState blackboard) so the emergent loop —
// observe -> propose -> claim -> execute -> report — actually runs end to end.
// Without this, JS bots can place blocks but cannot create/claim/complete the
// shared tasks that the Director, civilization ledgers, and evals read; they
// fall back to ad-hoc public chat. This routes every task op through the
// existing `shared_state.write` bridge verb (operation=task_*); a bridge outage
// is never treated as success — the action returns a safe-idle status string.

import { randomUUID } from 'node:crypto';

import { BridgeClientError, callBridge } from '../bridge/python_bridge.js';

const TASK_DEADLINE_MS = 5000;
const MAX_SUMMARY_CHARS = 600;

function agentId(agent) {
    const bot = agent && agent.bot ? agent.bot : agent;
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function clip(value, max = MAX_SUMMARY_CHARS) {
    if (value === undefined || value === null || value === '') return '';
    const text = String(value).trim();
    return text.length <= max ? text : `${text.slice(0, max)}...`;
}

function announce(agent, traceId, line, isError = false) {
    try {
        if (agent && typeof agent.openChat === 'function') agent.openChat(line);
    } catch {
        /* chat is cosmetic; never let it mask the bridge result */
    }
    const tagged = `[manageTask trace=${traceId}] ${line}`;
    if (isError) console.error(tagged);
    else console.log(tagged);
}

// Map the human-facing first arg to a shared_state.write operation + payload.
function buildRequest(action, target, detail) {
    const verb = String(action === undefined || action === null ? '' : action)
        .trim()
        .toLowerCase();
    const arg = target === undefined || target === null ? '' : String(target).trim();
    const extra = detail === undefined || detail === null ? '' : String(detail).trim();
    if (verb === 'create' || verb === 'propose' || verb === 'add') {
        if (!arg) return { error: 'manageTask create requires a task title' };
        return { operation: 'task_create', payload: { operation: 'task_create', task_title: arg } };
    }
    if (verb === 'claim' || verb === 'take') {
        if (!arg) return { error: 'manageTask claim requires a task id' };
        return { operation: 'task_claim', payload: { operation: 'task_claim', task_id: arg } };
    }
    if (verb === 'complete' || verb === 'done' || verb === 'finish') {
        if (!arg) return { error: 'manageTask complete requires a task id' };
        const payload = { operation: 'task_complete', task_id: arg };
        if (extra) payload.task_evidence = extra;
        return { operation: 'task_complete', payload };
    }
    if (verb === '' || verb === 'list' || verb === 'read' || verb === 'board') {
        return { operation: 'task_list', payload: { operation: 'task_list' } };
    }
    return {
        error: `unknown manageTask action '${verb}'; use create|claim|complete|list`,
    };
}

function summarize(operation, result) {
    const taskId = result.task_id || '';
    const status = result.task_status || '';
    const owner = result.task_owner || '';
    if (operation === 'task_create') {
        return `proposed task ${taskId} to the shared board — claim it with !manageTask("claim","${taskId}")`;
    }
    if (operation === 'task_claim') {
        if (status === 'ok') return `claimed ${taskId} — now executing it`;
        if (status === 'already_claimed') return `${taskId} already claimed by ${owner || 'someone'}`;
        if (status === 'not_found') return `task ${taskId} not found`;
        return `claim ${taskId}: ${status}`;
    }
    if (operation === 'task_complete') {
        return status === 'done' ? `completed ${taskId}` : `complete ${taskId}: ${status}`;
    }
    // task_list — surface the rendered board from the blackboard summary.
    return `task board:\n${clip(result.formatted || '(empty board)')}`;
}

export const manageTaskAction = {
    name: '!manageTask',
    description:
        'Use the shared task board. action=create|claim|complete|list. '
        + 'create: target=task title. claim/complete: target=task id (from list). '
        + 'Example: !manageTask("create","build a watchtower").',
    params: {
        action: { type: 'string', description: 'create | claim | complete | list' },
        target: {
            type: 'string',
            description: 'Task title (for create) or task id (for claim/complete).',
        },
        detail: { type: 'string', description: 'Optional completion evidence (for complete).' },
    },
    perform: async function (agent, action, target, detail) {
        const traceId = `trace-${randomUUID()}`;
        const request = buildRequest(action, target, detail);
        if (request.error) {
            announce(agent, traceId, `manageTask: ${request.error}`, true);
            return `manageTask: ${request.error}`;
        }

        try {
            const response = await callBridge({
                service: 'shared_state',
                method: 'write',
                payload: request.payload,
                deadlineMs: TASK_DEADLINE_MS,
                agentId: agentId(agent),
                traceId,
            });
            const result = response && response.payload ? response.payload : {};
            const line = summarize(request.operation, result);
            announce(agent, traceId, line, false);
            return line;
        } catch (err) {
            const codeValue = err instanceof BridgeClientError ? err.code : 'bridge_unknown';
            const detailMsg = err && err.message ? err.message : String(err);
            if (codeValue === 'bridge_unreachable' || codeValue === 'bridge_overloaded') {
                const line = `task board unavailable, safe-idling [${codeValue}]: ${detailMsg}`;
                announce(agent, traceId, line, true);
                return line;
            }
            const line = `manageTask failed [${codeValue}]: ${detailMsg}`;
            announce(agent, traceId, line, true);
            return line;
        }
    },
};

export default manageTaskAction;

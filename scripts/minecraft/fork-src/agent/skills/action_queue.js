// Per-agent action serialization for staged Mindcraft clones.
//
// The stock ActionManager stops the current action before starting the next one.
// In a multi-agent crowd that creates self-interruption loops around placeHere,
// movement, and buildFromPlan. This wrapper gives each agent one active action
// slot and a bounded FIFO of deferred actions.

import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const PATCH_FLAG = Symbol.for('livestreamtoagi.actionQueueInstalled');
const DEFAULT_MAX_QUEUE = 16;

function intEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function agentId(manager) {
    const agent = manager && manager.agent;
    return (agent && agent.name) || process.env.LTAG_AGENT_ID || process.env.MC_AGENT_ID || 'agent';
}

function emit(manager, type, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentId(manager),
        payload: {
            active_action: manager.currentActionLabel || null,
            queue_depth: manager.__ltagActionQueue?.pending?.length || 0,
            ...payload,
        },
    });
}

function busyResult(actionLabel, reason) {
    return {
        success: false,
        message: `busy: action ${actionLabel} ${reason}`,
        interrupted: false,
        timedout: false,
        busy: true,
        queued: false,
    };
}

async function drain(manager, originalExecute) {
    const state = manager.__ltagActionQueue;
    if (!state || state.draining || manager.executing) return;
    state.draining = true;
    try {
        while (!manager.executing && state.pending.length > 0) {
            const next = state.pending.shift();
            emit(manager, 'action.started', {
                action: next.actionLabel,
                source: 'queued',
                remaining_depth: state.pending.length,
            });
            try {
                const result = await originalExecute.call(
                    manager,
                    next.actionLabel,
                    next.actionFn,
                    next.timeout,
                );
                emit(manager, 'action.completed', {
                    action: next.actionLabel,
                    success: Boolean(result && result.success),
                    interrupted: Boolean(result && result.interrupted),
                    timedout: Boolean(result && result.timedout),
                    source: 'queued',
                });
                next.resolve(result);
            } catch (err) {
                emit(manager, 'action.completed', {
                    action: next.actionLabel,
                    success: false,
                    source: 'queued',
                    error: err && err.message ? err.message : String(err),
                });
                next.reject(err);
            }
        }
    } finally {
        state.draining = false;
    }
}

export function installActionQueue(manager, options = {}) {
    if (!manager || typeof manager._executeAction !== 'function' || manager[PATCH_FLAG]) {
        return manager;
    }

    const originalExecute = manager._executeAction;
    const maxQueue = options.maxQueue ?? intEnv('MINECRAFT_ACTION_QUEUE_MAX', DEFAULT_MAX_QUEUE);
    manager.__ltagActionQueue = { pending: [], draining: false };

    manager._executeAction = async function queuedExecuteAction(actionLabel, actionFn, timeout = 10) {
        const label = String(actionLabel || 'action');
        const state = this.__ltagActionQueue;

        if (this.executing || state.draining) {
            if (state.pending.length >= maxQueue) {
                console.warn(
                    `[action-status] ${agentId(this)} rejected ${label}; action queue is full (${maxQueue})`,
                );
                emit(this, 'action.rejected_busy', {
                    action: label,
                    reason: 'queue_full',
                    max_queue: maxQueue,
                });
                return busyResult(label, 'rejected because the queue is full');
            }
            console.log(
                `[action-status] ${agentId(this)} queued action "${label}" behind "${this.currentActionLabel || 'current action'}"`,
            );
            emit(this, 'action.queued', {
                action: label,
                queued_behind: this.currentActionLabel || null,
            });
            return new Promise((resolve, reject) => {
                state.pending.push({ actionLabel: label, actionFn, timeout, resolve, reject });
            });
        }

        emit(this, 'action.started', { action: label, source: 'direct' });
        try {
            const result = await originalExecute.call(this, label, actionFn, timeout);
            emit(this, 'action.completed', {
                action: label,
                success: Boolean(result && result.success),
                interrupted: Boolean(result && result.interrupted),
                timedout: Boolean(result && result.timedout),
            });
            return result;
        } finally {
            void drain(this, originalExecute);
        }
    };

    Object.defineProperty(manager, PATCH_FLAG, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
    return manager;
}

export default installActionQueue;

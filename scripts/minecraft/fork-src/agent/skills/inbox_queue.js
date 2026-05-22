// Per-agent chat inbox batching for multi-agent Mindcraft soaks.
//
// Mindcraft's stock Agent.handleMessage path lets overlapping generations race
// and then drops an expensive response if another message arrives mid-call. This
// wrapper serializes conversation turns per agent: incoming chat is batched,
// debounced, and any messages that arrive while a model call is running are kept
// for the next turn.

import { emitTimelineEvent } from '../bridge/timeline_emitter.js';
import { containsCommand } from '../commands/index.js';
import convoManager from '../conversation.js';

const PATCH_FLAG = Symbol.for('livestreamtoagi.inboxQueueInstalled');
const DEFAULT_DEBOUNCE_MS = 2000;
const DEFAULT_MAX_BATCH = 12;
const DEFAULT_MAX_MESSAGE_CHARS = 320;
const DEFAULT_MAX_BATCH_CHARS = 2400;
const COMMAND_PARSE_ERROR_RE =
    /^Command\s+![A-Za-z]\w*\s+was given\s+\d+\s+args?,\s+but requires\s+\d+\s+args?\.?$/i;
const USED_COMMAND_STATUS_RE = /^\*[A-Za-z][A-Za-z0-9_-]*\s+used\s+[A-Za-z]\w*\*\s*$/i;
const DEFAULT_BOT_NAMES = [
    'alpha',
    'aurora',
    'bridge',
    'bridgebot',
    'fork',
    'grok',
    'pixel',
    'rex',
    'sentinel',
    'vera',
];

function intEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function agentId(agent) {
    return (agent && agent.name) || process.env.LTAG_AGENT_ID || process.env.MC_AGENT_ID || 'agent';
}

function clip(value, limit) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1)).trim()}...`;
}

function knownBotNames() {
    const fromEnv = String(process.env.SOAK_BOTS || '')
        .split(/\s+/)
        .map((name) => name.trim().toLowerCase())
        .filter(Boolean);
    return new Set([...DEFAULT_BOT_NAMES, ...fromEnv]);
}

function isKnownBotSource(agent, source) {
    const name = String(source || '').trim();
    if (!name || name.toLowerCase() === 'system' || name === agent?.name) return false;
    if (agent && typeof agent.__ltagIsOtherAgent === 'function') {
        try {
            if (agent.__ltagIsOtherAgent(name)) return true;
        } catch {
            // Fall back to the static soak roster below.
        }
    }
    return knownBotNames().has(name.toLowerCase());
}

function isTelemetryOnlyMessage(agent, source, message) {
    const text = String(message || '').trim();
    if (!text) return false;
    if (COMMAND_PARSE_ERROR_RE.test(text) || USED_COMMAND_STATUS_RE.test(text)) {
        return true;
    }
    if (isKnownBotSource(agent, source) && containsCommand(text)) {
        return true;
    }
    if (/^(I'm stuck!?|I'm free\.?|unstuck timed out(?: before recovery)?|Restarting\.|Exiting\.)$/i.test(text)) {
        return true;
    }
    return (
        /^(mode-status|behavior-status|heartbeat|action-status)\b/i.test(text) ||
        (/^interrupted:\s*unstuck-failed/i.test(text) && String(source || '').toLowerCase() === 'system')
    );
}

function hasImmediateUserCommand(agent, source, message) {
    if (!agent || !source || source === 'system' || source === agent.name) return false;
    const command = containsCommand(String(message || ''));
    if (!command) return false;
    const fromOtherBot = isKnownBotSource(agent, source);
    if (fromOtherBot) return false;
    return true;
}

function batchSource(batch) {
    const interactive = [...batch].reverse().find((entry) => {
        const source = String(entry.source || '');
        return source && source !== 'system';
    });
    return interactive ? interactive.source : batch[batch.length - 1]?.source || 'system';
}

function batchMaxResponses(batch) {
    for (const entry of [...batch].reverse()) {
        if (entry.maxResponses !== null && entry.maxResponses !== undefined) return entry.maxResponses;
    }
    return null;
}

function compactBatchMessage(batch, options) {
    if (batch.length === 1) return String(batch[0].message || '');
    const lines = [];
    let remainingChars = options.maxBatchChars;
    for (const entry of batch.slice(-options.maxBatch)) {
        const line = `- ${entry.source}: ${clip(entry.message, options.maxMessageChars)}`;
        if (line.length > remainingChars && lines.length > 0) break;
        lines.push(line);
        remainingChars -= line.length + 1;
    }
    return [
        `Incoming message batch since your last turn (${batch.length} messages):`,
        ...lines,
        'Respond once to the batch. Address the newest actionable request and keep any earlier useful context in mind.',
    ].join('\n');
}

function emit(agent, type, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentId(agent),
        payload: {
            queue_depth: agent.__ltagInboxQueue?.pending?.length || 0,
            ...payload,
        },
    });
}

async function runTurnQueue(agent, originalHandleMessage, options) {
    const state = agent.__ltagInboxQueue;
    if (!state || state.running) return;
    state.running = true;
    try {
        while (state.pending.length > 0) {
            const batch = state.pending.splice(0, options.maxBatch);
            let source = batchSource(batch);
            let message = compactBatchMessage(batch, options);
            let maxResponses = batchMaxResponses(batch);
            emit(agent, 'inbox.turn_started', {
                batch_size: batch.length,
                source,
                message_preview: clip(message, 220),
            });
            let result;
            try {
                const gate = state && typeof state.beforeTurn === 'function' ? state.beforeTurn : null;
                if (gate) {
                    const verdict = await gate.call(agent, {
                        batch,
                        source,
                        message,
                        maxResponses,
                        queueDepth: state.pending.length,
                    });
                    if (verdict && verdict.selected === false) {
                        result = verdict.result ?? false;
                        for (const entry of batch) entry.resolve(result);
                        emit(agent, 'inbox.turn_completed', {
                            batch_size: batch.length,
                            outcome: verdict.outcome || 'director_suppressed',
                            remaining_depth: state.pending.length,
                        });
                        continue;
                    }
                    if (verdict && typeof verdict.source === 'string') source = verdict.source;
                    if (verdict && typeof verdict.message === 'string') message = verdict.message;
                    if (verdict && Object.hasOwn(verdict, 'maxResponses')) {
                        maxResponses = verdict.maxResponses;
                    }
                }
                result = await originalHandleMessage.call(agent, source, message, maxResponses);
                for (const entry of batch) entry.resolve(result);
                emit(agent, 'inbox.turn_completed', {
                    batch_size: batch.length,
                    outcome: 'ok',
                    remaining_depth: state.pending.length,
                });
            } catch (err) {
                for (const entry of batch) entry.reject(err);
                emit(agent, 'inbox.turn_completed', {
                    batch_size: batch.length,
                    outcome: 'error',
                    error: err && err.message ? err.message : String(err),
                    remaining_depth: state.pending.length,
                });
            }
        }
    } finally {
        state.running = false;
        if (state.pending.length > 0) scheduleTurn(agent, originalHandleMessage, options);
    }
}

function scheduleTurn(agent, originalHandleMessage, options) {
    const state = agent.__ltagInboxQueue;
    if (!state || state.running) return;
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(() => {
        state.timer = null;
        void runTurnQueue(agent, originalHandleMessage, options);
    }, options.debounceMs);
}

export function installInboxQueue(agent, options = {}) {
    if (!agent || typeof agent.handleMessage !== 'function' || agent[PATCH_FLAG]) return agent;

    const originalHandleMessage = agent.handleMessage;
    const installedOptions = {
        debounceMs: options.debounceMs ?? intEnv('MINECRAFT_TURN_DEBOUNCE_MS', DEFAULT_DEBOUNCE_MS),
        maxBatch: options.maxBatch ?? intEnv('MINECRAFT_TURN_BATCH_MAX', DEFAULT_MAX_BATCH),
        maxMessageChars:
            options.maxMessageChars ??
            intEnv('MINECRAFT_TURN_MESSAGE_MAX_CHARS', DEFAULT_MAX_MESSAGE_CHARS),
        maxBatchChars:
            options.maxBatchChars ?? intEnv('MINECRAFT_TURN_BATCH_MAX_CHARS', DEFAULT_MAX_BATCH_CHARS),
    };
    agent.__ltagInboxQueue = {
        pending: [],
        running: false,
        timer: null,
        beforeTurn: null,
    };
    agent.__ltagIsOtherAgent =
        options.isOtherAgent ||
        ((source) => {
            try {
                return convoManager.isOtherAgent(source);
            } catch {
                return false;
            }
        });

    agent.handleMessage = function queuedHandleMessage(source, message, maxResponses = null) {
        if (!source || !message) {
            return originalHandleMessage.call(this, source, message, maxResponses);
        }
        if (isTelemetryOnlyMessage(this, source, message)) {
            console.log('[inbox-telemetry]', agentId(this) + ':', `${source}: ${message}`);
            emit(this, 'inbox.telemetry_ignored', {
                source: String(source),
                message: clip(message, 220),
            });
            return Promise.resolve(false);
        }
        if (hasImmediateUserCommand(this, source, message)) {
            emit(this, 'inbox.immediate_command', {
                source: String(source),
                command: containsCommand(String(message || '')),
            });
            return originalHandleMessage.call(this, source, message, maxResponses);
        }

        return new Promise((resolve, reject) => {
            const state = this.__ltagInboxQueue;
            state.pending.push({
                source,
                message,
                maxResponses,
                queuedAt: Date.now(),
                resolve,
                reject,
            });
            emit(this, 'inbox.queued', {
                source: String(source),
                message_preview: clip(message, 180),
                running: state.running,
            });
            scheduleTurn(this, originalHandleMessage, installedOptions);
        });
    };

    Object.defineProperty(agent, PATCH_FLAG, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
    return agent;
}

export default installInboxQueue;

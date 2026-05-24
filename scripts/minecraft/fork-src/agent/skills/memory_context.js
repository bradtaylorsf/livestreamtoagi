// Runtime Python-memory context for Mindcraft prompt decisions.
//
// This is deliberately best-effort: memory should shape decisions when the
// bridge is healthy, but a memory outage must never crash a bot turn.

import { randomUUID } from 'node:crypto';

import { callBridge } from '../bridge/python_bridge.js';
import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const DEFAULT_RECALL_LIMIT = 3;
const DEFAULT_CORE_MAX_CHARS = 1500;
const DEFAULT_RECALL_MAX_CHARS = 1200;
const DEFAULT_RECENT_EVENTS = 5;
const DEFAULT_DEADLINE_MS = 1500;
const DEFAULT_RUN_ID = 'run-local';
const DEFAULT_SIMULATION_ID = '00000000-0000-0000-0000-000000000000';
const DEFAULT_EXCLUDED_AGENTS = Object.freeze(['management', 'alpha']);

function hasEnv(name) {
    return Object.hasOwn(process.env, name);
}

function isFalseLike(value) {
    return ['0', 'false', 'no', 'off', 'disabled'].includes(String(value).trim().toLowerCase());
}

function enabledByEnv() {
    if (!hasEnv('MC_SIM_MEMORY_CONTEXT_ENABLED')) return true;
    return !isFalseLike(process.env.MC_SIM_MEMORY_CONTEXT_ENABLED);
}

function intEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function agentId(agent) {
    const bot = agent && agent.bot ? agent.bot : null;
    return String(
        (agent && (agent.name || agent.agent_id || agent.id)) ||
            (bot && bot.username) ||
            process.env.LTAG_AGENT_ID ||
            process.env.MC_AGENT_ID ||
            'agent',
    );
}

function excludedAgents() {
    if (!hasEnv('MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS')) {
        return new Set(DEFAULT_EXCLUDED_AGENTS);
    }
    return new Set(
        String(process.env.MC_SIM_MEMORY_CONTEXT_EXCLUDE_AGENTS || '')
            .split(',')
            .flatMap((part) => part.split(/\s+/))
            .map((part) => part.trim().toLowerCase())
            .filter(Boolean),
    );
}

function runId() {
    return process.env.LTAG_RUN_ID || process.env.MC_RUN_ID || DEFAULT_RUN_ID;
}

function simulationId() {
    return process.env.LTAG_SIMULATION_ID || process.env.MC_SIMULATION_ID || DEFAULT_SIMULATION_ID;
}

function runMode(value) {
    return (
        value ||
        process.env.MC_SIM_RUN_MODE ||
        process.env.SOAK_PROFILE ||
        process.env.CONVERSATION_MODE ||
        'default'
    );
}

function normalizeText(value) {
    return String(value ?? '')
        .replace(/\r\n/g, '\n')
        .replace(/[ \t]+/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function clip(value, limit) {
    const text = normalizeText(value);
    if (!text || limit <= 0) return '';
    return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3)).trimEnd()}...`;
}

function eventText(event) {
    if (event === undefined || event === null) return '';
    if (typeof event === 'string') return clip(event, 260);
    if (typeof event !== 'object') return clip(String(event), 260);
    const source = event.source || event.agent || event.agent_id || event.event_kind || event.kind || 'event';
    const message =
        event.message ||
        event.event_text ||
        event.text ||
        event.summary ||
        event.action_label ||
        event.outcome ||
        '';
    return clip(`${source}: ${message}`, 260);
}

function recentEmbodiedEvents(agent, explicitEvents) {
    const events = [];
    const add = (value) => {
        const text = eventText(value);
        if (text) events.push(text);
    };

    if (Array.isArray(explicitEvents)) {
        for (const event of explicitEvents) add(event);
    } else if (explicitEvents) {
        add(explicitEvents);
    }

    const director = agent?.__ltagDirectorContext;
    if (director?.scene_digest) add({ source: 'director_scene', message: director.scene_digest });
    if (director?.build_macro?.support_task) {
        add({ source: 'support_task', message: director.build_macro.support_task });
    }

    const inbox = agent?.__ltagInboxQueue;
    if (Array.isArray(inbox?.pending)) {
        for (const entry of inbox.pending.slice(-DEFAULT_RECENT_EVENTS)) add(entry);
    }

    if (Array.isArray(agent?.__ltagRecentEmbodiedEvents)) {
        for (const event of agent.__ltagRecentEmbodiedEvents.slice(-DEFAULT_RECENT_EVENTS)) add(event);
    }

    return events.slice(-DEFAULT_RECENT_EVENTS);
}

function queryText({ query, currentGoal, recentEvents }) {
    const parts = [
        normalizeText(query),
        normalizeText(currentGoal),
        ...recentEvents.map((event) => normalizeText(event)),
    ].filter(Boolean);
    return clip(parts.join('\n'), 700) || 'current Minecraft simulation scene';
}

function formattedRecall(payload) {
    if (!payload || typeof payload !== 'object') return '';
    if (typeof payload.formatted === 'string' && payload.formatted.trim()) {
        return payload.formatted;
    }
    if (Array.isArray(payload.results) && payload.results.length > 0) {
        return payload.results
            .map((result) => `- ${result.memory_id || 'memory'}: ${result.content || ''}`)
            .join('\n');
    }
    return '';
}

function emit(agent, type, payload = {}, traceId = null) {
    emitTimelineEvent({
        type,
        agent: agentId(agent),
        traceId: traceId || payload.trace_id || payload.traceId,
        payload,
    });
}

function memoryCallPayload(tier, query, limit) {
    return { tier, query, limit };
}

async function fetchTier({ id, tier, query, limit, traceId, deadlineMs }) {
    const response = await callBridge({
        service: 'memory',
        method: 'recall',
        payload: memoryCallPayload(tier, query, limit),
        deadlineMs,
        agentId: id,
        traceId,
        costContext: {
            agent_tier: 'conversation',
            budget_bucket: 'memory-context',
            estimated_cost_usd: 0.0,
        },
    });
    return response && response.payload ? response.payload : {};
}

export function memoryContextEligibility(agent) {
    const id = agentId(agent);
    if (!enabledByEnv()) return { eligible: false, agentId: id, reason: 'disabled' };
    if (excludedAgents().has(id.toLowerCase())) {
        return { eligible: false, agentId: id, reason: 'excluded-agent' };
    }
    return { eligible: true, agentId: id, reason: 'enabled' };
}

export function buildMemoryContextBlock({
    id,
    run,
    simulation,
    mode,
    goal,
    recentEvents,
    coreMemory,
    recallMemory,
    coreMaxChars,
    recallMaxChars,
}) {
    const lines = [
        '[Python memory context]',
        `Run: ${run}`,
        `Simulation: ${simulation}`,
        `Run mode: ${mode}`,
        `Agent: ${id}`,
        `Current goal/task: ${clip(goal, 320) || 'not provided'}`,
        'Recent embodied events:',
    ];
    if (recentEvents.length > 0) {
        for (const event of recentEvents) lines.push(`- ${clip(event, 260)}`);
    } else {
        lines.push('- none supplied');
    }
    lines.push(
        'Core memory excerpt:',
        clip(coreMemory, coreMaxChars) || '(none supplied)',
        'Relevant recall snippets:',
        clip(recallMemory, recallMaxChars) || '(none supplied)',
        '[/Python memory context]',
    );
    return lines.join('\n');
}

export async function fetchMemoryContext({
    agent,
    query = '',
    traceId = null,
    runMode: requestedRunMode = null,
    currentGoal = '',
    recentEvents: explicitEvents = [],
} = {}) {
    const trace = traceId || `trace-memory-context-${randomUUID()}`;
    const eligibility = memoryContextEligibility(agent);
    if (!eligibility.eligible) {
        emit(
            agent,
            'memory_context.skipped',
            {
                reason: eligibility.reason,
                agent_id: eligibility.agentId,
                run_id: runId(),
                simulation_id: simulationId(),
                run_mode: runMode(requestedRunMode),
            },
            trace,
        );
        return '';
    }

    const recentEvents = recentEmbodiedEvents(agent, explicitEvents);
    const goal = currentGoal || query || 'current Minecraft simulation scene';
    const memoryQuery = queryText({ query, currentGoal: goal, recentEvents });
    const recallLimit = intEnv('MC_SIM_MEMORY_RECALL_LIMIT', DEFAULT_RECALL_LIMIT);
    const coreMaxChars = intEnv('MC_SIM_MEMORY_CORE_MAX_CHARS', DEFAULT_CORE_MAX_CHARS);
    const recallMaxChars = intEnv('MC_SIM_MEMORY_RECALL_MAX_CHARS', DEFAULT_RECALL_MAX_CHARS);
    const deadlineMs = intEnv('MC_SIM_MEMORY_CONTEXT_DEADLINE_MS', DEFAULT_DEADLINE_MS);

    try {
        const corePayload = await fetchTier({
            id: eligibility.agentId,
            tier: 'core',
            query: memoryQuery,
            limit: 1,
            traceId: trace,
            deadlineMs,
        });
        const recallPayload = await fetchTier({
            id: eligibility.agentId,
            tier: 'recall',
            query: memoryQuery,
            limit: recallLimit,
            traceId: trace,
            deadlineMs,
        });
        const coreMemory = typeof corePayload.core_memory === 'string' ? corePayload.core_memory : '';
        const recallMemory = formattedRecall(recallPayload);
        const block = buildMemoryContextBlock({
            id: eligibility.agentId,
            run: runId(),
            simulation: simulationId(),
            mode: runMode(requestedRunMode),
            goal,
            recentEvents,
            coreMemory,
            recallMemory,
            coreMaxChars,
            recallMaxChars,
        });
        emit(
            agent,
            'memory_context.fetched',
            {
                agent_id: eligibility.agentId,
                run_id: runId(),
                simulation_id: simulationId(),
                run_mode: runMode(requestedRunMode),
                core_chars: coreMemory.length,
                recall_chars: recallMemory.length,
                recall_limit: recallLimit,
                recent_event_count: recentEvents.length,
                context_chars: block.length,
            },
            trace,
        );
        return block;
    } catch (err) {
        emit(
            agent,
            'memory_context.error',
            {
                agent_id: eligibility.agentId,
                run_id: runId(),
                simulation_id: simulationId(),
                run_mode: runMode(requestedRunMode),
                error_code: err && err.code ? String(err.code) : 'memory_context_error',
                error: clip(err && err.message ? err.message : String(err), 180),
            },
            trace,
        );
        return '';
    }
}

export default { fetchMemoryContext, memoryContextEligibility, buildMemoryContextBlock };

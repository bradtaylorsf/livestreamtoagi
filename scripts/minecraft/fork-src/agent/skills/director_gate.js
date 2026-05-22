// Director V2 prompt gate for Mindcraft conversation turns.
//
// Installed after inbox_queue.js, this evaluates one compacted inbox batch
// through the Python Director scheduler before the stock Mindcraft
// shouldRespond/conversation path can enqueue an LLM call.

import { callBridge } from '../bridge/python_bridge.js';
import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const PATCH_FLAG = Symbol.for('livestreamtoagi.directorGateInstalled');
const DEFAULT_DEADLINE_MS = 1500;
const DEFAULT_TOOLS = Object.freeze([
    '!move',
    '!place',
    '!placeHere',
    '!break',
    '!nearbyBlocks',
    '!inventory',
]);

function isFalseLike(value) {
    return ['0', 'false', 'no', 'off', 'disabled'].includes(String(value).trim().toLowerCase());
}

function enabledByEnv() {
    if (process.env.DIRECTOR_V2_GATE && !isFalseLike(process.env.DIRECTOR_V2_GATE)) return true;
    return String(process.env.CONVERSATION_MODE || '').trim().toLowerCase() === 'director_v2';
}

function intEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function agentId(agent) {
    const bot = agent && agent.bot ? agent.bot : null;
    return (
        (agent && (agent.name || agent.agent_id || agent.id)) ||
        (bot && bot.username) ||
        process.env.LTAG_AGENT_ID ||
        process.env.MC_AGENT_ID ||
        'agent'
    );
}

function clip(value, limit = 240) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3)).trim()}...`;
}

function mentions(message) {
    const found = new Set();
    for (const match of String(message || '').matchAll(/@([A-Za-z][A-Za-z0-9_-]*)/g)) {
        found.add(match[1].toLowerCase());
    }
    return [...found].sort();
}

function position(agent) {
    const pos = agent?.bot?.entity?.position || agent?.bot?.player?.entity?.position;
    if (!pos) return null;
    const x = Number(pos.x);
    const y = Number(pos.y);
    const z = Number(pos.z);
    if (![x, y, z].every(Number.isFinite)) return null;
    return { x, y, z };
}

function availableTools(agent) {
    const tools = new Set(DEFAULT_TOOLS);
    if (process.env.MC_SIM_BUILD_MODE === 'plan') {
        tools.add('!planAndBuild');
        tools.add('!buildFromPlan');
    }
    const actionNames = agent?.actions?.actions || agent?.actions?.actionList || null;
    if (Array.isArray(actionNames)) {
        for (const name of actionNames) {
            const text = String(name || '').trim();
            if (text) tools.add(text.startsWith('!') ? text : `!${text}`);
        }
    }
    return [...tools].sort();
}

function sceneHint({ source, message, batch }) {
    const first = batch && batch[0] ? `${batch[0].source}:${clip(batch[0].message, 80)}` : '';
    const last =
        batch && batch.length > 0
            ? `${batch[batch.length - 1].source}:${clip(batch[batch.length - 1].message, 80)}`
            : `${source}:${clip(message, 80)}`;
    return `batch:${batch?.length || 1}:${first}:${last}`;
}

function emit(agent, type, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentId(agent),
        traceId: payload.trace_id || payload.traceId,
        payload,
    });
}

function filteredGrantedTools(verdict) {
    const tools = Array.isArray(verdict.granted_tools) ? verdict.granted_tools : [];
    const macro = verdict.build_macro || null;
    if (!macro) return tools;
    if (macro.role === 'planner_owner' && macro.granted === true) return tools;
    return tools.filter((tool) => tool !== '!planAndBuild');
}

function enrichMessage(message, verdict) {
    const observations = JSON.stringify(verdict.local_observations || {});
    const tools = filteredGrantedTools(verdict);
    const macro = verdict.build_macro || null;
    const lines = [
        '[Director V2 context]',
        `Scene: ${verdict.scene_digest || verdict.scene_id || 'unknown'}`,
        `Role: ${verdict.role || 'scene participant'}`,
        `Available tools: ${tools.length ? tools.join(', ') : 'ordinary chat only'}`,
        `Local observations: ${clip(observations, 900)}`,
    ];
    if (macro) {
        lines.push(
            `Build macro: ${macro.role || 'support'} owner=${macro.owner || 'unknown'} plan=${
                macro.plan_id || 'pending'
            }`,
        );
        if (macro.role !== 'planner_owner' && macro.support_task) {
            lines.push(`Support task: ${macro.support_task}`);
        }
    }
    lines.push(
        'Use this current scene context and ignore stale queued requests.',
        '[/Director V2 context]',
        '',
        String(message || ''),
    );
    return lines.join('\n');
}

async function askDirector(agent, turn, options, gateState) {
    const gateSeq = ++gateState.sequence;
    gateState.latestSequence = gateSeq;
    const payload = {
        agent_id: agentId(agent),
        event_kind: 'chat',
        event_text: String(turn.message || ''),
        source_agent: turn.source ? String(turn.source) : null,
        mentions: mentions(turn.message),
        position: position(agent),
        scene_hint: sceneHint(turn),
        available_tools: availableTools(agent),
    };
    const deadlineMs = options.deadlineMs ?? intEnv('DIRECTOR_V2_GATE_DEADLINE_MS', DEFAULT_DEADLINE_MS);

    let response;
    try {
        response = await callBridge({
            service: 'director',
            method: 'gate',
            payload,
            deadlineMs,
            agentId: agentId(agent),
            costContext: {
                agent_tier: 'conversation',
                budget_bucket: 'director-gate',
                estimated_cost_usd: 0.0,
            },
        });
    } catch (err) {
        emit(agent, 'director_gate.error', {
            outcome: err && err.code ? err.code : 'bridge_error',
            error: err && err.message ? err.message : String(err),
            queue_depth: turn.queueDepth || 0,
        });
        return { selected: true, message: turn.message };
    }

    if (gateSeq < gateState.latestSequence) {
        emit(agent, 'director_gate.stale_discarded', {
            scene_id: response?.payload?.scene_id,
            queue_depth: response?.payload?.queue_depth ?? turn.queueDepth ?? 0,
        });
        return { selected: false, result: false, outcome: 'director_stale_discarded' };
    }

    const verdict = response && response.payload ? response.payload : {};
    verdict.granted_tools = filteredGrantedTools(verdict);
    gateState.lastVerdict = verdict;
    agent.__ltagDirectorContext = verdict;
    if (verdict.selected) {
        emit(agent, 'director_gate.selected', {
            scene_id: verdict.scene_id,
            turn_kind: verdict.turn_kind,
            reason: verdict.reason,
            build_plan_id: verdict.build_macro?.plan_id,
            build_owner: verdict.build_macro?.owner,
            build_role: verdict.build_macro?.role,
            queue_depth: verdict.queue_depth ?? 0,
        });
        return {
            selected: true,
            message: enrichMessage(turn.message, verdict),
            maxResponses: turn.maxResponses,
        };
    }

    emit(agent, 'director_gate.suppressed', {
        scene_id: verdict.scene_id,
        suppression_reason: verdict.suppression_reason || 'fanout_capped',
        build_plan_id: verdict.build_macro?.plan_id,
        build_owner: verdict.build_macro?.owner,
        build_role: verdict.build_macro?.role,
        support_task: verdict.build_macro?.support_task,
        queue_depth: verdict.queue_depth ?? 0,
        suppressed_agents_count: Array.isArray(verdict.suppressed_agents)
            ? verdict.suppressed_agents.length
            : 0,
    });
    return { selected: false, result: false, outcome: 'director_suppressed' };
}

export function installDirectorGate(agent, options = {}) {
    if (!agent || typeof agent.handleMessage !== 'function' || agent[PATCH_FLAG]) return agent;
    const enabled = options.enabled !== undefined ? Boolean(options.enabled) : enabledByEnv();
    if (!enabled) return agent;

    const gateState = {
        sequence: 0,
        latestSequence: 0,
        lastVerdict: null,
    };
    agent.__ltagDirectorGate = gateState;

    if (agent.__ltagInboxQueue) {
        const previous = agent.__ltagInboxQueue.beforeTurn;
        agent.__ltagInboxQueue.beforeTurn = async function directorGateBeforeTurn(turn) {
            if (typeof previous === 'function') {
                const prior = await previous.call(this, turn);
                if (prior && prior.selected === false) return prior;
                if (prior && typeof prior.message === 'string') {
                    turn = { ...turn, ...prior };
                }
            }
            return askDirector(this, turn, options, gateState);
        };
    } else {
        const originalHandleMessage = agent.handleMessage;
        agent.handleMessage = async function directorGateHandleMessage(
            source,
            message,
            maxResponses = null,
        ) {
            const verdict = await askDirector(
                this,
                { source, message, maxResponses, batch: [], queueDepth: 0 },
                options,
                gateState,
            );
            if (verdict && verdict.selected === false) return verdict.result ?? false;
            return originalHandleMessage.call(
                this,
                verdict.source || source,
                verdict.message || message,
                Object.hasOwn(verdict, 'maxResponses') ? verdict.maxResponses : maxResponses,
            );
        };
    }

    Object.defineProperty(agent, PATCH_FLAG, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
    return agent;
}

export default installDirectorGate;

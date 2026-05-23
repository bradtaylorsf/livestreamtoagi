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
    '!placeHere',
    '!nearbyBlocks',
    '!inventory',
    '!searchForBlock',
]);
const LOCAL_SAFE_TOOLS = new Set([
    '!move',
    '!placeHere',
    '!nearbyBlocks',
    '!inventory',
    '!searchForBlock',
    '!craftable',
    '!getCraftingPlan',
]);
const STANDALONE_BUILD_TOOLS = new Set(['!placeHere', '!place', '!break', '!buildFromPlan']);
const RISKY_PROMPT_TOOLS = new Set([
    '!break',
    '!executeCode',
    '!navigate',
    '!newAction',
    '!observe',
    '!place',
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
    const planMode = process.env.MC_SIM_BUILD_MODE === 'plan';
    const tools = new Set(planMode ? DEFAULT_TOOLS.filter((tool) => !STANDALONE_BUILD_TOOLS.has(tool)) : DEFAULT_TOOLS);
    if (planMode) {
        tools.add('!planAndBuild');
    }
    const actionNames = agent?.actions?.actions || agent?.actions?.actionList || null;
    if (Array.isArray(actionNames)) {
        for (const name of actionNames) {
            const text = String(name || '').trim();
            if (!text) continue;
            const command = text.startsWith('!') ? text : `!${text}`;
            if (planMode && STANDALONE_BUILD_TOOLS.has(command)) continue;
            if (LOCAL_SAFE_TOOLS.has(command) || (planMode && command === '!planAndBuild')) {
                tools.add(command);
            }
        }
    }
    return [...tools].filter((tool) => !RISKY_PROMPT_TOOLS.has(tool)).sort();
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

function emitDecision(agent, verdict, turn, response) {
    const macro =
        verdict && verdict.build_macro && typeof verdict.build_macro === 'object'
            ? verdict.build_macro
            : {};
    const selected = Boolean(verdict && verdict.selected);
    const turnKind = verdict?.turn_kind || null;
    emitTimelineEvent({
        type: 'director.gate.decision',
        agent: agentId(agent),
        traceId: response?.trace_id || response?.traceId,
        payload: {
            scene_id: verdict?.scene_id,
            agent_id: agentId(agent),
            selected,
            selected_speaker: selected && turnKind === 'speaker' ? agentId(agent) : null,
            selected_action_owner: selected && turnKind === 'planner' ? agentId(agent) : null,
            turn_kind: turnKind,
            reason: verdict?.reason || (selected ? 'selected' : 'suppressed'),
            reason_code: selected
                ? verdict?.reason || 'selected'
                : verdict?.suppression_reason || 'fanout_capped',
            suppression_reason: verdict?.suppression_reason || null,
            suppressed_agents: Array.isArray(verdict?.suppressed_agents)
                ? verdict.suppressed_agents
                : [],
            suppressed_candidates: Array.isArray(verdict?.suppressed_agents)
                ? verdict.suppressed_agents
                : [],
            queue_depth: verdict?.queue_depth ?? turn.queueDepth ?? 0,
            scene_event_type: 'chat',
            source_agent: turn.source ? String(turn.source) : null,
            scene_hint: sceneHint(turn),
            available_tools: Array.isArray(verdict?.granted_tools) ? verdict.granted_tools : [],
            llm_prompt_count: selected ? 1 : 0,
            avoided_prompt_count: selected ? 0 : 1,
            build_plan_id: macro.plan_id || null,
            build_owner: macro.owner || null,
            build_role: macro.role || null,
            build_support_role: macro.support_role || null,
            estimated_usd: 0.0,
        },
    });
}

function filteredGrantedTools(verdict) {
    const tools = Array.isArray(verdict.granted_tools) ? verdict.granted_tools : [];
    const macro = verdict.build_macro || null;
    if (process.env.MC_SIM_BUILD_MODE === 'plan') {
        return tools.filter((tool) => {
            if (STANDALONE_BUILD_TOOLS.has(tool)) return false;
            if (tool === '!planAndBuild') return macro?.role === 'planner_owner' && macro.granted === true;
            return true;
        });
    }
    if (!macro) return tools;
    if (macro.role === 'planner_owner' && macro.granted === true) return tools;
    return tools.filter((tool) => tool !== '!planAndBuild');
}

function commandPolicy(verdict) {
    const macro = verdict.build_macro || null;
    if (process.env.MC_SIM_BUILD_MODE === 'plan' || macro) {
        if (macro?.role === 'planner_owner' && macro.granted === true) {
            return 'Command policy: Only the build owner should place blocks through !planAndBuild. Use exactly one concise !planAndBuild request for the shared structure, then let buildFromPlan finish. Do not use standalone placement, breaking, observation, navigation, execute-code, or JSON/object command arguments in local smoke.';
        }
        return 'Command policy: Support role only. Use ordinary chat, !inventory, !nearbyBlocks, or !searchForBlock when useful. Do not use plan/build commands, standalone placement, breaking, observation, navigation, execute-code, or JSON/object command arguments in local smoke.';
    }
    return 'Command policy: prefer one visible safe command: !placeHere("oak_log"), !placeHere("cobblestone"), or !move("heartbeat-scout", "forward", 2). Use !inventory, !nearbyBlocks, or !searchForBlock only when you need information. Do not use !place, !break, !observe, !navigate, !executeCode, or JSON/object arguments in local smoke.';
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
        commandPolicy(verdict),
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
        gateState.lastOutcome = {
            sequence: gateSeq,
            selected: true,
            outcome: 'bridge_error',
        };
        emit(agent, 'director_gate.error', {
            outcome: err && err.code ? err.code : 'bridge_error',
            error: err && err.message ? err.message : String(err),
            queue_depth: turn.queueDepth || 0,
        });
        return { selected: true, message: turn.message };
    }

    if (gateSeq < gateState.latestSequence) {
        gateState.lastOutcome = {
            sequence: gateSeq,
            selected: false,
            outcome: 'director_stale_discarded',
        };
        emit(agent, 'director_gate.stale_discarded', {
            scene_id: response?.payload?.scene_id,
            queue_depth: response?.payload?.queue_depth ?? turn.queueDepth ?? 0,
        });
        return { selected: false, result: false, outcome: 'director_stale_discarded' };
    }

    const verdict = response && response.payload ? response.payload : {};
    verdict.granted_tools = filteredGrantedTools(verdict);
    emitDecision(agent, verdict, turn, response);
    gateState.lastVerdict = verdict;
    gateState.lastOutcome = {
        sequence: gateSeq,
        selected: Boolean(verdict.selected),
        outcome: verdict.selected ? 'selected' : 'director_suppressed',
        scene_id: verdict.scene_id,
    };
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
            source: 'system',
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
        lastOutcome: null,
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

// Structured distress rescue command for local/easy Minecraft runs.

import { randomUUID } from 'node:crypto';

import { callBridge } from '../bridge/python_bridge.js';
import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const DEFAULT_DEADLINE_MS = 5000;

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || process.env.LTAG_AGENT_ID || 'bridge-bot';
}

function rescueMode() {
    const mode = String(process.env.RESCUE_MODE || process.env.MINECRAFT_RESCUE_MODE || 'standard')
        .trim()
        .toLowerCase();
    return ['easy', 'standard', 'production'].includes(mode) ? mode : 'standard';
}

function emit(agent, type, traceId, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentId(agent),
        traceId,
        payload,
    });
}

function targetPosition(agent, targetAgentId) {
    const bot = getBot(agent);
    const wanted = String(targetAgentId || '').toLowerCase();
    const players = bot?.players || {};
    const player = players[wanted] || Object.values(players).find((entry) => {
        const username = entry?.username || entry?.entity?.username || '';
        return String(username).toLowerCase() === wanted;
    });
    const pos = player?.entity?.position;
    if (!pos) return null;
    return { x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) };
}

async function navigateNear(agent, targetAgentId) {
    const bot = getBot(agent);
    const pos = targetPosition(agent, targetAgentId);
    if (!pos) return { ok: false, detail: `target ${targetAgentId} not visible` };
    try {
        const mod = await import('mineflayer-pathfinder');
        const goals = (mod && mod.goals) || (mod && mod.default && mod.default.goals);
        const GoalNear = goals && goals.GoalNear;
        if (!bot?.pathfinder?.goto || !GoalNear) {
            return { ok: false, detail: 'pathfinder unavailable' };
        }
        await bot.pathfinder.goto(new GoalNear(pos.x, pos.y, pos.z, 2));
        return { ok: true, detail: `navigated near ${targetAgentId}` };
    } catch (err) {
        return { ok: false, detail: err && err.message ? err.message : String(err) };
    }
}

async function easyTeleport(agent, targetAgentId) {
    const bot = getBot(agent);
    if (rescueMode() !== 'easy') {
        return { ok: false, detail: 'operator teleport fallback disabled outside easy mode' };
    }
    if (typeof bot?.chat !== 'function') {
        return { ok: false, detail: 'chat command unavailable for operator teleport' };
    }
    bot.chat(`/tp ${targetAgentId} ${agentId(agent)}`);
    return { ok: true, detail: `operator teleport fallback requested for ${targetAgentId}` };
}

async function reportResolution(agent, traceId, targetAgentId, status, detail, dangerId) {
    await callBridge({
        service: 'shared_state',
        method: 'write',
        payload: {
            operation: 'danger_resolve',
            danger_resolution: {
                danger_id: dangerId || null,
                agent_id: targetAgentId,
                rescuer_id: agentId(agent),
                recovery_status: status,
            },
        },
        deadlineMs: DEFAULT_DEADLINE_MS,
        agentId: agentId(agent),
        traceId,
        costContext: {
            agent_tier: 'conversation',
            budget_bucket: 'distress-rescue',
            estimated_cost_usd: 0.0,
        },
    });
    return detail;
}

export const rescueAction = {
    name: '!rescue',
    description:
        'Assist a stuck, drowning, trapped, low-health, or repeatedly blocked agent and report the recovery.',
    params: {
        target_agent_id: {
            type: 'string',
            description: 'Agent id to assist.',
        },
        danger_id: {
            type: 'string',
            description: 'Optional shared-state danger id.',
        },
    },
    perform: async function (agent, targetAgentId, dangerId = null) {
        const traceId = `trace-rescue-${randomUUID()}`;
        const rescueId = `rescue-${dangerId || randomUUID()}`;
        emit(agent, 'rescue.action.started', traceId, {
            rescue_id: rescueId,
            target_agent_id: targetAgentId,
            rescuer_id: agentId(agent),
            danger_id: dangerId || null,
            mode: rescueMode(),
        });

        let attempt = await navigateNear(agent, targetAgentId);
        let recoveryStatus = attempt.ok ? 'escaped' : 'failed';
        if (!attempt.ok && rescueMode() === 'easy') {
            attempt = await easyTeleport(agent, targetAgentId);
            recoveryStatus = attempt.ok ? 'teleported' : 'failed';
        }

        emit(agent, 'rescue.action.completed', traceId, {
            rescue_id: rescueId,
            target_agent_id: targetAgentId,
            rescuer_id: agentId(agent),
            danger_id: dangerId || null,
            mode: rescueMode(),
            recovery_status: recoveryStatus,
            status: attempt.ok ? 'success' : 'failure',
            detail: attempt.detail,
        });

        if (attempt.ok) {
            await reportResolution(
                agent,
                traceId,
                targetAgentId,
                recoveryStatus,
                attempt.detail,
                dangerId,
            );
        }
        return `rescue ${targetAgentId}: ${attempt.ok ? 'success' : 'failure'}: ${attempt.detail}`;
    },
};

export default rescueAction;

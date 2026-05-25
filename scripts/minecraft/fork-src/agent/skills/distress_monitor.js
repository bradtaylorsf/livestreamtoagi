// Health/oxygen distress reporter for embodied Minecraft agents.

import { randomUUID } from 'node:crypto';

import { callBridge } from '../bridge/python_bridge.js';
import { emitTimelineEvent } from '../bridge/timeline_emitter.js';

const PATCH_FLAG = Symbol.for('livestreamtoagi.distressMonitorInstalled');
const DEFAULT_POLL_MS = 1000;
const DEFAULT_DEADLINE_MS = 5000;

function agentId(agent) {
    const bot = agent && agent.bot ? agent.bot : null;
    return (
        (agent && (agent.name || agent.agent_id || agent.id)) ||
        (bot && bot.username) ||
        process.env.LTAG_AGENT_ID ||
        'agent'
    );
}

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function position(bot) {
    const pos = bot?.entity?.position;
    if (!pos) return null;
    return { x: Math.floor(pos.x), y: Math.floor(pos.y), z: Math.floor(pos.z) };
}

function intEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function emit(agent, type, traceId, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentId(agent),
        traceId,
        payload,
    });
}

function distressKind(bot) {
    const health = Number(bot?.health);
    const oxygen = Number(bot?.oxygenLevel ?? bot?.oxygen);
    const inWater = Boolean(
        bot?.entity?.isInWater ||
            bot?.entity?.isInWaterRain ||
            bot?.entity?.isInWaterOrRain ||
            bot?.isInWater,
    );
    if (Number.isFinite(health) && health <= 0) return { kind: 'death', severity: 5 };
    if (inWater && Number.isFinite(oxygen) && oxygen <= 3) return { kind: 'drowning', severity: 5 };
    if (Number.isFinite(health) && health < 6) return { kind: 'low_health', severity: 4 };
    return null;
}

async function reportDistress(agent, bot, distress, traceId) {
    const payload = {
        operation: 'danger_report',
        danger: {
            agent_id: agentId(agent),
            kind: distress.kind,
            location: position(bot),
            severity: distress.severity,
            details: `health=${bot?.health ?? 'unknown'} oxygen=${bot?.oxygenLevel ?? bot?.oxygen ?? 'unknown'}`,
        },
    };
    await callBridge({
        service: 'shared_state',
        method: 'write',
        payload,
        deadlineMs: DEFAULT_DEADLINE_MS,
        agentId: agentId(agent),
        traceId,
        costContext: {
            agent_tier: 'conversation',
            budget_bucket: 'distress-monitor',
            estimated_cost_usd: 0.0,
        },
    });
    emit(agent, 'distress.reported', traceId, {
        agent_id: agentId(agent),
        kind: distress.kind,
        severity: distress.severity,
        location: payload.danger.location,
    });
}

export function installDistressMonitor(agent, options = {}) {
    if (!agent || agent[PATCH_FLAG]) return agent;
    const bot = getBot(agent);
    const pollMs = options.pollMs || intEnv('MINECRAFT_DISTRESS_POLL_MS', DEFAULT_POLL_MS);
    let lastKind = null;
    let lastReportedAt = 0;
    const minIntervalMs = options.minIntervalMs || intEnv('MINECRAFT_DISTRESS_MIN_INTERVAL_MS', 15000);

    const timer = setInterval(() => {
        const distress = distressKind(bot);
        if (!distress) {
            lastKind = null;
            return;
        }
        const now = Date.now();
        if (distress.kind === lastKind && now - lastReportedAt < minIntervalMs) return;
        lastKind = distress.kind;
        lastReportedAt = now;
        const traceId = `trace-distress-${randomUUID()}`;
        reportDistress(agent, bot, distress, traceId).catch((err) => {
            emit(agent, 'distress.report_failed', traceId, {
                agent_id: agentId(agent),
                kind: distress.kind,
                error: err && err.message ? err.message : String(err),
            });
        });
    }, pollMs);
    if (typeof timer.unref === 'function') timer.unref();

    Object.defineProperty(agent, PATCH_FLAG, {
        value: true,
        configurable: false,
        enumerable: false,
        writable: false,
    });
    agent.__ltagDistressMonitor = { timer };
    return agent;
}

export default installDistressMonitor;

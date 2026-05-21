// Per-agent build-plan governor for !planAndBuild.
//
// This keeps repeated build requests from turning into repeated builder-model
// calls. State is intentionally process-local because each staged Mindcraft bot
// runs as its own process during local soaks.

import { createHash, randomUUID } from 'node:crypto';

const DEFAULT_BUILD_MAX_PER_AGENT = 6;
const DEFAULT_BUILD_COOLDOWN_SEC = 300;
const DEFAULT_BUILD_ZONE_STRIDE = 12;
const DEFAULT_BUILD_CACHE_TTL_SEC = 3600;
const DEFAULT_ACTIVE_TIMEOUT_SEC = 600;
const ZONE_BUCKET_SIZE = 16;

const stateByAgent = new Map();

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || process.env.LTAG_AGENT_ID || 'agent';
}

function intEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function nowMs(options = {}) {
    return Number.isFinite(Number(options.nowMs)) ? Number(options.nowMs) : Date.now();
}

function normalizeDescription(description) {
    return String(description || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim()
        .replace(/\s+/g, ' ');
}

function stableValue(value) {
    if (Array.isArray(value)) return value.map((item) => stableValue(item));
    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([key, item]) => [key, stableValue(item)]),
        );
    }
    return value;
}

function hashText(value, length = 12) {
    return createHash('sha1').update(String(value)).digest('hex').slice(0, length);
}

function settingsHash(settings = {}) {
    return hashText(JSON.stringify(stableValue(settings)), 10);
}

function positionCell(origin) {
    const raw = origin && typeof origin === 'object' ? origin : {};
    return {
        x: Math.floor(Number(raw.x) || 0),
        y: Math.floor(Number(raw.y) || 64),
        z: Math.floor(Number(raw.z) || 0),
    };
}

function zoneBucket(origin) {
    const cell = positionCell(origin);
    return [
        Math.floor(cell.x / ZONE_BUCKET_SIZE),
        Math.floor(cell.y / ZONE_BUCKET_SIZE),
        Math.floor(cell.z / ZONE_BUCKET_SIZE),
    ].join(',');
}

export function applyBuildZoneOffset(agentKey, origin) {
    const stride = intEnv('MC_SIM_BUILD_ZONE_STRIDE', DEFAULT_BUILD_ZONE_STRIDE);
    const base = positionCell(origin);
    if (stride <= 0) return base;
    const slot = Number.parseInt(hashText(agentKey, 8), 16) % 25;
    const gridX = (slot % 5) - 2;
    const gridZ = Math.floor(slot / 5) - 2;
    return {
        x: base.x + gridX * stride,
        y: base.y,
        z: base.z + gridZ * stride,
    };
}

export function buildPlanCacheKey(agentKey, description, origin, settings = {}) {
    return [
        String(agentKey || 'agent').toLowerCase(),
        normalizeDescription(description),
        zoneBucket(origin),
        settingsHash(settings),
    ].join('|');
}

function stateFor(agentKey) {
    const key = String(agentKey || 'agent').toLowerCase();
    if (!stateByAgent.has(key)) {
        stateByAgent.set(key, {
            activeBuild: null,
            builderCallCount: 0,
            planCache: new Map(),
            lastCompletedAtByKey: new Map(),
            skipCounts: {
                active_build_exists: 0,
                cache_hit: 0,
                cooldown: 0,
                per_agent_cap: 0,
            },
        });
    }
    return stateByAgent.get(key);
}

function publicActiveBuild(activeBuild) {
    if (!activeBuild) return null;
    return {
        plan_id: activeBuild.planId,
        description: activeBuild.description,
        origin: activeBuild.origin,
        status: activeBuild.status,
        started_at_ms: activeBuild.startedAt,
        cache_key: activeBuild.cacheKey,
    };
}

function evictExpiredCache(state, now) {
    const ttlMs = intEnv('MC_SIM_BUILD_CACHE_TTL_SEC', DEFAULT_BUILD_CACHE_TTL_SEC) * 1000;
    if (ttlMs <= 0) return;
    for (const [key, entry] of state.planCache.entries()) {
        if (now - entry.createdAt > ttlMs) state.planCache.delete(key);
    }
}

function expireActiveBuild(state, now) {
    const active = state.activeBuild;
    if (!active) return null;
    const timeoutMs = DEFAULT_ACTIVE_TIMEOUT_SEC * 1000;
    if (now - active.startedAt < timeoutMs) return null;
    state.activeBuild = null;
    return { ...active, status: 'timed_out', timedOut: true };
}

function skipResult({
    agentKey,
    state,
    reason,
    cacheKey,
    origin,
    activeBuild = null,
    cooldownRemainingSec = 0,
    cacheHit = false,
}) {
    state.skipCounts[reason] = (state.skipCounts[reason] || 0) + 1;
    return {
        allowed: false,
        reason,
        agent_id: agentKey,
        active_build_owner: agentKey,
        active_build: publicActiveBuild(activeBuild),
        cache_key: cacheKey,
        origin,
        cache_hit: cacheHit,
        cooldown_remaining_sec: cooldownRemainingSec,
        builder_call_count: state.builderCallCount,
        max_builder_calls_per_agent: intEnv(
            'MC_SIM_BUILD_MAX_PER_AGENT',
            DEFAULT_BUILD_MAX_PER_AGENT,
        ),
        skipped_repeat_count: state.skipCounts[reason],
    };
}

export function tryAcquireBuild(agent, description, origin, settings = {}, options = {}) {
    const agentKey = agentId(agent).toLowerCase();
    const state = stateFor(agentKey);
    const now = nowMs(options);
    evictExpiredCache(state, now);
    expireActiveBuild(state, now);

    const buildOrigin = applyBuildZoneOffset(agentKey, origin);
    const cacheKey = buildPlanCacheKey(agentKey, description, buildOrigin, settings);
    if (state.activeBuild) {
        return skipResult({
            agentKey,
            state,
            reason: 'active_build_exists',
            cacheKey,
            origin: buildOrigin,
            activeBuild: state.activeBuild,
            cacheHit: state.planCache.has(cacheKey),
        });
    }

    const cooldownSec = intEnv('MC_SIM_BUILD_COOLDOWN_SEC', DEFAULT_BUILD_COOLDOWN_SEC);
    const completedAt = state.lastCompletedAtByKey.get(cacheKey);
    const elapsedSec = completedAt ? Math.floor((now - completedAt) / 1000) : null;
    const cooldownRemainingSec =
        elapsedSec !== null && elapsedSec < cooldownSec ? cooldownSec - elapsedSec : 0;
    if (cooldownRemainingSec > 0) {
        return skipResult({
            agentKey,
            state,
            reason: 'cooldown',
            cacheKey,
            origin: buildOrigin,
            cooldownRemainingSec,
            cacheHit: state.planCache.has(cacheKey),
        });
    }

    const cached = state.planCache.get(cacheKey) || null;
    const maxPerAgent = intEnv('MC_SIM_BUILD_MAX_PER_AGENT', DEFAULT_BUILD_MAX_PER_AGENT);
    if (!cached && state.builderCallCount >= maxPerAgent) {
        return skipResult({
            agentKey,
            state,
            reason: 'per_agent_cap',
            cacheKey,
            origin: buildOrigin,
        });
    }

    const planId = cached ? cached.planId : `plan-${hashText(cacheKey, 8)}-${randomUUID()}`;
    state.activeBuild = {
        planId,
        description,
        origin: buildOrigin,
        cacheKey,
        startedAt: now,
        status: cached ? 'cache_hit' : 'planning',
    };
    if (cached) state.skipCounts.cache_hit += 1;
    return {
        allowed: true,
        reason: cached ? 'cache_hit' : 'cache_miss',
        agent_id: agentKey,
        active_build_owner: agentKey,
        active_build: publicActiveBuild(state.activeBuild),
        plan_id: planId,
        cache_key: cacheKey,
        origin: buildOrigin,
        cache_hit: Boolean(cached),
        cached_plan: cached ? cached.plan : null,
        cooldown_remaining_sec: 0,
        builder_call_count: state.builderCallCount,
        max_builder_calls_per_agent: maxPerAgent,
        skipped_repeat_count: cached ? state.skipCounts.cache_hit : 0,
    };
}

export function recordBuilderCallStarted(agent, acquisition) {
    const agentKey = acquisition?.agent_id || agentId(agent).toLowerCase();
    const state = stateFor(agentKey);
    state.builderCallCount += 1;
    if (state.activeBuild && state.activeBuild.planId === acquisition?.plan_id) {
        state.activeBuild.status = 'generating';
    }
    return {
        builder_call_count: state.builderCallCount,
        max_builder_calls_per_agent: intEnv(
            'MC_SIM_BUILD_MAX_PER_AGENT',
            DEFAULT_BUILD_MAX_PER_AGENT,
        ),
    };
}

export function recordPlanGenerated(agent, acquisition, plan) {
    const agentKey = acquisition?.agent_id || agentId(agent).toLowerCase();
    const state = stateFor(agentKey);
    const now = Date.now();
    const planId = acquisition?.plan_id;
    if (!planId || !acquisition?.cache_key) return governorSnapshot(agent);
    state.planCache.set(acquisition.cache_key, {
        planId,
        plan,
        origin: acquisition.origin,
        createdAt: now,
    });
    if (state.activeBuild && state.activeBuild.planId === planId) {
        state.activeBuild.status = 'planned';
    }
    return governorSnapshot(agent);
}

function releaseBuild(agent, planId, status, result = '', options = {}) {
    const agentKey = agentId(agent).toLowerCase();
    const state = stateFor(agentKey);
    const now = nowMs(options);
    const active = state.activeBuild;
    if (active && (!planId || active.planId === planId)) {
        if (status === 'completed') {
            state.lastCompletedAtByKey.set(active.cacheKey, now);
        }
        state.activeBuild = null;
        return {
            plan_id: active.planId,
            status,
            result,
            cooldown_remaining_sec:
                status === 'completed'
                    ? intEnv('MC_SIM_BUILD_COOLDOWN_SEC', DEFAULT_BUILD_COOLDOWN_SEC)
                    : 0,
            active_build: null,
        };
    }
    return {
        plan_id: planId || null,
        status,
        result,
        cooldown_remaining_sec: 0,
        active_build: publicActiveBuild(state.activeBuild),
    };
}

export function recordBuildCompleted(agent, planId, result = '', options = {}) {
    return releaseBuild(agent, planId, 'completed', result, options);
}

export function recordBuildFailed(agent, planId, result = '', options = {}) {
    return releaseBuild(agent, planId, 'failed', result, options);
}

export function governorSnapshot(agent) {
    const agentKey = agentId(agent).toLowerCase();
    const state = stateFor(agentKey);
    return {
        agent_id: agentKey,
        active_build: publicActiveBuild(state.activeBuild),
        builder_call_count: state.builderCallCount,
        max_builder_calls_per_agent: intEnv(
            'MC_SIM_BUILD_MAX_PER_AGENT',
            DEFAULT_BUILD_MAX_PER_AGENT,
        ),
        cache_size: state.planCache.size,
        skipped_active_build: state.skipCounts.active_build_exists,
        skipped_cooldown: state.skipCounts.cooldown,
        skipped_per_agent_cap: state.skipCounts.per_agent_cap,
        cache_hits: state.skipCounts.cache_hit,
    };
}

export function resetBuildPlanGovernor() {
    stateByAgent.clear();
}


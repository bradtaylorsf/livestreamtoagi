// Per-agent and per-scene build-plan governor for !planAndBuild.
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
const stateByScene = new Map();
const RETRYABLE_FAILURE_REASONS = new Set([
    'bridge_down',
    'bridge_unavailable',
    'materials_missing',
    'provider_failed',
    'temporary_blocked',
    'timed_out',
    'timeout',
    'tool_missing',
]);

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    if (typeof agent === 'string') return agent;
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || process.env.LTAG_AGENT_ID || 'agent';
}

function agentKeyFor(agent) {
    return String(agentId(agent) || 'agent').toLowerCase();
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

function normalizeSceneId(sceneId) {
    const text = String(sceneId || '').trim();
    return text || null;
}

function sceneFor(sceneId) {
    const key = normalizeSceneId(sceneId);
    if (!key) return null;
    if (!stateByScene.has(key)) {
        stateByScene.set(key, {
            activeBuild: null,
            planCache: new Map(),
            lastCompletedAtByKey: new Map(),
            skipCounts: {
                scene_locked: 0,
                cache_hit: 0,
                cooldown: 0,
            },
        });
    }
    return stateByScene.get(key);
}

function publicActiveBuild(activeBuild) {
    if (!activeBuild) return null;
    return {
        plan_id: activeBuild.planId,
        scene_id: activeBuild.sceneId || null,
        description: activeBuild.description,
        origin: activeBuild.origin,
        status: activeBuild.status,
        started_at_ms: activeBuild.startedAt,
        cache_key: activeBuild.cacheKey,
        owner: activeBuild.owner || activeBuild.agentKey || null,
        objective_id: activeBuild.objectiveId || null,
        phase_index: Number.isInteger(activeBuild.phaseIndex) ? activeBuild.phaseIndex : null,
        phase_owner: activeBuild.phaseOwner || activeBuild.owner || activeBuild.agentKey || null,
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

function expireSceneBuild(sceneState, now) {
    const active = sceneState.activeBuild;
    if (!active) return null;
    if (active.cooldownUntil && now >= active.cooldownUntil) {
        sceneState.activeBuild = null;
        return { ...active, status: 'cooldown_expired' };
    }
    if (active.status === 'failed' && active.cooldownUntil) return null;
    const timeoutMs = DEFAULT_ACTIVE_TIMEOUT_SEC * 1000;
    if (now - active.startedAt < timeoutMs) return null;
    sceneState.activeBuild = null;
    return { ...active, status: 'timed_out', timedOut: true };
}

function skipResult({
    agentKey,
    state,
    reason,
    cacheKey,
    origin,
    activeBuild = null,
    activeBuildOwner = agentKey,
    sceneId = null,
    planId = null,
    cooldownRemainingSec = 0,
    cacheHit = false,
    objectiveId = null,
    phaseIndex = null,
    phaseOwner = null,
}) {
    state.skipCounts[reason] = (state.skipCounts[reason] || 0) + 1;
    return {
        allowed: false,
        reason,
        scene_id: sceneId,
        plan_id: planId || activeBuild?.planId || null,
        agent_id: agentKey,
        active_build_owner: activeBuildOwner,
        active_build: publicActiveBuild(activeBuild),
        cache_key: cacheKey,
        origin,
        cache_hit: cacheHit,
        objective_id: objectiveId,
        phase_index: Number.isInteger(phaseIndex) ? phaseIndex : null,
        phase_owner: phaseOwner,
        cooldown_remaining_sec: cooldownRemainingSec,
        builder_call_count: state.builderCallCount,
        max_builder_calls_per_agent: intEnv(
            'MC_SIM_BUILD_MAX_PER_AGENT',
            DEFAULT_BUILD_MAX_PER_AGENT,
        ),
        skipped_repeat_count: state.skipCounts[reason],
    };
}

function tryAcquireAgentBuild(agentKey, description, origin, settings = {}, options = {}) {
    const state = stateFor(agentKey);
    const now = nowMs(options);
    evictExpiredCache(state, now);
    expireActiveBuild(state, now);

    const buildOrigin = options.buildOrigin || applyBuildZoneOffset(agentKey, origin);
    const cacheKey = options.cacheKey || buildPlanCacheKey(agentKey, description, buildOrigin, settings);
    if (state.activeBuild) {
        return skipResult({
            agentKey,
            state,
            reason: 'active_build_exists',
            cacheKey,
            origin: buildOrigin,
            activeBuild: state.activeBuild,
            activeBuildOwner: state.activeBuild.owner || state.activeBuild.agentKey || agentKey,
            sceneId: options.sceneId || state.activeBuild.sceneId || null,
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

    const cached = options.cachedPlanEntry || state.planCache.get(cacheKey) || null;
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

    const planId = cached
        ? cached.planId
        : options.planId || `plan-${hashText(cacheKey, 8)}-${randomUUID()}`;
    state.activeBuild = {
        planId,
        description,
        origin: buildOrigin,
        cacheKey,
        startedAt: now,
        sceneId: options.sceneId || null,
        owner: options.ownerAgentId || agentKey,
        agentKey,
        status: cached ? 'cache_hit' : 'planning',
        objectiveId: options.objectiveId || null,
        phaseIndex: Number.isInteger(options.phaseIndex) ? options.phaseIndex : null,
        phaseOwner: options.phaseOwner || options.ownerAgentId || agentKey,
    };
    if (cached) state.skipCounts.cache_hit += 1;
    return {
        allowed: true,
        reason: cached ? 'cache_hit' : 'cache_miss',
        scene_id: options.sceneId || null,
        agent_id: agentKey,
        active_build_owner: options.ownerAgentId || agentKey,
        active_build: publicActiveBuild(state.activeBuild),
        plan_id: planId,
        cache_key: cacheKey,
        origin: buildOrigin,
        cache_hit: Boolean(cached),
        cached_plan: cached ? cached.plan : null,
        objective_id: options.objectiveId || null,
        phase_index: Number.isInteger(options.phaseIndex) ? options.phaseIndex : null,
        phase_owner: options.phaseOwner || options.ownerAgentId || agentKey,
        cooldown_remaining_sec: 0,
        builder_call_count: state.builderCallCount,
        max_builder_calls_per_agent: maxPerAgent,
        skipped_repeat_count: cached ? state.skipCounts.cache_hit : 0,
    };
}

export function tryAcquireBuild(agent, description, origin, settings = {}, options = {}) {
    return tryAcquireAgentBuild(agentKeyFor(agent), description, origin, settings, options);
}

export function tryAcquireSceneBuild(
    sceneId,
    agent,
    description,
    origin,
    settings = {},
    options = {},
) {
    const normalizedSceneId = normalizeSceneId(sceneId);
    if (!normalizedSceneId) return tryAcquireBuild(agent, description, origin, settings, options);

    const agentKey = agentKeyFor(agent);
    const ownerAgentId = options.ownerAgentId ? String(options.ownerAgentId).toLowerCase() : agentKey;
    const phaseOwner = options.phaseOwner ? String(options.phaseOwner).toLowerCase() : ownerAgentId;
    const now = nowMs(options);
    const buildOrigin = applyBuildZoneOffset(agentKey, origin);
    const cacheKey = buildPlanCacheKey(agentKey, description, buildOrigin, settings);
    const sceneState = sceneFor(normalizedSceneId);
    expireSceneBuild(sceneState, now);
    const cachedScenePlan = sceneState.planCache.get(cacheKey) || null;

    if (phaseOwner !== agentKey) {
        return skipResult({
            agentKey,
            state: stateFor(agentKey),
            reason: options.objectiveId ? 'not_phase_owner' : 'scene_locked',
            cacheKey,
            origin: buildOrigin,
            activeBuild: sceneState.activeBuild || {
                planId: options.planId || null,
                sceneId: normalizedSceneId,
                description,
                origin: buildOrigin,
                cacheKey,
                startedAt: now,
                status: 'director_owned',
                owner: phaseOwner,
                agentKey: phaseOwner,
                objectiveId: options.objectiveId || null,
                phaseIndex: Number.isInteger(options.phaseIndex) ? options.phaseIndex : null,
                phaseOwner,
            },
            activeBuildOwner: phaseOwner,
            sceneId: normalizedSceneId,
            planId: options.planId || sceneState.activeBuild?.planId || null,
            cacheHit: Boolean(cachedScenePlan),
            objectiveId: options.objectiveId || null,
            phaseIndex: options.phaseIndex,
            phaseOwner,
        });
    }

    if (sceneState.activeBuild) {
        const activeOwner = sceneState.activeBuild.owner || sceneState.activeBuild.agentKey || ownerAgentId;
        return skipResult({
            agentKey,
            state: stateFor(agentKey),
            reason: activeOwner === agentKey ? 'active_build_exists' : 'scene_locked',
            cacheKey,
            origin: buildOrigin,
            activeBuild: sceneState.activeBuild,
            activeBuildOwner: activeOwner,
            sceneId: normalizedSceneId,
            planId: sceneState.activeBuild.planId,
            cacheHit: Boolean(cachedScenePlan),
            objectiveId: sceneState.activeBuild.objectiveId || options.objectiveId || null,
            phaseIndex: sceneState.activeBuild.phaseIndex ?? options.phaseIndex ?? null,
            phaseOwner: sceneState.activeBuild.phaseOwner || activeOwner,
        });
    }

    const cooldownSec = intEnv('MC_SIM_BUILD_COOLDOWN_SEC', DEFAULT_BUILD_COOLDOWN_SEC);
    const completedAt = sceneState.lastCompletedAtByKey.get(cacheKey);
    const elapsedSec = completedAt ? Math.floor((now - completedAt) / 1000) : null;
    const cooldownRemainingSec =
        elapsedSec !== null && elapsedSec < cooldownSec ? cooldownSec - elapsedSec : 0;
    if (cooldownRemainingSec > 0) {
        sceneState.skipCounts.cooldown += 1;
        return skipResult({
            agentKey,
            state: stateFor(agentKey),
            reason: 'cooldown',
            cacheKey,
            origin: buildOrigin,
            sceneId: normalizedSceneId,
            cooldownRemainingSec,
            cacheHit: Boolean(cachedScenePlan),
            objectiveId: options.objectiveId || null,
            phaseIndex: options.phaseIndex,
            phaseOwner,
        });
    }

    const acquisition = tryAcquireAgentBuild(agentKey, description, origin, settings, {
        ...options,
        buildOrigin,
        cacheKey,
        cachedPlanEntry: cachedScenePlan,
        sceneId: normalizedSceneId,
        ownerAgentId: phaseOwner,
        phaseOwner,
    });
    if (!acquisition.allowed) return acquisition;

    sceneState.activeBuild = {
        planId: acquisition.plan_id,
        description,
        origin: acquisition.origin,
        cacheKey: acquisition.cache_key,
        startedAt: now,
        sceneId: normalizedSceneId,
        owner: phaseOwner,
        agentKey,
        status: acquisition.cache_hit ? 'cache_hit' : 'planning',
        objectiveId: options.objectiveId || null,
        phaseIndex: Number.isInteger(options.phaseIndex) ? options.phaseIndex : null,
        phaseOwner,
    };
    if (acquisition.cache_hit) sceneState.skipCounts.cache_hit += 1;
    return {
        ...acquisition,
        scene_id: normalizedSceneId,
        active_build_owner: phaseOwner,
        active_build: publicActiveBuild(sceneState.activeBuild),
        objective_id: options.objectiveId || null,
        phase_index: Number.isInteger(options.phaseIndex) ? options.phaseIndex : null,
        phase_owner: phaseOwner,
    };
}

export function recordBuilderCallStarted(agent, acquisition) {
    const agentKey = acquisition?.agent_id || agentKeyFor(agent);
    const state = stateFor(agentKey);
    state.builderCallCount += 1;
    if (state.activeBuild && state.activeBuild.planId === acquisition?.plan_id) {
        state.activeBuild.status = 'generating';
    }
    if (acquisition?.scene_id) {
        const sceneState = sceneFor(acquisition.scene_id);
        if (sceneState?.activeBuild && sceneState.activeBuild.planId === acquisition?.plan_id) {
            sceneState.activeBuild.status = 'generating';
        }
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
    const agentKey = acquisition?.agent_id || agentKeyFor(agent);
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
    if (acquisition?.scene_id) {
        const sceneState = sceneFor(acquisition.scene_id);
        sceneState.planCache.set(acquisition.cache_key, {
            planId,
            plan,
            origin: acquisition.origin,
            createdAt: now,
            owner: acquisition.active_build_owner || agentKey,
        });
        if (sceneState.activeBuild && sceneState.activeBuild.planId === planId) {
            sceneState.activeBuild.status = 'planned';
        }
    }
    return governorSnapshot(agent);
}

function releaseBuild(agent, planId, status, result = '', options = {}) {
    const agentKey = agentKeyFor(agent);
    const state = stateFor(agentKey);
    const now = nowMs(options);
    const active = state.activeBuild;
    if (active && (!planId || active.planId === planId)) {
        if (status === 'completed') {
            state.lastCompletedAtByKey.set(active.cacheKey, now);
        } else if (status === 'failed') {
            state.planCache.delete(active.cacheKey);
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

function retryableReasonFrom(result = '', options = {}) {
    if (options.retryable === true) return { retryable: true, reason: options.reason || 'retryable' };
    if (options.retryable === false) return { retryable: false, reason: options.reason || 'failed' };
    const raw = String(options.reason || result || '').toLowerCase().replace(/-/g, '_');
    for (const reason of RETRYABLE_FAILURE_REASONS) {
        if (raw.includes(reason)) return { retryable: true, reason };
    }
    return { retryable: false, reason: raw.includes('protected') ? 'protected' : 'failed' };
}

function releaseSceneBuild(agent, planId, status, result = '', options = {}) {
    const agentKey = agentKeyFor(agent);
    const now = nowMs(options);
    for (const [sceneId, sceneState] of stateByScene.entries()) {
        const active = sceneState.activeBuild;
        if (!active || (planId && active.planId !== planId)) continue;
        if (status === 'completed') {
            sceneState.lastCompletedAtByKey.set(active.cacheKey, now);
            sceneState.activeBuild = null;
            return {
                scene_id: sceneId,
                plan_id: active.planId,
                status,
                result,
                cooldown_remaining_sec: intEnv(
                    'MC_SIM_BUILD_COOLDOWN_SEC',
                    DEFAULT_BUILD_COOLDOWN_SEC,
                ),
                active_build: null,
            };
        }
        if (status === 'failed') {
            const failure = retryableReasonFrom(result, options);
            sceneState.planCache.delete(active.cacheKey);
            if (failure.retryable) {
                sceneState.activeBuild = null;
                return {
                    scene_id: sceneId,
                    plan_id: active.planId,
                    status,
                    result,
                    reason: failure.reason,
                    retryable: true,
                    cooldown_remaining_sec: 0,
                    active_build: null,
                };
            }
            active.status = 'failed';
            active.result = result;
            active.failedAt = now;
            active.cooldownUntil =
                now + intEnv('MC_SIM_BUILD_COOLDOWN_SEC', DEFAULT_BUILD_COOLDOWN_SEC) * 1000;
            return {
                scene_id: sceneId,
                plan_id: active.planId,
                status,
                result,
                reason: failure.reason,
                retryable: false,
                cooldown_remaining_sec: intEnv(
                    'MC_SIM_BUILD_COOLDOWN_SEC',
                    DEFAULT_BUILD_COOLDOWN_SEC,
                ),
                active_build: publicActiveBuild(active),
            };
        }
        if (active.agentKey === agentKey || active.owner === agentKey || !planId) {
            sceneState.activeBuild = null;
        }
    }
    return {
        scene_id: options.sceneId || null,
        plan_id: planId || null,
        status,
        result,
        cooldown_remaining_sec: 0,
        active_build: null,
    };
}

export function recordBuildCompleted(agent, planId, result = '', options = {}) {
    const agentState = releaseBuild(agent, planId, 'completed', result, options);
    const sceneState = releaseSceneBuild(agent, planId, 'completed', result, options);
    return { ...agentState, ...sceneState, active_build: sceneState.active_build };
}

export function recordBuildFailed(agent, planId, result = '', options = {}) {
    const agentState = releaseBuild(agent, planId, 'failed', result, options);
    const sceneState = releaseSceneBuild(agent, planId, 'failed', result, options);
    return { ...agentState, ...sceneState, active_build: sceneState.active_build };
}

export function governorSnapshot(agent) {
    const agentKey = agentKeyFor(agent);
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
        scenes_tracked: stateByScene.size,
    };
}

export function resetBuildPlanGovernor() {
    stateByAgent.clear();
    stateByScene.clear();
}

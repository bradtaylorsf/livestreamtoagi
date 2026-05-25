// Builder-model plan generation plus bounded buildFromPlan execution.

import { randomUUID } from 'node:crypto';

import { callBridge } from '../bridge/python_bridge.js';
import { emitTimelineEvent } from '../bridge/timeline_emitter.js';
import {
    BuilderBudgetError,
    BuilderProviderError,
    builderProviderSnapshot,
    resolveBuilderModel,
} from '../skills/builder_provider.js';
import {
    governorSnapshot,
    recordBuildCompleted,
    recordBuildFailed,
    recordBuilderCallStarted,
    recordPlanGenerated,
    tryAcquireBuild,
    tryAcquireSceneBuild,
} from '../skills/build_plan_governor.js';
import { normalizePlan } from '../skills/build_plan.js';
import { normalizeBlockType, positionFrom } from '../skills/building.js';
import { performBuildFromPlan } from './build_from_plan_action.js';

const DEFAULT_MAX_STEPS = 64;
const DEFAULT_TIMEOUT_MS = 60000;
const MAX_RADIUS = 6;
const MAX_HEIGHT = 5;
const MIN_CABIN_BLOCKS = 32;
const DEFAULT_MODEL_MAX_STEPS = 32;
const ALLOWED_MATERIALS = new Set([
    'oak_log',
    'oak_planks',
    'cobblestone',
    'dirt',
    'glass',
    'torch',
    'chest',
    'crafting_table',
    'stone',
    'stone_bricks',
]);

function getBot(agent) {
    return agent && agent.bot ? agent.bot : agent;
}

function agentId(agent) {
    const bot = getBot(agent);
    return (agent && agent.name) || (bot && bot.username) || 'bridge-bot';
}

function planBuildAllowedAgents() {
    const raw = String(
        process.env.MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST || process.env.SOAK_PLAN_BUILD_BOTS || '',
    ).trim();
    if (!raw || ['*', 'all', 'any'].includes(raw.toLowerCase())) return null;
    return new Set(
        raw
            .split(/[\s,]+/)
            .map((item) => item.trim().toLowerCase())
            .filter(Boolean),
    );
}

function planBuildAllowedForAgent(agent) {
    const allowed = planBuildAllowedAgents();
    if (!allowed) return true;
    return allowed.has(String(agentId(agent) || '').trim().toLowerCase());
}

function emit(agent, type, traceId, payload = {}) {
    emitTimelineEvent({
        type,
        agent: agentId(agent),
        traceId,
        payload,
    });
}

function originFromAgent(agent) {
    const bot = getBot(agent);
    const position = bot && bot.entity && bot.entity.position;
    const cell = positionFrom(position);
    if (cell) {
        return { x: Math.floor(cell.x), y: Math.floor(cell.y), z: Math.floor(cell.z) };
    }
    return { x: 0, y: 64, z: 0 };
}

function directorBuildContext(agent) {
    const verdict = agent?.__ltagDirectorContext || {};
    const macro = verdict && typeof verdict.build_macro === 'object' ? verdict.build_macro || {} : {};
    return {
        sceneId: macro.scene_id || verdict.scene_id || null,
        planId: macro.plan_id || null,
        owner: macro.owner || null,
        role: macro.role || null,
        supportTask: macro.support_task || null,
        objectiveId: macro.objective_id || null,
        phaseIndex: Number.isInteger(macro.phase_index) ? macro.phase_index : null,
        phaseOwner: macro.phase_owner || macro.owner || null,
    };
}

function commonBuildPayload(acquisition, context = {}) {
    const sceneId = acquisition?.scene_id || context.sceneId || null;
    const owner = acquisition?.active_build_owner || context.owner || null;
    return {
        scene_id: sceneId,
        owner,
        build_plan_owner: owner,
        director_role: context.role || null,
        director_support_task: context.supportTask || null,
        objective_id: context.objectiveId || acquisition?.objective_id || null,
        phase_index:
            Number.isInteger(context.phaseIndex) ? context.phaseIndex : acquisition?.phase_index ?? null,
        phase_owner: context.phaseOwner || acquisition?.phase_owner || owner,
    };
}

async function writeSettlementObjective(agent, operation, context, traceId, fields = {}) {
    if (process.env.MC_SIM_BUILD_MODE !== 'settlement' || !context.objectiveId) return;
    const owner =
        fields.owner ||
        context.phaseOwner ||
        context.owner ||
        (agentId(agent) ? String(agentId(agent)).toLowerCase() : null);
    const objective = {
        objective_id: context.objectiveId,
        phase_index: Number.isInteger(context.phaseIndex) ? context.phaseIndex : 0,
        description: fields.description || context.description || 'settlement objective',
        owner_agent_id: owner,
        status: fields.status || 'in_progress',
        plan_id: fields.planId || context.planId || null,
        intended_blocks: Number.isFinite(fields.intendedBlocks) ? fields.intendedBlocks : 0,
        verified_blocks: Number.isFinite(fields.verifiedBlocks) ? fields.verifiedBlocks : 0,
        completion_ratio: Number.isFinite(fields.completionRatio) ? fields.completionRatio : 0,
        reassign_reason: fields.reason || null,
        previous_owner_agent_ids: [],
        owner_started_at_ms: fields.ownerStartedAtMs || null,
        evidence: fields.evidence || {},
    };
    try {
        await callBridge({
            service: 'shared_state',
            method: 'write',
            payload: {
                operation,
                settlement_objective: objective,
            },
            deadlineMs: Number.parseInt(process.env.MC_SIM_SHARED_STATE_DEADLINE_MS || '1000', 10),
            agentId: agentId(agent),
            traceId,
            costContext: {
                agent_tier: 'conversation',
                budget_bucket: 'shared-state',
                estimated_cost_usd: 0.0,
            },
        });
        emit(agent, 'settlement_objective.updated', traceId, {
            operation,
            objective_id: objective.objective_id,
            phase_index: objective.phase_index,
            owner_agent_id: objective.owner_agent_id,
            status: objective.status,
            plan_id: objective.plan_id,
            verified_blocks: objective.verified_blocks,
            completion_ratio: objective.completion_ratio,
        });
    } catch (err) {
        emit(agent, 'settlement_objective.error', traceId, {
            operation,
            objective_id: objective.objective_id,
            error_code: err && err.code ? String(err.code) : 'shared_state_write_failed',
            error: err && err.message ? err.message : String(err),
        });
    }
}

function executionMetrics(result) {
    const text = String(result || '');
    const valueFor = (name) => {
        const match = text.match(new RegExp(`\\b${name}=([0-9]+(?:\\.[0-9]+)?)`, 'i'));
        if (!match) return null;
        const parsed = Number(match[1]);
        return Number.isFinite(parsed) ? parsed : null;
    };
    return {
        intended_blocks: valueFor('intended'),
        blocks_present: valueFor('present'),
        blocks_missing: valueFor('missing'),
        blocks_unexpected: valueFor('unexpected'),
        verified_blocks: valueFor('verified'),
        steps_abandoned: valueFor('abandoned'),
        completion_ratio: valueFor('completion'),
    };
}

function isFalseLike(value) {
    return ['0', 'false', 'no', 'off', 'disabled'].includes(String(value).trim().toLowerCase());
}

function sharedStateEnabledByEnv() {
    return !isFalseLike(process.env.MC_SIM_SHARED_STATE_ENABLED || '1');
}

async function readActiveSettlementObjective(agent, traceId) {
    if (process.env.MC_SIM_BUILD_MODE !== 'settlement' || !sharedStateEnabledByEnv()) {
        return null;
    }
    try {
        const response = await callBridge({
            service: 'shared_state',
            method: 'read',
            payload: {},
            deadlineMs: Number.parseInt(process.env.MC_SIM_SHARED_STATE_DEADLINE_MS || '1000', 10),
            agentId: agentId(agent),
            traceId,
            costContext: {
                agent_tier: 'conversation',
                budget_bucket: 'shared-state',
                estimated_cost_usd: 0.0,
            },
        });
        const active = response?.payload?.active_objective;
        return active && typeof active === 'object' ? active : null;
    } catch (err) {
        emit(agent, 'settlement_objective.error', traceId, {
            operation: 'settlement_objective_read',
            error_code: err && err.code ? String(err.code) : 'shared_state_read_failed',
            error: err && err.message ? err.message : String(err),
        });
        return null;
    }
}

function normalizedId(value) {
    return String(value || '').trim().toLowerCase();
}

const REASSIGNABLE_SETTLEMENT_STATUSES = new Set([
    'blocked',
    'owner_cap_reached',
    'cooldown',
    'stale',
    'abandoned',
]);

function directorAuthorizedReassignment(activeObjective, context, agent) {
    const actor = normalizedId(agentId(agent));
    const directorOwner = normalizedId(context.phaseOwner || context.owner);
    if (!actor || directorOwner !== actor || context.role !== 'planner_owner') return false;
    const status = normalizedId(activeObjective.status);
    if (REASSIGNABLE_SETTLEMENT_STATUSES.has(status)) return true;
    const cooldownUntil = Number(activeObjective.cooldown_until_ms || 0);
    return Number.isFinite(cooldownUntil) && cooldownUntil > Date.now();
}

function staleSettlementReason(activeObjective, context, agent) {
    if (!activeObjective || typeof activeObjective !== 'object') return '';
    const activeObjectiveId = normalizedId(activeObjective.objective_id || activeObjective.id);
    const contextObjectiveId = normalizedId(context.objectiveId);
    if (activeObjectiveId && contextObjectiveId && activeObjectiveId !== contextObjectiveId) {
        return 'stale_settlement_objective';
    }
    const activeOwner = normalizedId(activeObjective.owner_agent_id);
    const actor = normalizedId(agentId(agent));
    if (activeOwner && actor && activeOwner !== actor) {
        if (directorAuthorizedReassignment(activeObjective, context, agent)) {
            return '';
        }
        return 'settlement_owner_mismatch';
    }
    if (
        activeObjectiveId &&
        contextObjectiveId &&
        activeObjectiveId === contextObjectiveId &&
        normalizedId(activeObjective.status) === 'completed'
    ) {
        return 'settlement_objective_completed';
    }
    return '';
}

function settlementStatusForSkippedAcquisition(reason) {
    if (reason === 'per_agent_cap') return 'owner_cap_reached';
    if (reason === 'cooldown') return 'cooldown';
    return null;
}

function localBuilderModel(agent) {
    const model = agent && agent.prompter && agent.prompter.code_model;
    return model && typeof model.sendRequest === 'function' ? model : null;
}

function localBuilderModelName(agent) {
    const model = localBuilderModel(agent);
    return (
        (model && (model.model_name || model.modelName || model.name || model.id)) ||
        'local/code_model'
    );
}

function hutBlueprint() {
    const blocks = [];
    for (let x = -1; x <= 1; x += 1) {
        for (let z = -1; z <= 1; z += 1) {
            blocks.push({ dx: x, dy: 0, dz: z, block_type: 'oak_planks' });
        }
    }
    for (let y = 1; y <= 2; y += 1) {
        for (const [dx, dz] of [
            [-1, -1],
            [0, -1],
            [1, -1],
            [-1, 0],
            [1, 0],
            [-1, 1],
            [0, 1],
            [1, 1],
        ]) {
            blocks.push({ dx, dy: y, dz, block_type: y === 2 ? 'oak_planks' : 'cobblestone' });
        }
    }
    blocks.push({ dx: 0, dy: 3, dz: 0, block_type: 'torch' });
    return { blocks };
}

function compactCabinBlueprint(maxSteps = DEFAULT_MAX_STEPS) {
    const limit = Math.max(1, Math.min(maxSteps, DEFAULT_MAX_STEPS));
    const blocks = [
        { dx: 1, dy: 0, dz: -2, block_type: 'oak_planks' },
        { dx: 2, dy: 0, dz: -2, block_type: 'oak_planks' },
        { dx: 1, dy: 0, dz: -1, block_type: 'oak_planks' },
        { dx: 2, dy: 0, dz: -1, block_type: 'oak_planks' },
        { dx: 1, dy: 1, dz: -2, block_type: 'oak_log' },
        { dx: 2, dy: 1, dz: -2, block_type: 'oak_log' },
        { dx: 1, dy: 1, dz: -1, block_type: 'oak_log' },
        { dx: 2, dy: 1, dz: -1, block_type: 'oak_log' },
        { dx: 1, dy: 2, dz: -2, block_type: 'oak_planks' },
        { dx: 2, dy: 2, dz: -2, block_type: 'oak_planks' },
        { dx: 1, dy: 2, dz: -1, block_type: 'oak_planks' },
        { dx: 2, dy: 2, dz: -1, block_type: 'oak_planks' },
    ];
    return { blocks: blocks.slice(0, limit) };
}

function isCabinRequest(description) {
    const text = String(description || '').toLowerCase();
    return text.includes('cabin') || text.includes('house') || text.includes('shelter');
}

function isWallRequest(description) {
    const text = String(description || '').toLowerCase();
    return text.includes('wall');
}

function cabinBlueprint(maxSteps = DEFAULT_MAX_STEPS) {
    if (maxSteps < MIN_CABIN_BLOCKS) return compactCabinBlueprint(maxSteps);
    const blocks = [];
    const corners = [
        [-1, -1],
        [1, -1],
        [-1, 1],
        [1, 1],
    ];

    for (const [dx, dz] of corners) {
        blocks.push({ dx, dy: 0, dz, block_type: 'oak_log' });
    }
    for (const [dx, dz] of [
        [0, -1],
        [-1, 0],
        [1, 0],
        [0, 1],
    ]) {
        blocks.push({ dx, dy: 0, dz, block_type: 'cobblestone' });
    }
    for (let y = 1; y <= 2; y += 1) {
        for (const [dx, dz] of corners) {
            blocks.push({ dx, dy: y, dz, block_type: 'oak_log' });
        }
        for (const [dx, dz] of [
            [-1, 0],
            [1, 0],
            [0, 1],
        ]) {
            blocks.push({ dx, dy: y, dz, block_type: 'oak_planks' });
        }
    }
    for (const [dx, dz] of [
        [-1, -1],
        [1, -1],
        [-1, 0],
        [1, 0],
        [-1, 1],
        [0, 1],
        [1, 1],
    ]) {
        blocks.push({ dx, dy: 3, dz, block_type: 'oak_planks' });
    }
    for (const [dx, dz] of [
        [-1, 0],
        [1, 0],
    ]) {
        blocks.push({ dx, dy: 4, dz, block_type: 'oak_planks' });
    }
    blocks.push({ dx: 0, dy: 1, dz: -1, block_type: 'torch' });
    return { blocks };
}

function starterBlueprint(description, maxSteps = DEFAULT_MAX_STEPS) {
    const text = String(description || '').toLowerCase();
    if (isCabinRequest(text)) {
        return cabinBlueprint(maxSteps);
    }
    if (text.includes('hut')) {
        return hutBlueprint();
    }
    if (text.includes('wall')) {
        return {
            blocks: [
                { dx: -2, dy: 0, dz: 0, block_type: 'cobblestone' },
                { dx: -1, dy: 0, dz: 0, block_type: 'cobblestone' },
                { dx: 0, dy: 0, dz: 0, block_type: 'cobblestone' },
                { dx: 1, dy: 0, dz: 0, block_type: 'cobblestone' },
                { dx: 2, dy: 0, dz: 0, block_type: 'cobblestone' },
                { dx: -2, dy: 1, dz: 0, block_type: 'torch' },
                { dx: 2, dy: 1, dz: 0, block_type: 'torch' },
            ],
        };
    }
    if (text.includes('storage') || text.includes('chest')) {
        return {
            blocks: [
                { dx: 0, dy: 0, dz: 0, block_type: 'oak_planks' },
                { dx: 1, dy: 0, dz: 0, block_type: 'chest' },
                { dx: -1, dy: 0, dz: 0, block_type: 'crafting_table' },
                { dx: 0, dy: 1, dz: 1, block_type: 'torch' },
            ],
        };
    }
    if (
        text.includes('workshop') ||
        text.includes('workbench') ||
        text.includes('work table') ||
        text.includes('crafting') ||
        text.includes('station')
    ) {
        return {
            blocks: [
                { dx: 1, dy: 0, dz: 1, block_type: 'oak_planks' },
                { dx: 2, dy: 0, dz: 1, block_type: 'oak_planks' },
                { dx: 1, dy: 0, dz: 2, block_type: 'crafting_table' },
                { dx: 2, dy: 0, dz: 2, block_type: 'oak_planks' },
                { dx: 2, dy: 1, dz: 2, block_type: 'torch' },
            ],
        };
    }
    if (text.includes('garden') || text.includes('farm')) {
        return {
            blocks: [
                { dx: -1, dy: 0, dz: -1, block_type: 'dirt' },
                { dx: 0, dy: 0, dz: -1, block_type: 'dirt' },
                { dx: 1, dy: 0, dz: -1, block_type: 'dirt' },
                { dx: -1, dy: 0, dz: 0, block_type: 'dirt' },
                { dx: 0, dy: 0, dz: 0, block_type: 'torch' },
                { dx: 1, dy: 0, dz: 0, block_type: 'dirt' },
            ],
        };
    }
    if (text.includes('marker') || text.includes('camp')) {
        return {
            blocks: [
                { dx: 0, dy: 0, dz: 0, block_type: 'oak_log' },
                { dx: 0, dy: 1, dz: 0, block_type: 'oak_log' },
                { dx: 0, dy: 2, dz: 0, block_type: 'torch' },
                { dx: 1, dy: 0, dz: 0, block_type: 'cobblestone' },
                { dx: -1, dy: 0, dz: 0, block_type: 'cobblestone' },
            ],
        };
    }
    return null;
}

function starterBlueprintOrNull(description, maxSteps = DEFAULT_MAX_STEPS) {
    return starterBlueprint(description, maxSteps);
}

function noStarterBlueprintMessage(description) {
    return `no starter blueprint matches non-cabin build request: ${String(description || '').slice(0, 80)}`;
}

function skippedPlanResult(agent, traceId, actionId, acquisition, buildPayload, description, origin, reason) {
    emit(agent, 'build_plan.generation.skipped', traceId, {
        action_id: actionId,
        plan_id: acquisition.plan_id || null,
        ...buildPayload,
        description,
        origin,
        reason,
        fallback_reason: reason,
        cache_key: acquisition.cache_key,
        cache_hit: Boolean(acquisition.cache_hit),
        active_build_owner: acquisition.active_build_owner,
        active_build: governorSnapshot(agent).active_build,
        builder_call_count: governorSnapshot(agent).builder_call_count,
        max_builder_calls_per_agent: acquisition.max_builder_calls_per_agent,
        skipped_repeat_count: acquisition.skipped_repeat_count || 0,
    });
    recordBuildFailed(agent, actionId, noStarterBlueprintMessage(description), { reason });
    return `plan-and-build skipped: ${reason}`;
}

function hasBuildablePlaceOrder(blocks) {
    const placed = new Set();
    for (const block of blocks) {
        const key = `${block.dx},${block.dy},${block.dz}`;
        if (block.dy > 0 && !placed.has(`${block.dx},${block.dy - 1},${block.dz}`)) {
            return false;
        }
        placed.add(key);
    }
    return true;
}

function orderBlocksForPlacement(blocks) {
    return [...blocks].sort((a, b) => {
        const dy = a.dy - b.dy;
        if (dy !== 0) return dy;
        const dz = a.dz - b.dz;
        if (dz !== 0) return dz;
        return a.dx - b.dx;
    });
}

function positiveIntEnv(name, fallback) {
    const raw = process.env[name];
    if (raw === undefined || raw === null || raw === '') return fallback;
    const parsed = Number.parseInt(raw, 10);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function plannerStepLimit(maxSteps) {
    return Math.max(1, Math.min(maxSteps, positiveIntEnv('MINECRAFT_PLAN_BUILD_MODEL_MAX_STEPS', DEFAULT_MODEL_MAX_STEPS)));
}

function assertPlanMatchesRequest(plan, description, maxSteps) {
    const blocks = Array.isArray(plan?.blocks) ? plan.blocks : [];
    const materials = new Set(blocks.map((block) => normalizeBlockType(block.block_type)));
    if (!hasBuildablePlaceOrder(blocks)) {
        throw new TypeError('build plan places unsupported upper blocks before foundations');
    }
    if (!isCabinRequest(description) && isWallRequest(description) && !materials.has('cobblestone')) {
        throw new TypeError('wall plan must use cobblestone from the easy starter kit');
    }
    if (!isCabinRequest(description)) return;
    const xs = new Set(blocks.map((block) => block.dx));
    const zs = new Set(blocks.map((block) => block.dz));
    if (xs.size < 2 || zs.size < 2) {
        throw new TypeError('cabin plan lacks a recognizable footprint');
    }
    if (maxSteps < MIN_CABIN_BLOCKS) {
        return;
    }
    if (blocks.length < MIN_CABIN_BLOCKS) {
        throw new TypeError(`cabin plan too small: expected at least ${MIN_CABIN_BLOCKS} blocks`);
    }
    for (const required of ['oak_log', 'oak_planks', 'cobblestone', 'torch']) {
        if (!materials.has(required)) throw new TypeError(`cabin plan missing ${required}`);
    }
    const maxDy = Math.max(...blocks.map((block) => block.dy));
    if (xs.size < 3 || zs.size < 3) {
        throw new TypeError('cabin plan lacks a recognizable footprint');
    }
    if (maxDy < 3) {
        throw new TypeError('cabin plan lacks a roof outline');
    }
}

function stripJsonFence(text) {
    const raw = String(text || '').trim();
    const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
    return fenced ? fenced[1].trim() : raw;
}

function extractJson(text) {
    const raw = stripJsonFence(text).replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    try {
        return JSON.parse(raw);
    } catch {
        const start = raw.indexOf('{');
        const end = raw.lastIndexOf('}');
        if (start >= 0 && end > start) return JSON.parse(raw.slice(start, end + 1));
        throw new Error('builder model did not return JSON');
    }
}

function assertBoundedDelta(item, label) {
    for (const axis of ['dx', 'dy', 'dz']) {
        if (!Number.isInteger(item[axis])) throw new TypeError(`${label}.${axis} must be an integer`);
    }
    if (Math.abs(item.dx) > MAX_RADIUS || Math.abs(item.dz) > MAX_RADIUS) {
        throw new TypeError(`${label} exceeds horizontal build bounds`);
    }
    if (item.dy < 0 || item.dy > MAX_HEIGHT) {
        throw new TypeError(`${label} exceeds vertical build bounds`);
    }
}

function validateGeneratedPlan(rawPlan, origin, maxSteps) {
    const plan = rawPlan && rawPlan.plan && !rawPlan.blocks ? rawPlan.plan : rawPlan;
    if (!plan || typeof plan !== 'object' || Array.isArray(plan)) {
        throw new TypeError('plan JSON must be an object');
    }
    if (!Array.isArray(plan.blocks)) throw new TypeError('plan.blocks must be an array');
    const clear = plan.clear === undefined ? [] : plan.clear;
    if (!Array.isArray(clear)) throw new TypeError('plan.clear must be an array when present');
    if (plan.blocks.length <= 0) throw new TypeError('plan.blocks must contain at least one block');
    if (plan.blocks.length + clear.length > maxSteps) {
        throw new TypeError(`plan exceeds max_steps ${maxSteps}`);
    }
    for (const [index, block] of plan.blocks.entries()) {
        assertBoundedDelta(block, `plan.blocks[${index}]`);
        const blockType = normalizeBlockType(block.block_type);
        if (!ALLOWED_MATERIALS.has(blockType)) {
            throw new TypeError(`plan.blocks[${index}].block_type ${block.block_type} is not allowed`);
        }
        block.block_type = blockType;
    }
    plan.blocks = orderBlocksForPlacement(plan.blocks);
    for (const [index, item] of clear.entries()) {
        assertBoundedDelta(item, `plan.clear[${index}]`);
    }
    normalizePlan({ origin, plan });
    return {
        palette: plan.palette || undefined,
        clear,
        blocks: plan.blocks,
    };
}

function builderMetadataPayload(resolved, extra = {}) {
    const usage = resolved && resolved.lastMetadata ? resolved.lastMetadata : {};
    return {
        provider: resolved && resolved.provider ? resolved.provider : extra.provider || 'local',
        builder_provider: resolved && resolved.provider ? resolved.provider : extra.provider || 'local',
        model: resolved && resolved.model ? resolved.model : extra.model,
        builder_model: resolved && resolved.model ? resolved.model : extra.model,
        paid: Boolean(resolved && resolved.paid),
        purpose: 'plan_generation',
        prompt_tokens: usage.prompt_tokens,
        completion_tokens: usage.completion_tokens,
        total_tokens: usage.total_tokens,
        usage_source: usage.usage_source,
        estimated: usage.estimated,
        estimated_usd: usage.estimated_usd,
        request_count_run: usage.request_count_run ?? resolved?.request_count_run,
        request_count_agent: usage.request_count_agent ?? resolved?.request_count_agent,
        max_calls_per_run: usage.max_calls_per_run,
        max_calls_per_agent: usage.max_calls_per_agent,
        max_estimated_usd_per_run: usage.max_estimated_usd_per_run,
        fallback_reason: resolved?.fallbackReason || extra.fallback_reason || undefined,
        ...extra,
    };
}

async function sendLocalBuilderRequest(agent, messages, systemMessage) {
    const model = localBuilderModel(agent);
    if (!model) {
        return { source: 'starter_blueprint', plan: null, raw: '', provider: 'local' };
    }
    const raw = await model.sendRequest(messages, systemMessage);
    return {
        source: 'builder_model',
        plan: extractJson(raw),
        raw,
        provider: 'local',
        model: localBuilderModelName(agent),
        paid: false,
    };
}

function markFatalBuilderError(err) {
    if (err && (err instanceof BuilderProviderError || err instanceof BuilderBudgetError)) {
        err.builderFatal = Boolean(err.fatal);
    }
    return err;
}

async function generateWithBuilderModel(agent, description, origin, maxSteps, traceId, telemetryBase = {}) {
    let resolved;
    try {
        resolved = resolveBuilderModel(agent);
    } catch (err) {
        emit(agent, 'build_plan.generation.provider_failed', traceId, {
            ...telemetryBase,
            provider: err && err.provider ? err.provider : process.env.MC_SIM_BUILDER_PROVIDER || 'local',
            reason: err && err.reason ? err.reason : 'provider_resolution_failed',
            error: err && err.message ? err.message : String(err),
            fallback_reason: '',
            ...builderProviderSnapshot(agent),
        });
        throw markFatalBuilderError(err);
    }

    if (!resolved.available) {
        const fallbackPlan = starterBlueprintOrNull(description, maxSteps);
        return {
            source: 'starter_blueprint',
            plan: fallbackPlan,
            raw: '',
            fallback_reason: fallbackPlan ? 'starter_blueprint' : 'no_starter_blueprint',
        };
    }

    const modelMaxSteps = plannerStepLimit(maxSteps);
    const systemMessage = [
        'You are a Minecraft building planner.',
        'Output only strict JSON with shape {"blocks":[{"dx":0,"dy":0,"dz":0,"block_type":"oak_log"}],"clear":[]}.',
        `Use at most ${modelMaxSteps} total clear+block steps for this single phase.`,
        'Prefer compact 6-24 block phases over one large complete structure.',
        `Keep dx/dz within ${MAX_RADIUS} blocks and dy between 0 and ${MAX_HEIGHT}.`,
        `Allowed block_type values: ${[...ALLOWED_MATERIALS].join(', ')}.`,
        'Order blocks from lowest dy to highest dy, and include a same-column support block before every dy>0 block.',
        'Stay within starter supplies: at most 24 oak_planks, 16 cobblestone, 16 dirt, 12 oak_log, 8 torch, 1 chest, and 1 crafting_table.',
        'Avoid placing the first block at dx=0,dz=0 when another nearby offset would work.',
        'Do not include markdown, comments, narration, or code fences.',
    ].join('\n');
    const userMessage = [
        `Build request: ${description}`,
        `Origin: ${JSON.stringify(origin)}`,
        'Prefer recognizable, compact structures that can be built from nearby starter materials.',
    ].join('\n');
    const previousPurpose = process.env.MC_LLM_REQUEST_PURPOSE;
    const previousReason = process.env.MC_LLM_REQUEST_REASON;
    process.env.MC_LLM_REQUEST_PURPOSE = 'plan_generation';
    process.env.MC_LLM_REQUEST_REASON = 'planAndBuild';
    const messages = [{ role: 'user', content: userMessage }];
    try {
        try {
            const raw = await resolved.sendRequest(messages, systemMessage, {
                traceId,
                agentId: agentId(agent),
                purpose: 'plan_generation',
                description,
                maxSteps: modelMaxSteps,
            });
            return {
                source: 'builder_model',
                plan: extractJson(raw),
                raw,
                ...builderMetadataPayload(resolved),
            };
        } catch (err) {
            const isBudget = err instanceof BuilderBudgetError;
            const failureType = isBudget
                ? 'build_plan.generation.budget_capped'
                : 'build_plan.generation.provider_failed';
            emit(agent, failureType, traceId, {
                ...telemetryBase,
                provider: resolved.provider,
                model: resolved.model,
                reason: err && err.reason ? err.reason : err && err.code ? err.code : 'provider_failed',
                error: err && err.message ? err.message : String(err),
                fallback_reason: resolved.fallbackMode === 'local' ? 'local' : '',
                ...builderProviderSnapshot(agent),
            });
            if (resolved.fallbackMode === 'local' && resolved.provider === 'openrouter') {
                const localResult = await sendLocalBuilderRequest(agent, messages, systemMessage);
                if (localResult.plan) {
                    return {
                        ...localResult,
                        fallback_reason:
                            err && err.reason ? err.reason : err && err.code ? err.code : 'provider_failed',
                    };
                }
            }
            const fatalErr = markFatalBuilderError(err);
            if (resolved.provider === 'openrouter') fatalErr.builderFatal = true;
            throw fatalErr;
        }
    } finally {
        if (previousPurpose === undefined) delete process.env.MC_LLM_REQUEST_PURPOSE;
        else process.env.MC_LLM_REQUEST_PURPOSE = previousPurpose;
        if (previousReason === undefined) delete process.env.MC_LLM_REQUEST_REASON;
        else process.env.MC_LLM_REQUEST_REASON = previousReason;
    }
}

export const planAndBuildAction = {
    name: '!planAndBuild',
    description:
        'Generate a bounded JSON build plan with the builder model, validate it, and execute it with buildFromPlan.',
    params: {
        description: {
            type: 'string',
            description:
                'High-level structure request, e.g. "small shared cabin" or "torch-lit storage corner".',
        },
    },
    perform: async function (agent, description) {
        const traceId = `trace-${randomUUID()}`;
        let actionId = `plan-build-${randomUUID()}`;
        const baseOrigin = originFromAgent(agent);
        if (!planBuildAllowedForAgent(agent)) {
            emit(agent, 'build_plan.generation.skipped', traceId, {
                action_id: actionId,
                description,
                origin: baseOrigin,
                reason: 'plan_build_agent_not_allowed',
                allowed_agents:
                    process.env.MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST ||
                    process.env.SOAK_PLAN_BUILD_BOTS ||
                    '',
            });
            return 'plan-and-build skipped: plan_build_agent_not_allowed';
        }
        const maxSteps = Number.parseInt(process.env.MINECRAFT_PLAN_BUILD_MAX_STEPS || '', 10);
        const stepLimit = Number.isInteger(maxSteps) && maxSteps > 0 ? maxSteps : DEFAULT_MAX_STEPS;
        const modelStepLimit = plannerStepLimit(stepLimit);
        const buildSettings = {
            max_steps: stepLimit,
            planner_max_steps: modelStepLimit,
            allowed_materials: [...ALLOWED_MATERIALS].sort(),
        };
        const directorContext = directorBuildContext(agent);
        if (directorContext.objectiveId) {
            buildSettings.objective_id = directorContext.objectiveId;
            buildSettings.phase_index = directorContext.phaseIndex;
        }
        const activeObjective = await readActiveSettlementObjective(agent, traceId);
        const staleReason = staleSettlementReason(activeObjective, directorContext, agent);
        if (staleReason) {
            emit(agent, 'build_plan.generation.skipped', traceId, {
                action_id: actionId,
                plan_id: directorContext.planId || null,
                ...commonBuildPayload(null, directorContext),
                description,
                origin: baseOrigin,
                reason: staleReason,
                active_objective_id: activeObjective.objective_id || activeObjective.id || null,
                active_objective_owner: activeObjective.owner_agent_id || null,
                active_objective_status: activeObjective.status || null,
                active_objective_phase_index: Number.isInteger(activeObjective.phase_index)
                    ? activeObjective.phase_index
                    : null,
            });
            return `plan-and-build skipped: ${staleReason}`;
        }
        if (activeObjective?.description) {
            description = String(activeObjective.description);
        }
        const acquisition = directorContext.sceneId
            ? tryAcquireSceneBuild(
                  directorContext.sceneId,
                  agent,
                  description,
                  baseOrigin,
                  buildSettings,
                  {
                      planId: directorContext.planId || undefined,
                      ownerAgentId: directorContext.owner || undefined,
                      objectiveId: directorContext.objectiveId || undefined,
                      phaseIndex: directorContext.phaseIndex ?? undefined,
                      phaseOwner: directorContext.phaseOwner || undefined,
                  },
              )
            : tryAcquireBuild(agent, description, baseOrigin, buildSettings);
        const origin = acquisition.origin || baseOrigin;
        actionId = acquisition.plan_id || actionId;
        const buildPayload = commonBuildPayload(acquisition, directorContext);

        if (!acquisition.allowed) {
            const skippedStatus = settlementStatusForSkippedAcquisition(acquisition.reason);
            if (skippedStatus) {
                await writeSettlementObjective(
                    agent,
                    'settlement_objective_advance',
                    directorContext,
                    traceId,
                    {
                        description,
                        owner:
                            acquisition.active_build_owner ||
                            directorContext.phaseOwner ||
                            directorContext.owner,
                        planId: actionId,
                        status: skippedStatus,
                        reason: acquisition.reason,
                        evidence: {
                            action_id: actionId,
                            scene_id: buildPayload.scene_id,
                            skipped_reason: acquisition.reason,
                        },
                    },
                );
            }
            emit(agent, 'build_plan.generation.skipped', traceId, {
                action_id: actionId,
                plan_id: acquisition.plan_id || null,
                ...buildPayload,
                description,
                origin,
                reason: acquisition.reason,
                cache_key: acquisition.cache_key,
                cache_hit: Boolean(acquisition.cache_hit),
                active_build_owner: acquisition.active_build_owner,
                active_build: acquisition.active_build,
                cooldown_remaining_sec: acquisition.cooldown_remaining_sec || 0,
                builder_call_count: acquisition.builder_call_count,
                max_builder_calls_per_agent: acquisition.max_builder_calls_per_agent,
                skipped_repeat_count: acquisition.skipped_repeat_count || 0,
            });
            return `plan-and-build skipped: ${acquisition.reason}`;
        }

        await writeSettlementObjective(agent, 'settlement_objective_assign', directorContext, traceId, {
            description,
            owner: acquisition.active_build_owner || directorContext.phaseOwner || directorContext.owner,
            planId: actionId,
            reason: 'plan_and_build_started',
            ownerStartedAtMs: Date.now(),
        });

        emit(agent, 'build_plan.generation.started', traceId, {
            action_id: actionId,
            plan_id: actionId,
            ...buildPayload,
            description,
            origin,
            base_origin: baseOrigin,
            max_steps: stepLimit,
            planner_max_steps: modelStepLimit,
            purpose: 'plan_generation',
            cache_key: acquisition.cache_key,
            cache_hit: Boolean(acquisition.cache_hit),
            active_build_owner: acquisition.active_build_owner,
            active_build: acquisition.active_build,
            cooldown_remaining_sec: acquisition.cooldown_remaining_sec || 0,
            builder_call_count: acquisition.builder_call_count,
            max_builder_calls_per_agent: acquisition.max_builder_calls_per_agent,
            ...builderProviderSnapshot(agent),
        });

        let generated;
        let plan;
        try {
            if (acquisition.cache_hit && acquisition.cached_plan) {
                emit(agent, 'build_plan.generation.skipped', traceId, {
                    action_id: actionId,
                    plan_id: actionId,
                    ...buildPayload,
                    description,
                    origin,
                    reason: 'cache_hit',
                    cache_key: acquisition.cache_key,
                    cache_hit: true,
                    active_build_owner: acquisition.active_build_owner,
                    active_build: acquisition.active_build,
                    cooldown_remaining_sec: 0,
                    builder_call_count: acquisition.builder_call_count,
                    max_builder_calls_per_agent: acquisition.max_builder_calls_per_agent,
                    skipped_repeat_count: acquisition.skipped_repeat_count || 0,
                });
                generated = {
                    source: 'plan_cache',
                    raw: '',
                    plan: acquisition.cached_plan,
                    provider: 'cache',
                    model: 'plan_cache',
                    paid: false,
                    fallback_reason: 'cache_hit',
                };
            } else {
                const callState = recordBuilderCallStarted(agent, acquisition);
                generated = await generateWithBuilderModel(
                    agent,
                    description,
                    origin,
                    stepLimit,
                    traceId,
                    buildPayload,
                );
                generated.builder_call_count = callState.builder_call_count;
                generated.max_builder_calls_per_agent = callState.max_builder_calls_per_agent;
            }
            plan = validateGeneratedPlan(generated.plan, origin, modelStepLimit);
            assertPlanMatchesRequest(plan, description, stepLimit);
            if (!acquisition.cache_hit) {
                recordPlanGenerated(agent, acquisition, plan);
            }
        } catch (err) {
            emit(agent, 'build_plan.generation.rejected', traceId, {
                action_id: actionId,
                plan_id: actionId,
                ...buildPayload,
                description,
                origin,
                error: err && err.message ? err.message : String(err),
                provider: generated?.provider || err?.provider || process.env.MC_SIM_BUILDER_PROVIDER || 'local',
                model: generated?.model,
                builder_provider:
                    generated?.provider || err?.provider || process.env.MC_SIM_BUILDER_PROVIDER || 'local',
                builder_model: generated?.model,
                purpose: 'plan_generation',
                cache_key: acquisition.cache_key,
                cache_hit: Boolean(acquisition.cache_hit),
                active_build_owner: acquisition.active_build_owner,
                active_build: governorSnapshot(agent).active_build,
                builder_call_count: governorSnapshot(agent).builder_call_count,
                max_builder_calls_per_agent: acquisition.max_builder_calls_per_agent,
            });
            if (err && err.builderFatal) {
                recordBuildFailed(agent, actionId, err && err.message ? err.message : String(err), {
                    reason: err && err.reason ? err.reason : err && err.code ? err.code : undefined,
                });
                return `plan-and-build ${actionId} failed: ${
                    err && err.message ? err.message : String(err)
                }`;
            }
            const fallbackPlan = starterBlueprintOrNull(description, stepLimit);
            if (!fallbackPlan) {
                return skippedPlanResult(
                    agent,
                    traceId,
                    actionId,
                    acquisition,
                    buildPayload,
                    description,
                    origin,
                    'no_starter_blueprint',
                );
            }
            generated = {
                source: 'starter_blueprint_after_rejection',
                raw: '',
                plan: fallbackPlan,
                fallback_reason: 'starter_blueprint_after_rejection',
            };
            plan = validateGeneratedPlan(generated.plan, origin, stepLimit);
            recordPlanGenerated(agent, acquisition, plan);
        }

        console.log(`[plan-and-build trace=${traceId}] plan json: ${JSON.stringify(plan)}`);
        emit(agent, 'build_plan.generation.completed', traceId, {
            action_id: actionId,
            plan_id: actionId,
            ...buildPayload,
            description,
            origin,
            base_origin: baseOrigin,
            source: generated.source,
            provider: generated.provider || 'local',
            builder_provider: generated.provider || 'local',
            model: generated.model,
            builder_model: generated.model,
            paid: Boolean(generated.paid),
            purpose: 'plan_generation',
            prompt_tokens: generated.prompt_tokens,
            completion_tokens: generated.completion_tokens,
            total_tokens: generated.total_tokens,
            usage_source: generated.usage_source,
            estimated: generated.estimated,
            estimated_usd: generated.estimated_usd || 0,
            request_count_run: generated.request_count_run || 0,
            request_count_agent: generated.request_count_agent || 0,
            max_calls_per_run: generated.max_calls_per_run,
            max_calls_per_agent: generated.max_calls_per_agent,
            max_estimated_usd_per_run: generated.max_estimated_usd_per_run,
            fallback_reason: generated.fallback_reason || '',
            cache_key: acquisition.cache_key,
            cache_hit: Boolean(acquisition.cache_hit),
            active_build_owner: acquisition.active_build_owner,
            active_build: governorSnapshot(agent).active_build,
            builder_call_count:
                generated.builder_call_count || governorSnapshot(agent).builder_call_count || 0,
            max_builder_calls_per_agent:
                generated.max_builder_calls_per_agent || acquisition.max_builder_calls_per_agent,
            plan,
            plan_json: JSON.stringify(plan),
            max_steps: stepLimit,
            planner_max_steps: modelStepLimit,
        });

        emit(agent, 'build_plan.execution.started', traceId, {
            action_id: actionId,
            plan_id: actionId,
            ...buildPayload,
            origin,
            step_count: (plan.clear || []).length + (plan.blocks || []).length,
            cache_key: acquisition.cache_key,
            active_build_owner: acquisition.active_build_owner,
            active_build: governorSnapshot(agent).active_build,
        });
        let result;
        try {
            result = await performBuildFromPlan(
                agent,
                actionId,
                origin,
                plan,
                stepLimit,
                DEFAULT_TIMEOUT_MS,
            );
        } catch (err) {
            recordBuildFailed(agent, actionId, err && err.message ? err.message : String(err), {
                reason: err && err.reason ? err.reason : undefined,
            });
            throw err;
        }
        const metrics = executionMetrics(result);
        const effectiveSuccess =
            /\bsuccess\b/i.test(String(result || '')) || (metrics.completion_ratio || 0) >= 0.8;
        const buildState = effectiveSuccess
            ? recordBuildCompleted(agent, actionId, result)
            : recordBuildFailed(agent, actionId, result);
        emit(agent, 'build_plan.execution.completed', traceId, {
            action_id: actionId,
            plan_id: actionId,
            ...buildPayload,
            origin,
            result,
            verified_blocks: metrics.verified_blocks || 0,
            verified_block_changes: metrics.verified_blocks || 0,
            metric: {
                intended_count: metrics.intended_blocks || 0,
                blocks_present: metrics.blocks_present || 0,
                blocks_missing: metrics.blocks_missing || 0,
                blocks_unexpected: metrics.blocks_unexpected || 0,
                steps_verified: metrics.verified_blocks || 0,
                steps_abandoned: metrics.steps_abandoned || 0,
                completion_ratio: metrics.completion_ratio || 0,
            },
            cache_key: acquisition.cache_key,
            active_build_owner: acquisition.active_build_owner,
            active_build: buildState.active_build,
            status: buildState.status,
            cooldown_remaining_sec: buildState.cooldown_remaining_sec || 0,
        });
        await writeSettlementObjective(agent, 'settlement_objective_advance', directorContext, traceId, {
            description,
            owner: acquisition.active_build_owner || directorContext.phaseOwner || directorContext.owner,
            planId: actionId,
            status: effectiveSuccess ? 'completed' : 'blocked',
            intendedBlocks: metrics.intended_blocks || 0,
            verifiedBlocks: metrics.verified_blocks || 0,
            completionRatio: metrics.completion_ratio || 0,
            evidence: {
                action_id: actionId,
                scene_id: buildPayload.scene_id,
                result_excerpt: String(result || '').slice(0, 240),
            },
        });
        return `plan-and-build ${actionId}: ${result}`;
    },
};

export default planAndBuildAction;

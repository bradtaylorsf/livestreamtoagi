// Builder-model plan generation plus bounded buildFromPlan execution.

import { randomUUID } from 'node:crypto';

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
} from '../skills/build_plan_governor.js';
import { normalizePlan } from '../skills/build_plan.js';
import { normalizeBlockType, positionFrom } from '../skills/building.js';
import { performBuildFromPlan } from './build_from_plan_action.js';

const DEFAULT_MAX_STEPS = 64;
const DEFAULT_TIMEOUT_MS = 60000;
const MAX_RADIUS = 6;
const MAX_HEIGHT = 5;
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

function starterBlueprint(description) {
    const text = String(description || '').toLowerCase();
    if (text.includes('hut') || text.includes('cabin') || text.includes('shelter')) {
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

async function generateWithBuilderModel(agent, description, origin, maxSteps, traceId) {
    let resolved;
    try {
        resolved = resolveBuilderModel(agent);
    } catch (err) {
        emit(agent, 'build_plan.generation.provider_failed', traceId, {
            provider: err && err.provider ? err.provider : process.env.MC_SIM_BUILDER_PROVIDER || 'local',
            reason: err && err.reason ? err.reason : 'provider_resolution_failed',
            error: err && err.message ? err.message : String(err),
            fallback_reason: '',
            ...builderProviderSnapshot(agent),
        });
        throw markFatalBuilderError(err);
    }

    if (!resolved.available) {
        return { source: 'starter_blueprint', plan: starterBlueprint(description), raw: '' };
    }

    const systemMessage = [
        'You are a Minecraft building planner.',
        'Output only strict JSON with shape {"blocks":[{"dx":0,"dy":0,"dz":0,"block_type":"oak_log"}],"clear":[]}.',
        `Use at most ${maxSteps} total clear+block steps.`,
        `Keep dx/dz within ${MAX_RADIUS} blocks and dy between 0 and ${MAX_HEIGHT}.`,
        `Allowed block_type values: ${[...ALLOWED_MATERIALS].join(', ')}.`,
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
                maxSteps,
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
        const maxSteps = Number.parseInt(process.env.MINECRAFT_PLAN_BUILD_MAX_STEPS || '', 10);
        const stepLimit = Number.isInteger(maxSteps) && maxSteps > 0 ? maxSteps : DEFAULT_MAX_STEPS;
        const buildSettings = {
            max_steps: stepLimit,
            allowed_materials: [...ALLOWED_MATERIALS].sort(),
        };
        const acquisition = tryAcquireBuild(agent, description, baseOrigin, buildSettings);
        const origin = acquisition.origin || baseOrigin;
        actionId = acquisition.plan_id || actionId;

        if (!acquisition.allowed) {
            emit(agent, 'build_plan.generation.skipped', traceId, {
                action_id: actionId,
                plan_id: acquisition.plan_id || null,
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

        emit(agent, 'build_plan.generation.started', traceId, {
            action_id: actionId,
            plan_id: actionId,
            description,
            origin,
            base_origin: baseOrigin,
            max_steps: stepLimit,
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
                );
                generated.builder_call_count = callState.builder_call_count;
                generated.max_builder_calls_per_agent = callState.max_builder_calls_per_agent;
            }
            plan = validateGeneratedPlan(generated.plan, origin, stepLimit);
            if (!acquisition.cache_hit) {
                recordPlanGenerated(agent, acquisition, plan);
            }
        } catch (err) {
            emit(agent, 'build_plan.generation.rejected', traceId, {
                action_id: actionId,
                plan_id: actionId,
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
                recordBuildFailed(agent, actionId, err && err.message ? err.message : String(err));
                return `plan-and-build ${actionId} failed: ${
                    err && err.message ? err.message : String(err)
                }`;
            }
            generated = { source: 'starter_blueprint_after_rejection', raw: '', plan: starterBlueprint(description) };
            plan = validateGeneratedPlan(generated.plan, origin, stepLimit);
            recordPlanGenerated(agent, acquisition, plan);
        }

        console.log(`[plan-and-build trace=${traceId}] plan json: ${JSON.stringify(plan)}`);
        emit(agent, 'build_plan.generation.completed', traceId, {
            action_id: actionId,
            plan_id: actionId,
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
        });

        emit(agent, 'build_plan.execution.started', traceId, {
            action_id: actionId,
            plan_id: actionId,
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
            recordBuildFailed(agent, actionId, err && err.message ? err.message : String(err));
            throw err;
        }
        const buildState = /\bsuccess\b/i.test(String(result || ''))
            ? recordBuildCompleted(agent, actionId, result)
            : recordBuildFailed(agent, actionId, result);
        emit(agent, 'build_plan.execution.completed', traceId, {
            action_id: actionId,
            plan_id: actionId,
            origin,
            result,
            cache_key: acquisition.cache_key,
            active_build_owner: acquisition.active_build_owner,
            active_build: buildState.active_build,
            status: buildState.status,
            cooldown_remaining_sec: buildState.cooldown_remaining_sec || 0,
        });
        return `plan-and-build ${actionId}: ${result}`;
    },
};

export default planAndBuildAction;

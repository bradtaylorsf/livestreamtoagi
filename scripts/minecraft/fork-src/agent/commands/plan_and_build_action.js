// Builder-model plan generation plus bounded buildFromPlan execution.

import { randomUUID } from 'node:crypto';

import { emitTimelineEvent } from '../bridge/timeline_emitter.js';
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

async function generateWithBuilderModel(agent, description, origin, maxSteps) {
    const model = agent && agent.prompter && agent.prompter.code_model;
    if (!model || typeof model.sendRequest !== 'function') {
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
    try {
        const raw = await model.sendRequest([{ role: 'user', content: userMessage }], systemMessage);
        return { source: 'builder_model', plan: extractJson(raw), raw };
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
        const actionId = `plan-build-${randomUUID()}`;
        const origin = originFromAgent(agent);
        const maxSteps = Number.parseInt(process.env.MINECRAFT_PLAN_BUILD_MAX_STEPS || '', 10);
        const stepLimit = Number.isInteger(maxSteps) && maxSteps > 0 ? maxSteps : DEFAULT_MAX_STEPS;

        emit(agent, 'build_plan.generation.started', traceId, {
            action_id: actionId,
            description,
            origin,
            max_steps: stepLimit,
        });

        let generated;
        let plan;
        try {
            generated = await generateWithBuilderModel(agent, description, origin, stepLimit);
            plan = validateGeneratedPlan(generated.plan, origin, stepLimit);
        } catch (err) {
            emit(agent, 'build_plan.generation.rejected', traceId, {
                action_id: actionId,
                description,
                origin,
                error: err && err.message ? err.message : String(err),
            });
            generated = { source: 'starter_blueprint_after_rejection', raw: '', plan: starterBlueprint(description) };
            plan = validateGeneratedPlan(generated.plan, origin, stepLimit);
        }

        console.log(`[plan-and-build trace=${traceId}] plan json: ${JSON.stringify(plan)}`);
        emit(agent, 'build_plan.generation.completed', traceId, {
            action_id: actionId,
            description,
            origin,
            source: generated.source,
            plan,
            plan_json: JSON.stringify(plan),
            max_steps: stepLimit,
        });

        emit(agent, 'build_plan.execution.started', traceId, {
            action_id: actionId,
            origin,
            step_count: (plan.clear || []).length + (plan.blocks || []).length,
        });
        const result = await performBuildFromPlan(
            agent,
            actionId,
            origin,
            plan,
            stepLimit,
            DEFAULT_TIMEOUT_MS,
        );
        emit(agent, 'build_plan.execution.completed', traceId, {
            action_id: actionId,
            origin,
            result,
        });
        return `plan-and-build ${actionId}: ${result}`;
    },
};

export default planAndBuildAction;

// Pure multi-block build-plan verification helpers for E6-4 (#559).
//
// This file deliberately has no Mineflayer, Minecraft, bridge, or Node runtime
// dependencies. The action file expands a structured plan into place/break
// steps and uses these helpers to report final actual-vs-intended completion.

import { isAirBlock, normalizeBlockType, positionFrom } from './building.js';

export const BUILD_PLAN_CLASSES = Object.freeze([
    'success',
    'partial',
    'blocked',
    'timed-out',
    'invalid',
    'bridge-down',
]);

function finiteNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function deltaFrom(value, label) {
    if (value === null || value === undefined || typeof value !== 'object') {
        throw new TypeError(`${label} must be an object`);
    }
    const dx = finiteNumber(value.dx);
    const dy = finiteNumber(value.dy);
    const dz = finiteNumber(value.dz);
    if (dx === null || dy === null || dz === null) {
        throw new TypeError(`${label} must include finite dx/dy/dz`);
    }
    return { dx: Math.floor(dx), dy: Math.floor(dy), dz: Math.floor(dz) };
}

function positionKey(position) {
    const cell = positionFrom(position);
    return cell ? `${cell.x},${cell.y},${cell.z}` : null;
}

function keyToPosition(key) {
    const parts = String(key).split(',').map((part) => Number(part));
    if (parts.length !== 3 || parts.some((n) => !Number.isFinite(n))) return null;
    return { x: parts[0], y: parts[1], z: parts[2] };
}

function absolutePosition(origin, delta) {
    return {
        x: origin.x + delta.dx,
        y: origin.y + delta.dy,
        z: origin.z + delta.dz,
    };
}

function normalizePalette(rawPalette) {
    if (rawPalette === undefined || rawPalette === null) return new Map();
    if (typeof rawPalette !== 'object' || Array.isArray(rawPalette)) {
        throw new TypeError('plan.palette must be an object map');
    }

    const palette = new Map();
    for (const [key, value] of Object.entries(rawPalette)) {
        const normalizedValue = normalizeBlockType(value);
        if (!normalizedValue || isAirBlock(normalizedValue)) {
            throw new TypeError(`plan.palette.${key} must map to a non-air block type`);
        }
        palette.set(String(key).trim(), normalizedValue);
        const normalizedKey = normalizeBlockType(key);
        if (normalizedKey) palette.set(normalizedKey, normalizedValue);
    }
    return palette;
}

function resolveBlockType(value, palette, label) {
    const raw = value === undefined || value === null ? null : String(value).trim();
    const mapped = raw && palette.has(raw) ? palette.get(raw) : value;
    const normalizedMapped = normalizeBlockType(mapped);
    const normalized =
        normalizedMapped && palette.has(normalizedMapped)
            ? palette.get(normalizedMapped)
            : normalizedMapped;
    if (!normalized || isAirBlock(normalized)) {
        throw new TypeError(`${label} must resolve to a non-air block type`);
    }
    return normalized;
}

function normalizePlanClass(value, fallback = 'partial') {
    const reported = String(value || '').toLowerCase();
    return BUILD_PLAN_CLASSES.includes(reported) ? reported : fallback;
}

export function normalizePlan({ origin, plan } = {}) {
    const base = positionFrom(origin);
    if (!base) throw new TypeError('origin must include finite x/y/z');
    if (plan === null || plan === undefined || typeof plan !== 'object' || Array.isArray(plan)) {
        throw new TypeError('plan must be an object');
    }

    const blocks = Array.isArray(plan.blocks) ? plan.blocks : null;
    if (!blocks || blocks.length === 0) {
        throw new TypeError('plan.blocks must contain at least one block');
    }
    const clear = plan.clear === undefined || plan.clear === null ? [] : plan.clear;
    if (!Array.isArray(clear)) throw new TypeError('plan.clear must be an array when provided');

    const palette = normalizePalette(plan.palette);
    const steps = [];

    for (const [planIndex, item] of clear.entries()) {
        const delta = deltaFrom(item, `plan.clear[${planIndex}]`);
        steps.push({
            index: steps.length,
            plan_index: planIndex,
            source: 'clear',
            action: 'break',
            ...delta,
            position: absolutePosition(base, delta),
            expected_block_type: null,
        });
    }

    for (const [planIndex, item] of blocks.entries()) {
        const delta = deltaFrom(item, `plan.blocks[${planIndex}]`);
        const blockType = resolveBlockType(
            item && item.block_type,
            palette,
            `plan.blocks[${planIndex}].block_type`,
        );
        steps.push({
            index: steps.length,
            plan_index: planIndex,
            source: 'blocks',
            action: 'place',
            ...delta,
            position: absolutePosition(base, delta),
            block_type: blockType,
            expected_block_type: blockType,
        });
    }

    return { origin: base, steps };
}

function blockTypeFromFinalEntry(entry) {
    if (entry === null || entry === undefined) return null;
    if (typeof entry === 'object') {
        return normalizeBlockType(
            entry.block_type ??
                entry.blockType ??
                entry.final_block ??
                entry.after_block ??
                entry.name ??
                entry.displayName,
        );
    }
    return normalizeBlockType(entry);
}

function finalBlocksMap(finalBlocks) {
    const observed = new Map();
    if (!finalBlocks) return observed;

    if (finalBlocks instanceof Map) {
        for (const [key, value] of finalBlocks.entries()) {
            const position = keyToPosition(key) || positionFrom(key);
            const cellKey = position ? positionKey(position) : String(key);
            observed.set(cellKey, normalizeBlockType(value));
        }
        return observed;
    }

    if (Array.isArray(finalBlocks)) {
        for (const entry of finalBlocks) {
            const position = positionFrom(entry && (entry.position || entry));
            const key = positionKey(position);
            if (key) observed.set(key, blockTypeFromFinalEntry(entry));
        }
        return observed;
    }

    if (typeof finalBlocks === 'object') {
        for (const [key, value] of Object.entries(finalBlocks)) {
            const position = keyToPosition(key);
            if (position) observed.set(positionKey(position), blockTypeFromFinalEntry(value));
        }
    }
    return observed;
}

function stepClass(step) {
    return String(step.class || step.outcome_class || step.outcomeClass || '').toLowerCase();
}

function stepStatus(step) {
    return String(step.status || '').toLowerCase();
}

function isStepAbandoned(step) {
    const cls = stepClass(step);
    const status = stepStatus(step);
    return Boolean(step.abandoned) || cls === 'abandoned' || status === 'abandoned';
}

function finalBlockForStep(step, observed) {
    const key = positionKey(step && step.position);
    if (key && observed.has(key)) return observed.get(key);
    return normalizeBlockType(step && (step.final_block ?? step.after_block));
}

function isStepVerified(step, observed) {
    if (!step || isStepAbandoned(step)) return false;
    const cls = stepClass(step);
    const status = stepStatus(step);
    if (cls === 'placed' || cls === 'removed' || status === 'success') return true;
    if (cls || status === 'failure') return false;

    const finalBlock = finalBlockForStep(step, observed);
    if (step.action === 'place') return finalBlock === normalizeBlockType(step.block_type);
    if (step.action === 'break') return isAirBlock(finalBlock);
    return false;
}

export function completionMetric({ steps, finalBlocks } = {}) {
    const normalizedSteps = Array.isArray(steps) ? steps : [];
    const observed = finalBlocksMap(finalBlocks);
    const intended = new Map();

    for (const step of normalizedSteps) {
        const key = positionKey(step && step.position);
        if (!key) continue;
        if (step.action === 'place') {
            const blockType = normalizeBlockType(step.block_type || step.expected_block_type);
            if (blockType && !isAirBlock(blockType)) intended.set(key, blockType);
        }
    }

    let blocksPresent = 0;
    let blocksMissing = 0;
    for (const [key, expected] of intended.entries()) {
        const actual = observed.get(key);
        if (actual === expected) blocksPresent += 1;
        else blocksMissing += 1;
    }

    let blocksUnexpected = 0;
    for (const [key, actual] of observed.entries()) {
        if (!actual || isAirBlock(actual)) continue;
        const expected = intended.get(key);
        if (!expected || expected !== actual) blocksUnexpected += 1;
    }

    const stepsVerified = normalizedSteps.filter((step) => isStepVerified(step, observed)).length;
    const stepsAbandoned = normalizedSteps.filter((step) => isStepAbandoned(step)).length;
    const intendedCount = intended.size;
    const completionRatio = intendedCount > 0 ? blocksPresent / intendedCount : 0;

    return {
        intended_count: intendedCount,
        blocks_present: blocksPresent,
        blocks_missing: blocksMissing,
        blocks_unexpected: blocksUnexpected,
        steps_verified: stepsVerified,
        steps_abandoned: stepsAbandoned,
        completion_ratio: completionRatio,
    };
}

export function classifyPlan({ metric, failureClass } = {}) {
    if (!metric || Number(metric.intended_count) <= 0) {
        return normalizePlanClass(failureClass, 'invalid');
    }
    if (
        metric.blocks_present === metric.intended_count &&
        metric.blocks_missing === 0 &&
        metric.blocks_unexpected === 0 &&
        metric.steps_abandoned === 0
    ) {
        return 'success';
    }
    if (metric.blocks_present > 0 || metric.steps_verified > 0) return 'partial';
    return normalizePlanClass(failureClass, 'partial');
}

export function statusForPlanClass(outcomeClass) {
    const cls = normalizePlanClass(outcomeClass, 'invalid');
    if (cls === 'success') return 'success';
    if (cls === 'partial') return 'partial';
    return 'failure';
}

function serializeStep(step) {
    const position = positionFrom(step && step.position);
    return {
        index: Number.isInteger(step && step.index) ? step.index : null,
        action: step && step.action,
        source: step && step.source,
        position,
        block_type: normalizeBlockType(step && step.block_type),
        expected_block_type: normalizeBlockType(step && step.expected_block_type),
        before_block: normalizeBlockType(step && step.before_block),
        after_block: normalizeBlockType(step && step.after_block),
        final_block: normalizeBlockType(step && (step.final_block ?? step.after_block)),
        class: stepClass(step) || null,
        abandoned: Boolean(step && step.abandoned),
    };
}

function finalBlocksFromSteps(steps) {
    const observed = new Map();
    for (const step of Array.isArray(steps) ? steps : []) {
        const key = positionKey(step && step.position);
        if (!key) continue;
        const blockType = normalizeBlockType(step && (step.final_block ?? step.after_block));
        if (!observed.has(key)) {
            observed.set(key, {
                position: positionFrom(step.position),
                block_type: blockType,
            });
        } else {
            observed.get(key).block_type = blockType;
        }
    }
    return Array.from(observed.values());
}

export function structureObservation({
    action = 'build-from-plan',
    actionId,
    origin,
    steps,
    metric,
    outcomeClass,
} = {}) {
    return {
        type: 'structure',
        action,
        action_id: actionId,
        origin: positionFrom(origin),
        steps: (Array.isArray(steps) ? steps : []).map((step) => serializeStep(step)),
        final_blocks: finalBlocksFromSteps(steps),
        metric: {
            intended_count: Number(metric && metric.intended_count) || 0,
            blocks_present: Number(metric && metric.blocks_present) || 0,
            blocks_missing: Number(metric && metric.blocks_missing) || 0,
            blocks_unexpected: Number(metric && metric.blocks_unexpected) || 0,
            steps_verified: Number(metric && metric.steps_verified) || 0,
            steps_abandoned: Number(metric && metric.steps_abandoned) || 0,
            completion_ratio: Number(metric && metric.completion_ratio) || 0,
        },
        class: normalizePlanClass(outcomeClass, 'invalid'),
    };
}

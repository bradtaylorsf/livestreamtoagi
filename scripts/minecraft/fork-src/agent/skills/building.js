// Pure block placement/break verification helpers for E6-3 (#558).
//
// This file deliberately has no Mineflayer, Minecraft, bridge, or Node runtime
// dependencies. The action files read the world before/after a place/break
// attempt and use these helpers to classify the observed block state.

export const BUILD_CLASSES = Object.freeze([
    'placed',
    'removed',
    'blocked',
    'protected',
    'invalid',
    'tool-missing',
    'timed-out',
    'partial',
]);

const AIR_BLOCK_TYPES = new Set(['air', 'cave_air', 'void_air']);

function finiteNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function blockNameFrom(value) {
    if (value === null || value === undefined) return null;
    if (typeof value === 'string' || typeof value === 'number') return value;
    if (typeof value !== 'object') return null;
    return value.name ?? value.block_type ?? value.blockType ?? value.displayName ?? null;
}

export function positionFrom(value) {
    if (value === null || value === undefined || typeof value !== 'object') return null;
    const x = finiteNumber(value.x);
    const y = finiteNumber(value.y);
    const z = finiteNumber(value.z);
    if (x === null || y === null || z === null) return null;
    return { x: Math.floor(x), y: Math.floor(y), z: Math.floor(z) };
}

export function normalizeBlockType(value) {
    const raw = blockNameFrom(value);
    if (raw === null || raw === undefined) return null;
    const normalized = String(raw)
        .trim()
        .toLowerCase()
        .replace(/^minecraft:/, '')
        .replace(/\s+/g, '_');
    return normalized.length > 0 ? normalized : null;
}

export function isAirBlock(value) {
    const blockType = normalizeBlockType(value);
    return blockType === null || AIR_BLOCK_TYPES.has(blockType);
}

function reportedBuildClass(value, fallback) {
    const reported = String(value || '').toLowerCase();
    return BUILD_CLASSES.includes(reported) ? reported : fallback;
}

export function classifyPlace({ afterBlock, blockType, failureClass } = {}) {
    const expected = normalizeBlockType(blockType);
    const after = normalizeBlockType(afterBlock);
    if (!expected || AIR_BLOCK_TYPES.has(expected)) {
        return reportedBuildClass(failureClass, 'invalid');
    }
    if (after === expected) return 'placed';
    return reportedBuildClass(failureClass, 'blocked');
}

export function classifyBreak({ beforeBlock, afterBlock, expectedBlockType, failureClass } = {}) {
    const before = normalizeBlockType(beforeBlock);
    const after = normalizeBlockType(afterBlock);
    const expected = normalizeBlockType(expectedBlockType);

    if (!before || AIR_BLOCK_TYPES.has(before)) {
        return reportedBuildClass(failureClass, 'invalid');
    }
    if (expected && before && !AIR_BLOCK_TYPES.has(before) && before !== expected) {
        return reportedBuildClass(failureClass, 'invalid');
    }
    if (isAirBlock(afterBlock)) return 'removed';
    if (after && after !== before) return reportedBuildClass(failureClass, 'partial');
    return reportedBuildClass(failureClass, 'blocked');
}

export function statusForBuildClass(outcomeClass) {
    if (outcomeClass === 'placed' || outcomeClass === 'removed') return 'success';
    if (outcomeClass === 'partial') return 'partial';
    return 'failure';
}

export function blockObservation({
    action,
    actionId,
    position,
    beforeBlock,
    afterBlock,
    expectedBlockType,
    outcomeClass,
} = {}) {
    return {
        type: 'block',
        action,
        action_id: actionId,
        position: positionFrom(position),
        before_block: normalizeBlockType(beforeBlock),
        after_block: normalizeBlockType(afterBlock),
        expected_block_type: normalizeBlockType(expectedBlockType),
        class: reportedBuildClass(outcomeClass, 'invalid'),
    };
}

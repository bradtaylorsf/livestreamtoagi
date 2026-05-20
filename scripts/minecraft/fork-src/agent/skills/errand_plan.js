// Pure Alpha errand-plan parser and outcome reducer for E7-3 (#567).
//
// This module has no Mineflayer or bridge dependency so Python tests can run
// it directly under Node. The runtime action consumes the normalized steps and
// maps the verified action results back to Alpha's ✓/✗/? vocabulary.

export const SUCCESS_SYMBOL = '✓';
export const FAILURE_SYMBOL = '✗';
export const UNKNOWN_SYMBOL = '?';

const ERRAND_KINDS = new Set(['navigate', 'place', 'fetch_place']);
const STEP_ACTIONS_BY_KIND = {
    navigate: new Set(['navigate']),
    place: new Set(['place']),
    fetch_place: new Set(['navigate', 'place']),
};

function isObject(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function nonEmptyString(value) {
    return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function optionalPositiveNumber(value, fieldName) {
    if (value === undefined || value === null || value === '') return { value: undefined };
    const n = Number(value);
    if (!Number.isFinite(n) || n <= 0) return { error: `${fieldName} must be positive` };
    return { value: n };
}

function positionFrom(value) {
    if (!isObject(value)) return null;
    const x = Number(value.x);
    const y = Number(value.y);
    const z = Number(value.z);
    if (![x, y, z].every(Number.isFinite)) return null;
    return { x, y, z };
}

function normalizeNavigate(actionId, payload) {
    if (!isObject(payload)) return { error: 'navigate must be an object' };
    if (payload.target === undefined || payload.target === null) {
        return { error: 'navigate.target is required' };
    }
    const tolerance = optionalPositiveNumber(
        payload.arrive_within_blocks,
        'navigate.arrive_within_blocks',
    );
    if (tolerance.error) return tolerance;
    const timeout = optionalPositiveNumber(payload.timeout_ms, 'navigate.timeout_ms');
    if (timeout.error) return timeout;
    return {
        value: {
            action: 'navigate',
            action_id: actionId,
            navigate: {
                target: payload.target,
                arrive_within_blocks: tolerance.value,
                timeout_ms: timeout.value,
            },
        },
    };
}

function normalizePlace(actionId, payload) {
    if (!isObject(payload)) return { error: 'place must be an object' };
    const blockType = nonEmptyString(payload.block_type);
    if (!blockType) return { error: 'place.block_type is required' };
    const position = positionFrom(payload.position);
    if (!position) return { error: 'place.position must be {x,y,z}' };
    const face = payload.face === undefined || payload.face === null ? 'up' : nonEmptyString(payload.face);
    if (!face) return { error: 'place.face must be a string' };
    const sourceSlot =
        payload.source_slot === undefined || payload.source_slot === null || payload.source_slot === ''
            ? undefined
            : Number(payload.source_slot);
    if (sourceSlot !== undefined && (!Number.isInteger(sourceSlot) || sourceSlot < 0)) {
        return { error: 'place.source_slot must be a non-negative integer' };
    }
    return {
        value: {
            action: 'place',
            action_id: actionId,
            place: {
                block_type: blockType,
                position,
                face,
                source_slot: sourceSlot,
            },
        },
    };
}

function normalizeStep(step, index, kind) {
    if (!isObject(step)) return { error: `steps[${index}] must be an object` };
    const actionId = nonEmptyString(step.action_id);
    if (!actionId) return { error: `steps[${index}].action_id is required` };

    const hasNavigate = step.navigate !== undefined;
    const hasPlace = step.place !== undefined;
    if (hasNavigate === hasPlace) {
        return { error: `steps[${index}] must contain exactly one of navigate or place` };
    }

    const action = hasNavigate ? 'navigate' : 'place';
    if (!STEP_ACTIONS_BY_KIND[kind].has(action)) {
        return { error: `kind ${kind} cannot contain ${action} steps` };
    }

    return hasNavigate
        ? normalizeNavigate(actionId, step.navigate)
        : normalizePlace(actionId, step.place);
}

export function parseErrandPlan(taskString) {
    if (typeof taskString !== 'string' || !taskString.trim()) {
        return { error: 'task must be a non-empty JSON string' };
    }

    let parsed;
    try {
        parsed = JSON.parse(taskString);
    } catch (err) {
        const detail = err && err.message ? err.message : String(err);
        return { error: `task JSON parse failed: ${detail}` };
    }

    if (!isObject(parsed)) return { error: 'task JSON must be an object' };
    const kind = nonEmptyString(parsed.kind);
    if (!kind || !ERRAND_KINDS.has(kind)) {
        return { error: 'kind must be navigate, place, or fetch_place' };
    }
    if (!Array.isArray(parsed.steps) || parsed.steps.length === 0) {
        return { error: 'steps must be a non-empty array' };
    }

    const steps = [];
    for (let i = 0; i < parsed.steps.length; i += 1) {
        const normalized = normalizeStep(parsed.steps[i], i, kind);
        if (normalized.error) return { error: normalized.error };
        steps.push(normalized.value);
    }
    return { kind, steps };
}

export function deriveOverallStatus(stepResults) {
    if (!Array.isArray(stepResults) || stepResults.length === 0) {
        return { status: 'failure', symbol: UNKNOWN_SYMBOL };
    }

    let sawPartial = false;
    for (const result of stepResults) {
        if (!isObject(result) || typeof result.status !== 'string') {
            return { status: 'failure', symbol: UNKNOWN_SYMBOL };
        }
        if (result.status === 'failure') return { status: 'failure', symbol: FAILURE_SYMBOL };
        if (result.status === 'partial') sawPartial = true;
        else if (result.status !== 'success') return { status: 'failure', symbol: UNKNOWN_SYMBOL };
    }

    if (sawPartial) return { status: 'partial', symbol: UNKNOWN_SYMBOL };
    return { status: 'success', symbol: SUCCESS_SYMBOL };
}

export default {
    parseErrandPlan,
    deriveOverallStatus,
    SUCCESS_SYMBOL,
    FAILURE_SYMBOL,
    UNKNOWN_SYMBOL,
};

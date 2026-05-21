// Pure movement verification helpers for E6-2 (#557).
//
// This file deliberately has no Mineflayer, Minecraft, bridge, or Node runtime
// dependencies. The Mindcraft action files use these helpers before/after
// issuing movement, and the Python tests can exercise the same outcome math
// without a server.

export const MOVEMENT_CLASSES = Object.freeze([
    'reached',
    'blocked',
    'interrupted',
    'aborted',
    'timed-out',
    'unreachable',
    'invalid',
    'partial',
]);

export const DEFAULT_ARRIVAL_TOLERANCE_BLOCKS = 0.5;
export const DEFAULT_MIN_PROGRESS_BLOCKS = 0.2;

function finiteNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

export function poseFrom(value) {
    if (value === null || value === undefined || typeof value !== 'object') return null;
    const x = finiteNumber(value.x);
    const y = finiteNumber(value.y);
    const z = finiteNumber(value.z);
    if (x === null || y === null || z === null) return null;
    return { x, y, z };
}

export function normalizeTolerance(value, fallback = DEFAULT_ARRIVAL_TOLERANCE_BLOCKS) {
    const n = finiteNumber(value);
    return n !== null && n >= 0 ? n : fallback;
}

export function poseDelta(before, after) {
    const a = poseFrom(before);
    const b = poseFrom(after);
    if (!a || !b) return null;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dz = b.z - a.z;
    return {
        dx,
        dy,
        dz,
        horizontal: Math.hypot(dx, dz),
        distance: Math.hypot(dx, dy, dz),
    };
}

export function distanceBetween(a, b) {
    const pa = poseFrom(a);
    const pb = poseFrom(b);
    if (!pa || !pb) return Number.POSITIVE_INFINITY;
    return Math.hypot(pa.x - pb.x, pa.y - pb.y, pa.z - pb.z);
}

export function withinTolerance(pose, target, tolerance = DEFAULT_ARRIVAL_TOLERANCE_BLOCKS) {
    return distanceBetween(pose, target) <= normalizeTolerance(tolerance);
}

function normalizeYaw(yawRadians) {
    const yaw = finiteNumber(yawRadians);
    return yaw === null ? 0 : yaw;
}

export function directionVector(direction, yawRadians = 0) {
    const d = String(direction || '').toLowerCase();
    const yaw = normalizeYaw(yawRadians);
    const forward = { x: -Math.sin(yaw), y: 0, z: Math.cos(yaw) };
    const right = { x: -Math.cos(yaw), y: 0, z: -Math.sin(yaw) };
    const vectors = {
        north: { x: 0, y: 0, z: -1 },
        south: { x: 0, y: 0, z: 1 },
        east: { x: 1, y: 0, z: 0 },
        west: { x: -1, y: 0, z: 0 },
        up: { x: 0, y: 1, z: 0 },
        down: { x: 0, y: -1, z: 0 },
        forward,
        back: { x: -forward.x, y: 0, z: -forward.z },
        left: { x: -right.x, y: 0, z: -right.z },
        right,
    };
    return vectors[d] || null;
}

export function targetFromMove(before, direction, distanceBlocks, yawRadians = 0) {
    const origin = poseFrom(before);
    const distance = finiteNumber(distanceBlocks);
    const vector = directionVector(direction, yawRadians);
    if (!origin || !vector || distance === null || distance <= 0) return null;
    return {
        x: origin.x + vector.x * distance,
        y: origin.y + vector.y * distance,
        z: origin.z + vector.z * distance,
    };
}

export function classifyMovement({
    before,
    after,
    target,
    tolerance = DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
    failureClass,
    minProgressBlocks = DEFAULT_MIN_PROGRESS_BLOCKS,
} = {}) {
    const b = poseFrom(before);
    const a = poseFrom(after);
    const t = poseFrom(target);
    const tol = normalizeTolerance(tolerance, null);
    if (!b || !a || !t || tol === null) {
        return MOVEMENT_CLASSES.includes(failureClass) ? failureClass : 'invalid';
    }

    if (withinTolerance(a, t, tol)) return 'reached';
    if (MOVEMENT_CLASSES.includes(failureClass)) return failureClass;

    const delta = poseDelta(b, a);
    if (!delta || delta.distance < minProgressBlocks) return 'blocked';
    return 'partial';
}

export function statusForMovementClass(outcomeClass) {
    if (outcomeClass === 'reached') return 'success';
    if (outcomeClass === 'partial') return 'partial';
    return 'failure';
}

export function poseObservation({
    action,
    actionId,
    before,
    after,
    target,
    tolerance = DEFAULT_ARRIVAL_TOLERANCE_BLOCKS,
    outcomeClass,
    requestedDistance,
} = {}) {
    const delta = poseDelta(before, after);
    const finalDistance = distanceBetween(after, target);
    return {
        type: 'pose',
        action,
        action_id: actionId,
        before: poseFrom(before),
        after: poseFrom(after),
        target: poseFrom(target),
        tolerance: normalizeTolerance(tolerance),
        distance: Number.isFinite(finalDistance) ? finalDistance : null,
        requested_distance: finiteNumber(requestedDistance),
        delta,
        class: MOVEMENT_CLASSES.includes(outcomeClass) ? outcomeClass : 'invalid',
    };
}

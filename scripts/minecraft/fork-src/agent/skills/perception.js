// Pure perception snapshot helpers for E6-6 (#561).
//
// This module has no top-level Mineflayer import. It reads pose, nearby blocks,
// entities, and inventory from a passed bot object and returns plain objects
// matching the Python bridge PerceptionSnapshot schema.

import { isAirBlock, normalizeBlockType, positionFrom } from './building.js';
import { distanceBetween, poseFrom as vectorFrom } from './movement.js';

export const PERCEPTION_SCOPES = Object.freeze([
    'pose',
    'nearby_blocks',
    'entities',
    'inventory',
    'all',
]);

export const DEFAULT_RADIUS_BLOCKS = 8;

function finiteNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
}

function nonNegativeInteger(value) {
    const n = finiteNumber(value);
    return n !== null && n >= 0 ? Math.floor(n) : null;
}

function normalizedRadius(value, fallback = DEFAULT_RADIUS_BLOCKS) {
    const n = finiteNumber(value);
    return n !== null && n >= 0 ? n : fallback;
}

function normalizedScope(value) {
    const scope = String(value || 'all').toLowerCase();
    return PERCEPTION_SCOPES.includes(scope) ? scope : 'all';
}

function truthy(value) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') {
        return ['1', 'true', 'yes', 'on'].includes(value.trim().toLowerCase());
    }
    return value === 1;
}

function textOrNull(value) {
    if (value === undefined || value === null) return null;
    const text = String(value).trim();
    return text.length > 0 ? text : null;
}

function dimensionFrom(bot) {
    const raw =
        (bot && bot.game && (bot.game.dimension || bot.game.dimensionName)) ||
        (bot && bot.dimension) ||
        (bot && bot.entity && bot.entity.dimension) ||
        'overworld';
    return normalizeBlockType(raw) || 'overworld';
}

export function poseFrom(bot) {
    const entity = bot && bot.entity ? bot.entity : bot;
    const position = vectorFrom(entity && entity.position) || vectorFrom(bot && bot.position) || {
        x: 0,
        y: 0,
        z: 0,
    };
    return {
        position,
        yaw: finiteNumber(entity && entity.yaw) ?? 0,
        pitch: finiteNumber(entity && entity.pitch) ?? 0,
        on_ground: Boolean(
            (entity && (entity.onGround ?? entity.on_ground)) ??
                (bot && (bot.onGround ?? bot.on_ground)) ??
                false,
        ),
        dimension: dimensionFrom(bot),
    };
}

async function makeVec3(value) {
    const cell = positionFrom(value);
    if (!cell) return value;
    try {
        const mod = await import('vec3');
        const Vec3 = mod && (mod.Vec3 || (mod.default && mod.default.Vec3) || mod.default);
        if (typeof Vec3 === 'function') return new Vec3(cell.x, cell.y, cell.z);
    } catch {
        /* Test and static environments may not have the Mindcraft dependency. */
    }
    return cell;
}

function blockDistance(origin, cell) {
    return Math.hypot(cell.x - origin.x, cell.y - origin.y, cell.z - origin.z);
}

export async function nearbyBlocks(bot, radius = DEFAULT_RADIUS_BLOCKS, includeAir = false) {
    const origin = vectorFrom(bot && bot.entity && bot.entity.position);
    if (!bot || typeof bot.blockAt !== 'function' || !origin) return [];

    const maxRadius = normalizedRadius(radius);
    const maxOffset = Math.ceil(maxRadius);
    const center = {
        x: Math.floor(origin.x),
        y: Math.floor(origin.y),
        z: Math.floor(origin.z),
    };
    const blocks = [];

    for (let dx = -maxOffset; dx <= maxOffset; dx += 1) {
        for (let dy = -maxOffset; dy <= maxOffset; dy += 1) {
            for (let dz = -maxOffset; dz <= maxOffset; dz += 1) {
                const position = {
                    x: center.x + dx,
                    y: center.y + dy,
                    z: center.z + dz,
                };
                if (blockDistance(origin, position) > maxRadius) continue;
                let block;
                try {
                    block = await bot.blockAt(await makeVec3(position));
                } catch {
                    continue;
                }
                const blockType = normalizeBlockType(block);
                if (!blockType) continue;
                if (!includeAir && isAirBlock(blockType)) continue;
                blocks.push({ position, block_type: blockType });
            }
        }
    }

    blocks.sort((a, b) => {
        const da = blockDistance(origin, a.position);
        const db = blockDistance(origin, b.position);
        if (da !== db) return da - db;
        return (
            a.position.x - b.position.x ||
            a.position.y - b.position.y ||
            a.position.z - b.position.z
        );
    });
    return blocks;
}

function entityKind(entity) {
    const raw = String(
        (entity && (entity.kind || entity.type || entity.mobType || entity.objectType)) || '',
    ).toLowerCase();
    if ((entity && entity.username) || raw.includes('player')) return 'player';
    if (raw.includes('item') || (entity && entity.name === 'item')) return 'item';
    if (raw.includes('mob') || (entity && entity.mobType)) return 'mob';
    if (raw === 'object' || raw.includes('object')) return 'object';
    return 'object';
}

function entityName(entity) {
    if (!entity) return null;
    if (entity.username) return textOrNull(entity.username);
    const raw = entity.name ?? entity.displayName ?? entity.mobType ?? entity.objectType;
    return normalizeBlockType(raw) || textOrNull(raw);
}

export function nearbyEntities(bot, radius = DEFAULT_RADIUS_BLOCKS) {
    const origin = vectorFrom(bot && bot.entity && bot.entity.position);
    if (!bot || !bot.entities || !origin) return [];

    const maxRadius = normalizedRadius(radius);
    const entities = Object.values(bot.entities)
        .map((entity, index) => {
            const position = vectorFrom(entity && entity.position);
            if (!entity || !position) return null;
            const distance = distanceBetween(origin, position);
            if (!Number.isFinite(distance) || distance > maxRadius) return null;
            const entityId = textOrNull(
                entity.uuid ?? entity.id ?? entity.username ?? entity.name ?? `entity-${index}`,
            );
            return {
                entity_id: entityId || `entity-${index}`,
                kind: entityKind(entity),
                name: entityName(entity),
                position,
                distance,
            };
        })
        .filter(Boolean);

    entities.sort((a, b) => {
        if (a.distance !== b.distance) return a.distance - b.distance;
        return String(a.entity_id).localeCompare(String(b.entity_id));
    });
    return entities;
}

function inventorySlots(bot) {
    return bot && bot.inventory && Array.isArray(bot.inventory.slots)
        ? bot.inventory.slots
        : [];
}

function rawInventoryItems(bot) {
    const slots = inventorySlots(bot);
    if (bot && bot.inventory && typeof bot.inventory.items === 'function') {
        const items = bot.inventory.items() || [];
        return items.map((item, index) => {
            const slotFromSlots = slots.indexOf(item);
            return {
                item,
                slot:
                    nonNegativeInteger(item && item.slot) ??
                    (slotFromSlots >= 0 ? slotFromSlots : index),
            };
        });
    }
    return slots
        .map((item, slot) => (item ? { item, slot } : null))
        .filter(Boolean);
}

function stackFrom(raw) {
    if (!raw || !raw.item) return null;
    const itemId = normalizeBlockType(raw.item);
    if (!itemId) return null;
    return {
        raw: raw.item,
        slot: nonNegativeInteger(raw.slot) ?? 0,
        item_id: itemId,
        count: nonNegativeInteger(raw.item.count) ?? 1,
    };
}

function matchesInventoryFilter(stack, filter) {
    if (!filter || typeof filter !== 'object') return true;
    const itemId = filter.item_id ? normalizeBlockType(filter.item_id) : null;
    if (itemId && stack.item_id !== itemId) return false;
    const slot = nonNegativeInteger(filter.slot);
    if (slot !== null && stack.slot !== slot) return false;
    if (filter.tag) {
        const wanted = String(filter.tag);
        const tags = Array.isArray(stack.raw && stack.raw.tags) ? stack.raw.tags : [];
        if (!tags.map(String).includes(wanted)) return false;
    }
    return true;
}

function equipmentItem(bot, slotName) {
    const slots = inventorySlots(bot);
    const slotIndexes = {
        head: 5,
        torso: 6,
        legs: 7,
        feet: 8,
        off_hand: 45,
    };
    if (slotName === 'hand') {
        return normalizeBlockType(
            (bot && bot.heldItem) ||
                slots[nonNegativeInteger(bot && bot.quickBarSlot) ?? -1] ||
                null,
        );
    }
    return normalizeBlockType(slots[slotIndexes[slotName]]);
}

export function inventorySnapshot(bot, filter = null, includeEquipment = true) {
    const slots = inventorySlots(bot);
    const stacks = rawInventoryItems(bot)
        .map(stackFrom)
        .filter(Boolean)
        .filter((stack) => matchesInventoryFilter(stack, filter))
        .map((stack) => ({
            slot: stack.slot,
            item_id: stack.item_id,
            count: stack.count,
        }))
        .sort((a, b) => a.slot - b.slot || a.item_id.localeCompare(b.item_id));

    const equipment = includeEquipment
        ? {
              hand: equipmentItem(bot, 'hand') || null,
              off_hand: equipmentItem(bot, 'off_hand') || null,
              head: equipmentItem(bot, 'head') || null,
              torso: equipmentItem(bot, 'torso') || null,
              legs: equipmentItem(bot, 'legs') || null,
              feet: equipmentItem(bot, 'feet') || null,
          }
        : {};

    return {
        items: stacks,
        equipment,
        used_slots: stacks.length,
        total_slots: slots.length,
    };
}

export function perceptionObservation({
    pose,
    blocks,
    entities,
    inventory,
    radius,
    scope,
    includeAir,
    tick,
} = {}) {
    return {
        type: 'perception_snapshot',
        pose: pose || {
            position: { x: 0, y: 0, z: 0 },
            yaw: 0,
            pitch: 0,
            on_ground: false,
            dimension: 'overworld',
        },
        nearby_blocks: Array.isArray(blocks) ? blocks : [],
        entities: Array.isArray(entities) ? entities : [],
        inventory:
            inventory || {
                items: [],
                equipment: {},
                used_slots: 0,
                total_slots: 0,
            },
        radius_blocks: normalizedRadius(radius),
        scope: normalizedScope(scope),
        include_air: truthy(includeAir),
        captured_tick: nonNegativeInteger(tick),
    };
}

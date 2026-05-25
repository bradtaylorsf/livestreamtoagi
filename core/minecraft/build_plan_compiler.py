"""``BuildPlan`` → ``BuildScript`` macro compiler (issue #857).

The compiler is the **deterministic** half of the headless-sim ↔ Minecraft
pipeline: given the same :class:`core.minecraft.build_plan.BuildPlan`,
``origin``, and ``seed`` it always emits a byte-identical
:class:`core.minecraft.build_script.BuildScript`. No LLM, no RNG without an
explicit ``seed`` parameter.

Architectural primitives (floors, walls, roofs, doors, columns, arches)
live in :mod:`core.minecraft.skill_cards.architectural`. Per-structure
recipes (cabin / farm / wall / watchtower / coliseum / market) compose
those primitives in a stable order. The compiler aggregates the resulting
commands, computes the materials manifest, and stamps the script with a
hash of its input plan so downstream consumers can detect plan drift.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from core.agents.build_intent import BuildIntent, SizeClass, StructureType
from core.minecraft.build_plan import BoundingBox, BuildPlan, Level, Position3D, Room
from core.minecraft.build_script import (
    BLOCKS_PER_SECOND,
    COMPILER_VERSION,
    BuildCommand,
    BuildScript,
    BuildScriptManifest,
)
from core.minecraft.skill_cards.architectural import (
    arch_round,
    column_doric,
    door_frame,
    foundation_lay,
    roof_pitched,
    wall_segment,
)

DEFAULT_ORIGIN = Position3D(x=0, y=64, z=0)

# Material region names recognised by the compiler. Cards fall back to the
# first listed material if a region is missing.
_FLOOR_REGION_KEYS = ("floor", "floors", "ground")
_WALL_REGION_KEYS = ("walls", "wall", "exterior")
_ROOF_REGION_KEYS = ("roof", "roofing")
_FRAME_REGION_KEYS = ("frame", "trim", "accent")
_COLUMN_REGION_KEYS = ("columns", "column", "pillars")
_CAPITAL_REGION_KEYS = ("capital", "capitals")


class BuildPlanCompiler:
    """Lower a ``BuildPlan`` into an ordered, deterministic ``BuildScript``."""

    def __init__(
        self,
        *,
        compiler_version: int = COMPILER_VERSION,
        blocks_per_second: int = BLOCKS_PER_SECOND,
    ) -> None:
        self._compiler_version = compiler_version
        self._blocks_per_second = max(1, blocks_per_second)

    @property
    def compiler_version(self) -> int:
        return self._compiler_version

    def compile(
        self,
        plan: BuildPlan,
        *,
        intent: BuildIntent | None = None,
        intent_id: str | None = None,
        origin: Position3D | None = None,
        seed: int = 0,
    ) -> BuildScript:
        """Compile ``plan`` into a deterministic ``BuildScript``.

        Either ``intent`` or ``intent_id`` must be supplied so the
        emitted script is traceable back to a row in
        ``build_intents.jsonl``.
        """
        if intent is None and intent_id is None:
            raise ValueError("compile requires either intent= or intent_id=")
        if intent_id is None and intent is not None:
            intent_id = intent.intent_id

        origin = origin if origin is not None else DEFAULT_ORIGIN
        materials = _materials_lookup(plan)

        recipe = _recipe_for(plan.structure_type)
        commands = recipe(plan=plan, origin=origin, materials=materials, seed=seed)

        manifest = _materials_manifest(commands)
        total_blocks = sum(manifest.values())
        estimated = total_blocks / self._blocks_per_second
        source_hash = _hash_plan(plan, origin=origin, seed=seed)

        return BuildScript(
            intent_id=intent_id,
            structure_type=_structure_enum(plan.structure_type),
            size_class=_size_enum(plan.size_class),
            origin=origin,
            commands=commands,
            materials_manifest=manifest,
            total_blocks=total_blocks,
            estimated_seconds=estimated,
            source_plan_hash=source_hash,
            compiler_version=self._compiler_version,
        )

    def dry_run(
        self,
        plan: BuildPlan,
        *,
        intent: BuildIntent | None = None,
        intent_id: str | None = None,
        origin: Position3D | None = None,
        seed: int = 0,
    ) -> BuildScriptManifest:
        """Return the preflight manifest without holding onto the full command list."""
        script = self.compile(
            plan, intent=intent, intent_id=intent_id, origin=origin, seed=seed
        )
        return BuildScriptManifest(
            intent_id=script.intent_id,
            structure_type=script.structure_type,
            size_class=script.size_class,
            total_blocks=script.total_blocks,
            materials_manifest=script.materials_manifest,
            estimated_seconds=script.estimated_seconds,
        )


# ─── Recipe dispatch ────────────────────────────────────────────────────


def _structure_enum(value: StructureType | str) -> StructureType:
    return value if isinstance(value, StructureType) else StructureType(value)


def _size_enum(value: SizeClass | str) -> SizeClass:
    return value if isinstance(value, SizeClass) else SizeClass(value)


RecipeFn = Callable[..., list[BuildCommand]]


def _recipe_for(structure_type: StructureType | str) -> RecipeFn:
    key = _structure_enum(structure_type)
    return _STRUCTURE_RECIPES.get(key, _recipe_generic)


def _materials_lookup(plan: BuildPlan) -> dict[str, str]:
    """Build a region → material map with a deterministic fallback."""
    table: dict[str, str] = {}
    first_material: str | None = None
    for assignment in plan.materials:
        table.setdefault(assignment.region.lower(), assignment.material)
        if first_material is None:
            first_material = assignment.material
    table.setdefault("__default__", first_material or "stone")
    return table


def _pick(materials: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = materials.get(key.lower())
        if value:
            return value
    return materials["__default__"]


def _floor_y_for_level(plan: BuildPlan, level: Level) -> int:
    # Stack levels so floor_y of level N sits on top of all previous levels.
    offset = 0
    for prior in plan.levels:
        if prior.index >= level.index:
            continue
        offset += max(1, prior.height_blocks)
    return offset


def _sorted_levels(plan: BuildPlan) -> list[Level]:
    return sorted(plan.levels, key=lambda lvl: lvl.index)


def _sorted_rooms(plan: BuildPlan) -> list[Room]:
    return sorted(
        plan.rooms,
        key=lambda room: (room.level_index, room.name),
    )


def _bbox_for_level(plan: BuildPlan) -> BoundingBox:
    return plan.footprint.bbox


def _materials_manifest(commands: list[BuildCommand]) -> dict[str, int]:
    manifest: dict[str, int] = {}
    for command in commands:
        block = command.block_type
        if block is None or block == "air":
            continue
        manifest[block] = manifest.get(block, 0) + command.block_count()
    return dict(sorted(manifest.items()))


def _hash_plan(plan: BuildPlan, *, origin: Position3D, seed: int) -> str:
    payload = json.dumps(
        {
            "plan": plan.model_dump(mode="json"),
            "origin": origin.model_dump(),
            "seed": seed,
            "compiler_version": COMPILER_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─── Generic recipe (used by cabin / generic single-structure builds) ──


def _recipe_generic(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> list[BuildCommand]:
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    floor_material = _pick(materials, _FLOOR_REGION_KEYS)
    wall_material = _pick(materials, _WALL_REGION_KEYS)
    roof_material = _pick(materials, _ROOF_REGION_KEYS)
    frame_material = _pick(materials, _FRAME_REGION_KEYS)

    levels = _sorted_levels(plan)
    for level in levels:
        floor_y = origin.y + _floor_y_for_level(plan, level)
        commands.extend(
            foundation_lay(
                bbox=bbox,
                origin=origin,
                floor_y=floor_y,
                material=level.floor_material or floor_material,
            )
        )
        # Walls rise from one block above the floor up through the level
        # height so the floor slab is visible inside the room.
        commands.extend(
            wall_segment(
                bbox=bbox,
                origin=origin,
                base_y=floor_y + 1,
                height=max(1, level.height_blocks),
                material=wall_material,
            )
        )

        # Interior partitions for any rooms recorded against this level.
        for room in _sorted_rooms(plan):
            if room.level_index != level.index:
                continue
            commands.extend(
                wall_segment(
                    bbox=room.relative_bbox,
                    origin=Position3D(
                        x=origin.x + bbox.x,
                        y=origin.y,
                        z=origin.z + bbox.y,
                    ),
                    base_y=floor_y + 1,
                    height=max(1, level.height_blocks),
                    material=wall_material,
                )
            )

    # Openings (doors / windows) — carve after walls so the air-fill wins.
    for opening in sorted(
        plan.openings, key=lambda o: (o.level_index, o.position.x, o.position.y, o.position.z)
    ):
        opening_position = Position3D(
            x=origin.x + opening.position.x,
            y=origin.y + opening.position.y,
            z=origin.z + opening.position.z,
        )
        commands.extend(
            door_frame(
                position=opening_position,
                kind=opening.kind,
                frame_material=frame_material,
            )
        )

    # Roof on the top level.
    if levels:
        top_level = levels[-1]
        roof_base_y = (
            origin.y
            + _floor_y_for_level(plan, top_level)
            + max(1, top_level.height_blocks)
            + 1
        )
        commands.extend(
            roof_pitched(
                bbox=bbox,
                origin=origin,
                base_y=roof_base_y,
                material=roof_material,
            )
        )

    commands.extend(_emit_key_features(plan, origin=origin, materials=materials))
    return commands


def _emit_key_features(
    plan: BuildPlan,
    *,
    origin: Position3D,
    materials: dict[str, str],
) -> list[BuildCommand]:
    commands: list[BuildCommand] = []
    column_material = _pick(materials, _COLUMN_REGION_KEYS)
    capital_material = materials.get(_CAPITAL_REGION_KEYS[0])
    arch_material = _pick(materials, _WALL_REGION_KEYS)

    for feature in sorted(
        plan.key_features,
        key=lambda f: (f.kind, f.position.x, f.position.y, f.position.z),
    ):
        base = Position3D(
            x=origin.x + feature.position.x,
            y=origin.y + feature.position.y,
            z=origin.z + feature.position.z,
        )
        size = feature.size or {}
        if feature.kind == "column":
            commands.extend(
                column_doric(
                    position=base,
                    height=max(1, int(size.get("height", 3))),
                    material=column_material,
                    capital_material=capital_material,
                )
            )
        elif feature.kind == "arch":
            commands.extend(
                arch_round(
                    position=base,
                    span=max(2, int(size.get("span", 4))),
                    height=max(1, int(size.get("height", 4))),
                    material=arch_material,
                )
            )
        # roof / ornament / other key features have no extra primitive; the
        # main roof recipe already covers the structural roof.
    return commands


# ─── Per-structure recipes ─────────────────────────────────────────────


def _recipe_cabin(**kwargs) -> list[BuildCommand]:
    return _recipe_generic(**kwargs)


def _recipe_farm(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> list[BuildCommand]:
    # A farm is a low fence ringing a tilled field. We model it as a thin
    # perimeter wall (the fence) + a floor slab (the field).
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    field_material = _pick(materials, ("field", "soil", "tilled") + _FLOOR_REGION_KEYS)
    fence_material = _pick(materials, ("fence",) + _WALL_REGION_KEYS)

    floor_y = origin.y
    commands.extend(
        foundation_lay(
            bbox=bbox, origin=origin, floor_y=floor_y, material=field_material
        )
    )
    commands.extend(
        wall_segment(
            bbox=bbox,
            origin=origin,
            base_y=floor_y + 1,
            height=1,
            material=fence_material,
        )
    )
    commands.extend(_emit_key_features(plan, origin=origin, materials=materials))
    return commands


def _recipe_wall(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> list[BuildCommand]:
    # A defensive wall: a tall perimeter rectangle, no roof.
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    wall_material = _pick(materials, _WALL_REGION_KEYS)
    levels = _sorted_levels(plan)
    height = sum(max(1, lvl.height_blocks) for lvl in levels) or 4

    commands.extend(
        wall_segment(
            bbox=bbox,
            origin=origin,
            base_y=origin.y,
            height=height,
            material=wall_material,
        )
    )
    commands.extend(_emit_key_features(plan, origin=origin, materials=materials))
    return commands


def _recipe_watchtower(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> list[BuildCommand]:
    # Tall and narrow — generic recipe handles stacked levels + roof; we
    # just delegate to it so the per-level walls fire.
    return _recipe_generic(plan=plan, origin=origin, materials=materials, seed=seed)


def _recipe_coliseum(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> list[BuildCommand]:
    # Outer wall + tiered seating modelled as concentric perimeters
    # shrinking inward, plus columns/arches from key_features.
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    floor_material = _pick(materials, _FLOOR_REGION_KEYS)
    wall_material = _pick(materials, _WALL_REGION_KEYS)

    floor_y = origin.y
    # Sand floor of the arena.
    commands.extend(
        foundation_lay(
            bbox=bbox, origin=origin, floor_y=floor_y, material=floor_material
        )
    )

    # Tiered seating rings.
    tiers = max(1, min(8, min(bbox.w, bbox.h) // 4))
    for tier in range(tiers):
        inset = tier
        tier_bbox = BoundingBox(
            x=bbox.x + inset,
            y=bbox.y + inset,
            w=max(1, bbox.w - 2 * inset),
            h=max(1, bbox.h - 2 * inset),
        )
        if tier_bbox.w < 2 or tier_bbox.h < 2:
            break
        commands.extend(
            wall_segment(
                bbox=tier_bbox,
                origin=origin,
                base_y=floor_y + 1 + tier,
                height=2,
                material=wall_material,
            )
        )

    # Interior rooms (gladiator quarters, etc.).
    for room in _sorted_rooms(plan):
        commands.extend(
            wall_segment(
                bbox=room.relative_bbox,
                origin=Position3D(
                    x=origin.x + bbox.x,
                    y=origin.y,
                    z=origin.z + bbox.y,
                ),
                base_y=floor_y + 1,
                height=3,
                material=wall_material,
            )
        )

    commands.extend(_emit_key_features(plan, origin=origin, materials=materials))
    return commands


def _recipe_market(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> list[BuildCommand]:
    # Open plaza ringed by stalls. We treat each ``rooms`` entry as a stall
    # bounded by short walls. Falls back to a generic single-building if
    # no rooms were decomposed.
    if not plan.rooms:
        return _recipe_generic(
            plan=plan, origin=origin, materials=materials, seed=seed
        )

    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    plaza_material = _pick(materials, ("plaza", "pavers") + _FLOOR_REGION_KEYS)
    stall_material = _pick(materials, ("stall",) + _WALL_REGION_KEYS)
    floor_y = origin.y

    commands.extend(
        foundation_lay(
            bbox=bbox, origin=origin, floor_y=floor_y, material=plaza_material
        )
    )

    for room in _sorted_rooms(plan):
        commands.extend(
            wall_segment(
                bbox=room.relative_bbox,
                origin=Position3D(
                    x=origin.x + bbox.x,
                    y=origin.y,
                    z=origin.z + bbox.y,
                ),
                base_y=floor_y + 1,
                height=2,
                material=stall_material,
            )
        )

    commands.extend(_emit_key_features(plan, origin=origin, materials=materials))
    return commands


_STRUCTURE_RECIPES: dict[StructureType, RecipeFn] = {
    StructureType.cabin: _recipe_cabin,
    StructureType.farm: _recipe_farm,
    StructureType.wall: _recipe_wall,
    StructureType.watchtower: _recipe_watchtower,
    StructureType.coliseum: _recipe_coliseum,
    StructureType.market: _recipe_market,
}


__all__ = [
    "DEFAULT_ORIGIN",
    "BuildPlanCompiler",
]

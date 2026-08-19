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
import math
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
_BASE_REGION_KEYS = ("base", "plinth", "foundation")
_SEAT_REGION_KEYS = ("seats", "seat", "stairs", "seating")
_BAND_REGION_KEYS = ("band", "bands", "frieze", "decorative")
_SLAB_REGION_KEYS = ("slabs", "slab", "ledge", "ledges")
_LIGHTING_REGION_KEYS = ("lighting", "lanterns", "lantern")


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
        commands, invoked_cards = recipe(plan=plan, origin=origin, materials=materials, seed=seed)

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
            skill_cards_invoked=list(dict.fromkeys(invoked_cards)),
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
        script = self.compile(plan, intent=intent, intent_id=intent_id, origin=origin, seed=seed)
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


RecipeFn = Callable[..., tuple[list[BuildCommand], list[str]]]


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


def _centered_bbox(container: BoundingBox, *, w: int, h: int) -> BoundingBox:
    """Return a bbox centered inside ``container`` and clamped to fit."""
    width = max(1, min(w, container.w))
    depth = max(1, min(h, container.h))
    return BoundingBox(
        x=container.x + max(0, (container.w - width) // 2),
        y=container.y + max(0, (container.h - depth) // 2),
        w=width,
        h=depth,
    )


def _inset_bbox(bbox: BoundingBox, inset: int) -> BoundingBox:
    clamped = max(0, inset)
    return BoundingBox(
        x=bbox.x + clamped,
        y=bbox.y + clamped,
        w=max(1, bbox.w - 2 * clamped),
        h=max(1, bbox.h - 2 * clamped),
    )


def _ellipse_span_at_z(bbox: BoundingBox, z: int) -> tuple[int, int] | None:
    """Return inclusive relative x-span for an ellipse row at relative z."""
    if z < bbox.y or z >= bbox.y + bbox.h:
        return None
    if bbox.w <= 1 or bbox.h <= 1:
        return (bbox.x, bbox.x)
    rx = bbox.w / 2.0
    rz = bbox.h / 2.0
    cx = bbox.x + (bbox.w - 1) / 2.0
    cz = bbox.y + (bbox.h - 1) / 2.0
    normalized_z = (z - cz) / rz if rz else 0.0
    inside = 1.0 - normalized_z * normalized_z
    if inside < 0:
        return None
    half_width = rx * math.sqrt(max(0.0, inside))
    return (math.ceil(cx - half_width), math.floor(cx + half_width))


def _ellipse_disk(
    *,
    bbox: BoundingBox,
    origin: Position3D,
    base_y: int,
    height: int,
    material: str,
) -> list[BuildCommand]:
    commands: list[BuildCommand] = []
    if height <= 0:
        return commands
    top_y = base_y + height - 1
    for z in range(bbox.y, bbox.y + bbox.h):
        span = _ellipse_span_at_z(bbox, z)
        if span is None:
            continue
        x0, x1 = span
        commands.append(
            BuildCommand(
                kind="fill",
                position=Position3D(x=origin.x + x0, y=base_y, z=origin.z + z),
                region_to=Position3D(x=origin.x + x1, y=top_y, z=origin.z + z),
                block_type=material,
            )
        )
    return commands


def _ellipse_ring(
    *,
    outer: BoundingBox,
    inner: BoundingBox,
    origin: Position3D,
    base_y: int,
    height: int,
    material: str,
) -> list[BuildCommand]:
    """Build an oval ring by subtracting the inner ellipse row span."""
    commands: list[BuildCommand] = []
    if height <= 0:
        return commands
    top_y = base_y + height - 1
    for z in range(outer.y, outer.y + outer.h):
        outer_span = _ellipse_span_at_z(outer, z)
        if outer_span is None:
            continue
        inner_span = _ellipse_span_at_z(inner, z)
        segments: list[tuple[int, int]]
        if inner_span is None:
            segments = [outer_span]
        else:
            ox0, ox1 = outer_span
            ix0, ix1 = inner_span
            segments = []
            if ox0 <= ix0 - 1:
                segments.append((ox0, ix0 - 1))
            if ix1 + 1 <= ox1:
                segments.append((ix1 + 1, ox1))
        for x0, x1 in segments:
            commands.append(
                BuildCommand(
                    kind="fill",
                    position=Position3D(x=origin.x + x0, y=base_y, z=origin.z + z),
                    region_to=Position3D(x=origin.x + x1, y=top_y, z=origin.z + z),
                    block_type=material,
                )
            )
    return commands


def _air_fill(
    commands: list[BuildCommand],
    *,
    origin: Position3D,
    x0: int,
    y0: int,
    z0: int,
    x1: int,
    y1: int,
    z1: int,
) -> None:
    commands.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=origin.x + min(x0, x1), y=min(y0, y1), z=origin.z + min(z0, z1)),
            region_to=Position3D(
                x=origin.x + max(x0, x1),
                y=max(y0, y1),
                z=origin.z + max(z0, z1),
            ),
            block_type="air",
        )
    )


def _material_fill(
    commands: list[BuildCommand],
    *,
    origin: Position3D,
    x0: int,
    y0: int,
    z0: int,
    x1: int,
    y1: int,
    z1: int,
    material: str,
) -> None:
    commands.append(
        BuildCommand(
            kind="fill",
            position=Position3D(x=origin.x + min(x0, x1), y=min(y0, y1), z=origin.z + min(z0, z1)),
            region_to=Position3D(
                x=origin.x + max(x0, x1),
                y=max(y0, y1),
                z=origin.z + max(z0, z1),
            ),
            block_type=material,
        )
    )


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
) -> tuple[list[BuildCommand], list[str]]:
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    floor_material = _pick(materials, _FLOOR_REGION_KEYS)
    wall_material = _pick(materials, _WALL_REGION_KEYS)
    roof_material = _pick(materials, _ROOF_REGION_KEYS)
    frame_material = _pick(materials, _FRAME_REGION_KEYS)

    levels = _sorted_levels(plan)

    # 1. Floors for every level.
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

    # 2. Roof above the top level. Emitted before walls so wall fills are
    #    the last writes on the perimeter, letting openings (step 4) carve
    #    air last without a wall re-fill resealing the doorway.
    if levels:
        top_level = levels[-1]
        roof_base_y = (
            origin.y + _floor_y_for_level(plan, top_level) + max(1, top_level.height_blocks) + 1
        )
        commands.extend(
            roof_pitched(
                bbox=bbox,
                origin=origin,
                base_y=roof_base_y,
                material=roof_material,
            )
        )

    # 3. Walls (hollow outline via wall_segment's four-side perimeter fills)
    #    and interior room partitions. Every level gets its own ring so
    #    upper floors are not left floating above the level below.
    top_wall_y = origin.y
    for level in levels:
        floor_y = origin.y + _floor_y_for_level(plan, level)
        base_y = floor_y + 1
        height = max(1, level.height_blocks)
        commands.extend(
            wall_segment(
                bbox=bbox,
                origin=origin,
                base_y=base_y,
                height=height,
                material=wall_material,
            )
        )
        top_wall_y = base_y + height - 1
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
                    base_y=base_y,
                    height=height,
                    material=wall_material,
                )
            )

    # 3b. Cap strip: today the per-level walls always butt up against
    #     `roof_base_y - 1` because the roof and wall math share the same
    #     accumulated offset. Guard against future drift (e.g. a recipe
    #     that picks a custom roof base) by filling any residual gap with
    #     the walls material so upper floors never end up floating below
    #     a roof.
    if levels:
        gap_start = top_wall_y + 1
        gap_end = roof_base_y - 1
        if gap_start <= gap_end:
            commands.extend(
                wall_segment(
                    bbox=bbox,
                    origin=origin,
                    base_y=gap_start,
                    height=gap_end - gap_start + 1,
                    material=wall_material,
                )
            )

    # 4. Openings (doors / windows) — carve AFTER walls so the air-fill wins.
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

    # 5. Ornamentation last so nothing overwrites the carved openings.
    extra_cmds, extra_invoked = _emit_key_features(plan, origin=origin, materials=materials)
    commands.extend(extra_cmds)
    return commands, extra_invoked


def _emit_key_features(
    plan: BuildPlan,
    *,
    origin: Position3D,
    materials: dict[str, str],
) -> tuple[list[BuildCommand], list[str]]:
    commands: list[BuildCommand] = []
    invoked: list[str] = []
    column_material = _pick(materials, _COLUMN_REGION_KEYS)
    capital_material = materials.get(_CAPITAL_REGION_KEYS[0])
    arch_material = _pick(materials, _WALL_REGION_KEYS)
    roof_material = _pick(materials, _ROOF_REGION_KEYS)
    trim_material = _pick(materials, _FRAME_REGION_KEYS)

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
            invoked.append("column_doric")
        elif feature.kind == "arch":
            commands.extend(
                arch_round(
                    position=base,
                    span=max(2, int(size.get("span", 4))),
                    height=max(1, int(size.get("height", 4))),
                    material=arch_material,
                )
            )
            invoked.append("arch_round")
        elif feature.kind == "roof":
            w = max(1, int(size.get("w", size.get("span", 3))))
            d = max(1, int(size.get("d", size.get("depth", 3))))
            commands.extend(
                roof_pitched(
                    bbox=BoundingBox(x=0, y=0, w=w, h=d),
                    origin=base,
                    base_y=base.y,
                    material=roof_material,
                )
            )
            invoked.append("roof_pitched")
        else:  # "ornament" or "other" — single-row trim ring
            w = max(1, int(size.get("w", size.get("span", 1))))
            d = max(1, int(size.get("d", size.get("depth", 1))))
            commands.extend(
                wall_segment(
                    bbox=BoundingBox(x=0, y=0, w=w, h=d),
                    origin=base,
                    base_y=base.y,
                    height=1,
                    material=trim_material,
                )
            )
            invoked.append("wall_segment")
    return commands, invoked


# ─── Per-structure recipes ─────────────────────────────────────────────


def _recipe_cabin(**kwargs) -> tuple[list[BuildCommand], list[str]]:
    return _recipe_generic(**kwargs)


def _recipe_farm(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> tuple[list[BuildCommand], list[str]]:
    # A farm is a low fence ringing a tilled field. We model it as a thin
    # perimeter wall (the fence) + a floor slab (the field).
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    field_material = _pick(materials, ("field", "soil", "tilled") + _FLOOR_REGION_KEYS)
    fence_material = _pick(materials, ("fence",) + _WALL_REGION_KEYS)

    floor_y = origin.y
    commands.extend(
        foundation_lay(bbox=bbox, origin=origin, floor_y=floor_y, material=field_material)
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
    extra_cmds, invoked = _emit_key_features(plan, origin=origin, materials=materials)
    commands.extend(extra_cmds)
    return commands, invoked


def _recipe_wall(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> tuple[list[BuildCommand], list[str]]:
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
    extra_cmds, invoked = _emit_key_features(plan, origin=origin, materials=materials)
    commands.extend(extra_cmds)
    return commands, invoked


def _recipe_watchtower(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> tuple[list[BuildCommand], list[str]]:
    # Tall and narrow — the generic recipe emits a wall ring for every
    # level plus a cap strip up to the roof base, so upper floors never
    # float above the level below.
    return _recipe_generic(plan=plan, origin=origin, materials=materials, seed=seed)


def _recipe_coliseum(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> tuple[list[BuildCommand], list[str]]:
    # Roman Colosseum blueprint recipe: a full-scale oval amphitheater
    # with 120 x 100 footprint, 42-block height, four arcade tiers,
    # a solid attic wall, 56 x 36 arena floor, four main gates, and
    # tiered seating rows. Smaller test plans use the same proportions.
    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    arena_material = materials.get("arena") or _pick(materials, _FLOOR_REGION_KEYS)
    base_material = _pick(materials, _BASE_REGION_KEYS + _WALL_REGION_KEYS)
    wall_material = _pick(materials, _WALL_REGION_KEYS)
    seat_material = _pick(materials, _SEAT_REGION_KEYS + _FLOOR_REGION_KEYS)
    band_material = _pick(materials, _BAND_REGION_KEYS + _WALL_REGION_KEYS)
    trim_material = _pick(materials, _FRAME_REGION_KEYS + _SLAB_REGION_KEYS)
    lighting_material = _pick(materials, _LIGHTING_REGION_KEYS + _FRAME_REGION_KEYS)

    large_blueprint_scale = bbox.w >= 80 and bbox.h >= 60
    base_height = 6 if large_blueprint_scale else max(2, min(bbox.w, bbox.h) // 8)
    tier_heights = _coliseum_tier_heights(plan, large_blueprint_scale=large_blueprint_scale)
    arch_tier_heights = tier_heights[:4]
    attic_height = tier_heights[4]
    arch_opening_height = 7 if large_blueprint_scale else max(2, min(tier_heights[0], 4))
    wall_thickness = 5 if large_blueprint_scale else max(1, min(bbox.w, bbox.h) // 8)

    floor_y = origin.y
    wall_base_y = floor_y + base_height
    wall_top_y = wall_base_y + sum(arch_tier_heights) + attic_height - 1

    shell_inner = _inset_bbox(bbox, wall_thickness)
    arena_bbox = (
        _centered_bbox(bbox, w=56, h=36)
        if large_blueprint_scale
        else _centered_bbox(bbox, w=max(4, bbox.w // 2), h=max(4, bbox.h // 2))
    )

    # Arena floor plus the footprint plinth.
    commands.extend(
        _ellipse_disk(
            bbox=arena_bbox,
            origin=origin,
            base_y=floor_y,
            height=1,
            material=arena_material,
        )
    )
    commands.extend(
        _ellipse_ring(
            outer=bbox,
            inner=arena_bbox,
            origin=origin,
            base_y=floor_y,
            height=base_height,
            material=base_material,
        )
    )

    # Outer amphitheater shell, then horizontal decorative bands at each tier.
    commands.extend(
        _ellipse_ring(
            outer=bbox,
            inner=shell_inner,
            origin=origin,
            base_y=wall_base_y,
            height=wall_top_y - wall_base_y + 1,
            material=wall_material,
        )
    )

    band_y = wall_base_y
    for height in arch_tier_heights:
        band_y += height
        commands.extend(
            _ellipse_ring(
                outer=bbox,
                inner=shell_inner,
                origin=origin,
                base_y=band_y - 1,
                height=1,
                material=band_material,
            )
        )
    commands.extend(
        _ellipse_ring(
            outer=bbox,
            inner=shell_inner,
            origin=origin,
            base_y=wall_top_y,
            height=1,
            material=trim_material,
        )
    )

    _carve_coliseum_arches(
        commands,
        bbox=bbox,
        origin=origin,
        base_y=wall_base_y,
        tier_heights=arch_tier_heights,
        wall_thickness=wall_thickness,
        opening_height=arch_opening_height,
        opening_width=5 if large_blueprint_scale else max(2, bbox.w // 8),
        spacing=8 if large_blueprint_scale else max(4, bbox.w // 6),
    )
    _carve_coliseum_gates(
        commands,
        bbox=bbox,
        origin=origin,
        floor_y=floor_y,
        wall_thickness=wall_thickness,
        gate_width=10 if large_blueprint_scale else max(3, min(bbox.w, bbox.h) // 5),
        gate_height=12 if large_blueprint_scale else base_height + arch_opening_height,
    )

    # Twenty-four seating rows in four tiers around the central arena.
    seat_rows = 24 if large_blueprint_scale else max(4, min(bbox.w, bbox.h) // 2)
    max_available_rows = max(
        1,
        min(
            (arena_bbox.x - bbox.x) - wall_thickness,
            (arena_bbox.y - bbox.y) - wall_thickness,
        ),
    )
    seat_rows = min(seat_rows, max_available_rows)
    for row in range(seat_rows):
        outer = BoundingBox(
            x=arena_bbox.x - row - 1,
            y=arena_bbox.y - row - 1,
            w=arena_bbox.w + 2 * (row + 1),
            h=arena_bbox.h + 2 * (row + 1),
        )
        inner = BoundingBox(
            x=arena_bbox.x - row,
            y=arena_bbox.y - row,
            w=arena_bbox.w + 2 * row,
            h=arena_bbox.h + 2 * row,
        )
        commands.extend(
            _ellipse_ring(
                outer=outer,
                inner=inner,
                origin=origin,
                base_y=floor_y + 1 + row,
                height=1,
                material=seat_material,
            )
        )

    _add_coliseum_lanterns(
        commands,
        bbox=bbox,
        origin=origin,
        floor_y=floor_y,
        material=lighting_material,
    )

    extra_cmds, invoked = _emit_key_features(plan, origin=origin, materials=materials)
    commands.extend(extra_cmds)
    return commands, [
        "ellipse_disk",
        "ellipse_ring",
        "coliseum_arcade",
        "coliseum_gates",
        "coliseum_seating",
        *invoked,
    ]


def _coliseum_tier_heights(
    plan: BuildPlan,
    *,
    large_blueprint_scale: bool,
) -> list[int]:
    levels = [max(1, lvl.height_blocks) for lvl in _sorted_levels(plan)]
    if len(levels) >= 5:
        return levels[:5]
    return [8, 8, 8, 6, 6] if large_blueprint_scale else [2, 2, 2, 2, 2]


def _carve_coliseum_arches(
    commands: list[BuildCommand],
    *,
    bbox: BoundingBox,
    origin: Position3D,
    base_y: int,
    tier_heights: list[int],
    wall_thickness: int,
    opening_height: int,
    opening_width: int,
    spacing: int,
) -> None:
    x0 = bbox.x
    x1 = bbox.x + bbox.w - 1
    z0 = bbox.y
    z1 = bbox.y + bbox.h - 1
    spacing = max(opening_width + 1, spacing)

    level_y = base_y
    for tier_height in tier_heights:
        open_y0 = level_y + 1
        open_y1 = min(level_y + tier_height - 1, open_y0 + opening_height - 1)

        for x in range(x0 + spacing, x1 - spacing, spacing):
            arch_x1 = min(x + opening_width - 1, x1 - wall_thickness - 1)
            if arch_x1 <= x:
                continue
            _air_fill(
                commands,
                origin=origin,
                x0=x,
                y0=open_y0,
                z0=z0,
                x1=arch_x1,
                y1=open_y1,
                z1=z0 + wall_thickness - 1,
            )
            _air_fill(
                commands,
                origin=origin,
                x0=x,
                y0=open_y0,
                z0=z1 - wall_thickness + 1,
                x1=arch_x1,
                y1=open_y1,
                z1=z1,
            )

        for z in range(z0 + spacing, z1 - spacing, spacing):
            arch_z1 = min(z + opening_width - 1, z1 - wall_thickness - 1)
            if arch_z1 <= z:
                continue
            _air_fill(
                commands,
                origin=origin,
                x0=x0,
                y0=open_y0,
                z0=z,
                x1=x0 + wall_thickness - 1,
                y1=open_y1,
                z1=arch_z1,
            )
            _air_fill(
                commands,
                origin=origin,
                x0=x1 - wall_thickness + 1,
                y0=open_y0,
                z0=z,
                x1=x1,
                y1=open_y1,
                z1=arch_z1,
            )
        level_y += tier_height


def _carve_coliseum_gates(
    commands: list[BuildCommand],
    *,
    bbox: BoundingBox,
    origin: Position3D,
    floor_y: int,
    wall_thickness: int,
    gate_width: int,
    gate_height: int,
) -> None:
    x0 = bbox.x
    x1 = bbox.x + bbox.w - 1
    z0 = bbox.y
    z1 = bbox.y + bbox.h - 1
    cx = (x0 + x1) // 2
    cz = (z0 + z1) // 2
    half = max(1, gate_width // 2)
    y1 = floor_y + gate_height - 1

    _air_fill(
        commands,
        origin=origin,
        x0=cx - half,
        y0=floor_y,
        z0=z0,
        x1=cx + half,
        y1=y1,
        z1=z0 + wall_thickness - 1,
    )
    _air_fill(
        commands,
        origin=origin,
        x0=cx - half,
        y0=floor_y,
        z0=z1 - wall_thickness + 1,
        x1=cx + half,
        y1=y1,
        z1=z1,
    )
    _air_fill(
        commands,
        origin=origin,
        x0=x0,
        y0=floor_y,
        z0=cz - half,
        x1=x0 + wall_thickness - 1,
        y1=y1,
        z1=cz + half,
    )
    _air_fill(
        commands,
        origin=origin,
        x0=x1 - wall_thickness + 1,
        y0=floor_y,
        z0=cz - half,
        x1=x1,
        y1=y1,
        z1=cz + half,
    )


def _add_coliseum_lanterns(
    commands: list[BuildCommand],
    *,
    bbox: BoundingBox,
    origin: Position3D,
    floor_y: int,
    material: str,
) -> None:
    x0 = bbox.x
    x1 = bbox.x + bbox.w - 1
    z0 = bbox.y
    z1 = bbox.y + bbox.h - 1
    cx = (x0 + x1) // 2
    cz = (z0 + z1) // 2
    y = floor_y + 1
    for x, z in (
        (cx, z0 + 2),
        (cx, z1 - 2),
        (x0 + 2, cz),
        (x1 - 2, cz),
    ):
        _material_fill(
            commands,
            origin=origin,
            x0=x,
            y0=y,
            z0=z,
            x1=x,
            y1=y,
            z1=z,
            material=material,
        )


def _recipe_market(
    *,
    plan: BuildPlan,
    origin: Position3D,
    materials: dict[str, str],
    seed: int,
) -> tuple[list[BuildCommand], list[str]]:
    # Open plaza ringed by stalls. We treat each ``rooms`` entry as a stall
    # bounded by short walls. Falls back to a generic single-building if
    # no rooms were decomposed.
    if not plan.rooms:
        return _recipe_generic(plan=plan, origin=origin, materials=materials, seed=seed)

    commands: list[BuildCommand] = []
    bbox = _bbox_for_level(plan)
    plaza_material = _pick(materials, ("plaza", "pavers") + _FLOOR_REGION_KEYS)
    stall_material = _pick(materials, ("stall",) + _WALL_REGION_KEYS)
    floor_y = origin.y

    commands.extend(
        foundation_lay(bbox=bbox, origin=origin, floor_y=floor_y, material=plaza_material)
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

    extra_cmds, invoked = _emit_key_features(plan, origin=origin, materials=materials)
    commands.extend(extra_cmds)
    return commands, invoked


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

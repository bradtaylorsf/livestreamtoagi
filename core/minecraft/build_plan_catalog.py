"""Static catalog of ``BuildPlan``s keyed by ``StructureType`` (issue #888).

When ``propose_build`` fires in headless mode the executor only writes a
``BuildScript`` if a ``build_plan_compiler`` *and* a ``build_plan_resolver``
are attached. The cloud-backed decomposer (``GeminiVisionDecomposer``)
requires network credentials and is too slow to take inside a smoke run,
so the headless smoke needs a deterministic, offline resolver that maps
``intent_args['structure_type']`` to a pre-authored ``BuildPlan``.

This module provides that resolver. The catalog covers every value in
:class:`core.agents.build_intent.StructureType` — additional informal
labels (``storage_hall``, ``market_stall``, ``town_square`` mentioned in
the issue body) are not in the validated enum and therefore have no
catalog entry; ``propose_build`` would reject them upstream anyway.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.agents.build_intent import StructureType
from core.minecraft.build_plan import (
    BoundingBox,
    BuildPlan,
    Footprint,
    KeyFeature,
    Level,
    MaterialAssignment,
    Opening,
    Position3D,
    Room,
)

_PROVIDER_MODEL_ID = "static_catalog"
_DECOMPOSER_VERSION = 1


def _cabin_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="cabin",
        size_class="medium",
        source_image_id="catalog:cabin",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=7, h=6)),
        levels=[Level(index=0, height_blocks=3, floor_material="oak_planks")],
        materials=[
            MaterialAssignment(region="floor", material="oak_planks"),
            MaterialAssignment(region="walls", material="oak_log"),
            MaterialAssignment(region="roof", material="dark_oak_planks"),
            MaterialAssignment(region="frame", material="oak_log"),
        ],
        openings=[
            Opening(kind="door", position=Position3D(x=3, y=0, z=0), level_index=0),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _farm_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="farm",
        size_class="medium",
        source_image_id="catalog:farm",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=8, h=6)),
        levels=[Level(index=0, height_blocks=1, floor_material="farmland")],
        materials=[
            MaterialAssignment(region="field", material="farmland"),
            MaterialAssignment(region="fence", material="oak_fence"),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _wall_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="wall",
        size_class="large",
        source_image_id="catalog:wall",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=12, h=8)),
        levels=[Level(index=0, height_blocks=5, floor_material="stone")],
        materials=[MaterialAssignment(region="walls", material="stone_bricks")],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _watchtower_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="watchtower",
        size_class="medium",
        source_image_id="catalog:watchtower",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=5, h=5)),
        levels=[
            Level(index=0, height_blocks=3, floor_material="stone_bricks"),
            Level(index=1, height_blocks=3, floor_material="stone_bricks"),
            Level(index=2, height_blocks=3, floor_material="stone_bricks"),
        ],
        materials=[
            MaterialAssignment(region="floor", material="stone_bricks"),
            MaterialAssignment(region="walls", material="cobblestone"),
            MaterialAssignment(region="roof", material="dark_oak_planks"),
        ],
        openings=[
            Opening(kind="door", position=Position3D(x=2, y=0, z=0), level_index=0),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _well_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="well",
        size_class="small",
        source_image_id="catalog:well",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=3, h=3)),
        levels=[Level(index=0, height_blocks=2, floor_material="cobblestone")],
        materials=[
            MaterialAssignment(region="floor", material="water"),
            MaterialAssignment(region="walls", material="cobblestone"),
            MaterialAssignment(region="roof", material="oak_planks"),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _coliseum_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="coliseum",
        size_class="epic",
        source_image_id="catalog:coliseum",
        footprint=Footprint(shape="oval", bbox=BoundingBox(x=0, y=0, w=24, h=20)),
        levels=[Level(index=0, height_blocks=8, floor_material="sand")],
        rooms=[
            Room(name="gladiator", level_index=0, relative_bbox=BoundingBox(x=2, y=2, w=4, h=3)),
            Room(name="entry", level_index=0, relative_bbox=BoundingBox(x=18, y=2, w=4, h=3)),
        ],
        materials=[
            MaterialAssignment(region="floor", material="sand"),
            MaterialAssignment(region="walls", material="stone_bricks"),
            MaterialAssignment(region="columns", material="quartz_pillar"),
        ],
        key_features=[
            KeyFeature(kind="column", position=Position3D(x=2, y=0, z=2), size={"height": 6}),
            KeyFeature(kind="column", position=Position3D(x=20, y=0, z=2), size={"height": 6}),
            KeyFeature(
                kind="arch",
                position=Position3D(x=10, y=0, z=0),
                size={"span": 4, "height": 4},
            ),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _market_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="market",
        size_class="large",
        source_image_id="catalog:market",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=14, h=14)),
        levels=[Level(index=0, height_blocks=3, floor_material="stone_bricks")],
        rooms=[
            Room(name="stall_n", level_index=0, relative_bbox=BoundingBox(x=2, y=0, w=3, h=2)),
            Room(name="stall_s", level_index=0, relative_bbox=BoundingBox(x=9, y=12, w=3, h=2)),
            Room(name="stall_e", level_index=0, relative_bbox=BoundingBox(x=12, y=6, w=2, h=3)),
        ],
        materials=[
            MaterialAssignment(region="plaza", material="stone_bricks"),
            MaterialAssignment(region="stall", material="oak_planks"),
            MaterialAssignment(region="walls", material="oak_planks"),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _temple_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="temple",
        size_class="large",
        source_image_id="catalog:temple",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=10, h=10)),
        levels=[Level(index=0, height_blocks=6, floor_material="polished_andesite")],
        materials=[
            MaterialAssignment(region="floor", material="polished_andesite"),
            MaterialAssignment(region="walls", material="stone_bricks"),
            MaterialAssignment(region="roof", material="dark_oak_planks"),
            MaterialAssignment(region="columns", material="quartz_pillar"),
        ],
        key_features=[
            KeyFeature(kind="column", position=Position3D(x=1, y=0, z=1), size={"height": 5}),
            KeyFeature(kind="column", position=Position3D(x=8, y=0, z=1), size={"height": 5}),
            KeyFeature(kind="column", position=Position3D(x=1, y=0, z=8), size={"height": 5}),
            KeyFeature(kind="column", position=Position3D(x=8, y=0, z=8), size={"height": 5}),
        ],
        openings=[
            Opening(kind="door", position=Position3D(x=4, y=0, z=0), level_index=0),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


def _mineshaft_plan() -> BuildPlan:
    return BuildPlan(
        structure_type="mineshaft",
        size_class="medium",
        source_image_id="catalog:mineshaft",
        footprint=Footprint(shape="rectangle", bbox=BoundingBox(x=0, y=0, w=4, h=4)),
        levels=[Level(index=0, height_blocks=3, floor_material="cobblestone")],
        materials=[
            MaterialAssignment(region="floor", material="cobblestone"),
            MaterialAssignment(region="walls", material="oak_log"),
            MaterialAssignment(region="roof", material="oak_planks"),
        ],
        openings=[
            Opening(kind="door", position=Position3D(x=1, y=0, z=0), level_index=0),
        ],
        decomposer_version=_DECOMPOSER_VERSION,
        provider_model_id=_PROVIDER_MODEL_ID,
    )


_CATALOG: dict[StructureType, Callable[[], BuildPlan]] = {
    StructureType.cabin: _cabin_plan,
    StructureType.farm: _farm_plan,
    StructureType.wall: _wall_plan,
    StructureType.watchtower: _watchtower_plan,
    StructureType.well: _well_plan,
    StructureType.coliseum: _coliseum_plan,
    StructureType.market: _market_plan,
    StructureType.temple: _temple_plan,
    StructureType.mineshaft: _mineshaft_plan,
}


class StaticBuildPlanCatalog:
    """Maps a ``StructureType`` to a deterministic, hand-authored ``BuildPlan``.

    The catalog exists so headless smoke runs can compile a ``BuildScript``
    without invoking the cloud decomposer. Each entry is intentionally
    simple: a valid footprint, one or more levels, materials assignments
    for every region the compiler picks, and (where relevant) openings or
    key features that exercise the corresponding recipe.
    """

    def __init__(
        self,
        entries: dict[StructureType, Callable[[], BuildPlan]] | None = None,
    ) -> None:
        self._entries = dict(entries) if entries is not None else dict(_CATALOG)

    def known_structure_types(self) -> frozenset[StructureType]:
        return frozenset(self._entries.keys())

    def get(self, structure_type: StructureType | str) -> BuildPlan | None:
        try:
            key = (
                structure_type
                if isinstance(structure_type, StructureType)
                else StructureType(structure_type)
            )
        except ValueError:
            return None
        factory = self._entries.get(key)
        if factory is None:
            return None
        return factory()

    def resolve(self, intent_args: dict[str, Any] | None) -> BuildPlan | None:
        """Resolver-shaped lookup: read ``structure_type`` from ``intent_args``."""
        if not isinstance(intent_args, dict):
            return None
        raw = intent_args.get("structure_type")
        if raw is None:
            return None
        return self.get(raw)


def build_plan_catalog_resolver(
    catalog: StaticBuildPlanCatalog | None = None,
) -> Callable[[dict[str, Any]], BuildPlan | None]:
    """Return a resolver callable compatible with ``HeadlessExecutor``.

    The returned callable accepts the ``intent.args`` payload (as written
    to ``build_intents.jsonl``) and returns either a ``BuildPlan`` from
    the catalog or ``None`` when the structure type is unknown. It never
    raises — malformed args produce ``None`` so a single bad intent
    cannot break a long-running sim.
    """
    cat = catalog if catalog is not None else StaticBuildPlanCatalog()

    def _resolve(intent_args: dict[str, Any]) -> BuildPlan | None:
        return cat.resolve(intent_args)

    return _resolve


__all__ = [
    "StaticBuildPlanCatalog",
    "build_plan_catalog_resolver",
]

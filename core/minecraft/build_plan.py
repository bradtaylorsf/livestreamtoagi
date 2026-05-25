"""Structured ``BuildPlan`` — the architectural decomposition of a reference image (issue #856).

A ``BuildPlan`` is the *architectural* output of the vision-model decomposer
in ``core/minecraft/build_plan_decomposer.py``. It describes a building in
terms a deterministic compiler (E22-7) can lower into Minecraft blocks:
footprint, levels, rooms, materials, key features, and openings.

This is distinct from the low-level *verification* dict in
``core/embodiment/build_plan.py`` which only records ``{position → block}``
expectations for the executor's post-build check; that file remains
untouched.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.agents.build_intent import SizeClass, StructureType

FootprintShape = Literal["rectangle", "circle", "oval", "polygon"]
KeyFeatureKind = Literal["column", "arch", "roof", "ornament", "other"]
OpeningKind = Literal["door", "window"]


class BoundingBox(BaseModel):
    """Axis-aligned planar bounding box in tile-space."""

    model_config = ConfigDict(extra="forbid")

    x: int
    y: int
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class Footprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shape: FootprintShape
    bbox: BoundingBox
    polygon_points: list[tuple[int, int]] | None = None

    @field_validator("polygon_points")
    @classmethod
    def _polygon_points_when_polygon(
        cls, value: list[tuple[int, int]] | None
    ) -> list[tuple[int, int]] | None:
        if value is not None and len(value) < 3:
            raise ValueError("polygon footprints need at least 3 points")
        return value


class Level(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    height_blocks: int = Field(gt=0)
    floor_material: str
    ceiling_material: str | None = None


class Room(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    level_index: int = Field(ge=0)
    relative_bbox: BoundingBox
    connections: list[str] = Field(default_factory=list)


class MaterialAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: str = Field(min_length=1)
    material: str = Field(min_length=1)


class Position3D(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: int
    y: int
    z: int


class KeyFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: KeyFeatureKind
    position: Position3D
    size: dict[str, int] | None = None


class Opening(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: OpeningKind
    position: Position3D
    level_index: int = Field(ge=0)


class BuildPlan(BaseModel):
    """Decomposer output: an architectural blueprint, not yet block placements."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    structure_type: StructureType
    size_class: SizeClass
    source_image_id: str = Field(min_length=1)
    footprint: Footprint
    levels: list[Level] = Field(min_length=1)
    rooms: list[Room] = Field(default_factory=list)
    materials: list[MaterialAssignment] = Field(min_length=1)
    key_features: list[KeyFeature] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    decomposer_version: int = Field(ge=1)
    provider_model_id: str = Field(min_length=1)


__all__ = [
    "BoundingBox",
    "BuildPlan",
    "Footprint",
    "FootprintShape",
    "KeyFeature",
    "KeyFeatureKind",
    "Level",
    "MaterialAssignment",
    "Opening",
    "OpeningKind",
    "Position3D",
    "Room",
]

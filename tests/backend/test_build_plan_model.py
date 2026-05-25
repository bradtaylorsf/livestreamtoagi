"""Unit tests for the architectural ``BuildPlan`` Pydantic model (issue #856)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

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


def _minimal_kwargs(**overrides):
    base = {
        "structure_type": "cabin",
        "size_class": "small",
        "source_image_id": "cabin:image.png",
        "footprint": Footprint(
            shape="rectangle", bbox=BoundingBox(x=0, y=0, w=8, h=6)
        ),
        "levels": [Level(index=0, height_blocks=3, floor_material="oak_planks")],
        "materials": [MaterialAssignment(region="walls", material="oak_log")],
        "decomposer_version": 1,
        "provider_model_id": "fake/test",
    }
    base.update(overrides)
    return base


def test_minimal_valid_plan() -> None:
    plan = BuildPlan(**_minimal_kwargs())
    assert plan.structure_type == "cabin"
    assert plan.size_class == "small"
    assert plan.footprint.shape == "rectangle"
    assert plan.levels[0].height_blocks == 3
    assert plan.rooms == []
    assert plan.key_features == []
    assert plan.openings == []


def test_unknown_structure_type_rejected() -> None:
    with pytest.raises(ValidationError):
        BuildPlan(**_minimal_kwargs(structure_type="megastructure"))


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        BuildPlan(**_minimal_kwargs(weird_extra="x"))


def test_invalid_shape_rejected() -> None:
    with pytest.raises(ValidationError):
        Footprint(shape="bezier", bbox=BoundingBox(x=0, y=0, w=1, h=1))


def test_polygon_requires_three_points() -> None:
    with pytest.raises(ValidationError, match="3 points"):
        Footprint(
            shape="polygon",
            bbox=BoundingBox(x=0, y=0, w=4, h=4),
            polygon_points=[(0, 0), (1, 1)],
        )


def test_levels_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        BuildPlan(**_minimal_kwargs(levels=[]))


def test_materials_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        BuildPlan(**_minimal_kwargs(materials=[]))


def test_level_height_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Level(index=0, height_blocks=0, floor_material="x")


def test_bounding_box_dimensions_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x=0, y=0, w=0, h=4)


def test_complete_plan_roundtrips_json() -> None:
    plan = BuildPlan(
        **_minimal_kwargs(
            rooms=[
                Room(
                    name="hearth",
                    level_index=0,
                    relative_bbox=BoundingBox(x=0, y=0, w=4, h=4),
                    connections=["porch"],
                )
            ],
            key_features=[
                KeyFeature(kind="roof", position=Position3D(x=4, y=3, z=3))
            ],
            openings=[
                Opening(kind="door", position=Position3D(x=4, y=0, z=0), level_index=0)
            ],
        )
    )
    raw = plan.model_dump_json()
    rebuilt = BuildPlan.model_validate(json.loads(raw))
    assert rebuilt.rooms[0].name == "hearth"
    assert rebuilt.key_features[0].kind == "roof"
    assert rebuilt.openings[0].kind == "door"

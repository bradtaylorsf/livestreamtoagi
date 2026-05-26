"""Unit tests for the ``BuildIntent`` Pydantic model (issue #855)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.agents.build_intent import (
    LOCATION_INTENTS,
    SIZE_CLASSES,
    STRUCTURE_TYPES,
    BuildCoords,
    BuildIntent,
    LocationIntent,
    SizeClass,
    StructureType,
)


def _minimal_kwargs(**overrides):
    base = {
        "proposer_id": "rex",
        "structure_type": StructureType.cabin,
        "size_class": SizeClass.small,
        "location_intent": LocationIntent.open_area,
        "motivation": "i want a place to sleep",
    }
    base.update(overrides)
    return base


def test_minimal_valid_intent_has_defaults() -> None:
    intent = BuildIntent(**_minimal_kwargs())
    assert intent.proposer_id == "rex"
    assert intent.structure_type == StructureType.cabin.value
    assert intent.size_class == SizeClass.small.value
    assert intent.location_intent == LocationIntent.open_area.value
    assert intent.intent_id.startswith("build-")
    assert intent.coords is None
    assert intent.materials_preference is None
    assert intent.reference_image_id is None


def test_structure_type_catalog_matches_enum() -> None:
    assert STRUCTURE_TYPES == frozenset(s.value for s in StructureType)
    assert "cabin" in STRUCTURE_TYPES
    assert "coliseum" in STRUCTURE_TYPES
    assert "mineshaft" in STRUCTURE_TYPES
    assert SIZE_CLASSES == frozenset({"small", "medium", "large", "epic"})
    assert "claim_specified" in LOCATION_INTENTS


def test_unknown_structure_type_rejected() -> None:
    with pytest.raises(ValidationError):
        BuildIntent(**_minimal_kwargs(structure_type="megastructure"))


def test_missing_motivation_rejected() -> None:
    with pytest.raises(ValidationError, match="motivation"):
        BuildIntent(**_minimal_kwargs(motivation=""))


def test_whitespace_motivation_rejected() -> None:
    with pytest.raises(ValidationError, match="motivation is required"):
        BuildIntent(**_minimal_kwargs(motivation="   "))


def test_claim_specified_requires_coords() -> None:
    with pytest.raises(ValidationError, match="coords"):
        BuildIntent(**_minimal_kwargs(location_intent=LocationIntent.claim_specified))


def test_claim_specified_with_coords_ok() -> None:
    intent = BuildIntent(
        **_minimal_kwargs(
            location_intent=LocationIntent.claim_specified,
            coords=BuildCoords(x=10, y=64, z=-5),
        )
    )
    assert intent.coords is not None
    assert intent.coords.as_dict() == {"x": 10, "y": 64, "z": -5}


def test_empty_proposer_id_rejected() -> None:
    with pytest.raises(ValidationError):
        BuildIntent(**_minimal_kwargs(proposer_id="   "))


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        BuildIntent(**_minimal_kwargs(weird_extra="x"))


def test_materials_preference_strips_blanks() -> None:
    intent = BuildIntent(
        **_minimal_kwargs(materials_preference=["oak_log", "   ", "stone"])
    )
    assert intent.materials_preference == ["oak_log", "stone"]


def test_materials_preference_all_blank_normalized_to_none() -> None:
    intent = BuildIntent(**_minimal_kwargs(materials_preference=["", "   "]))
    assert intent.materials_preference is None


def test_json_roundtrip() -> None:
    intent = BuildIntent(
        **_minimal_kwargs(
            structure_type=StructureType.coliseum,
            size_class=SizeClass.epic,
            location_intent=LocationIntent.claim_specified,
            coords=BuildCoords(x=1, y=64, z=2),
            materials_preference=["sandstone"],
            reference_image_id="coliseum:v1",
        )
    )
    raw = intent.model_dump_json()
    payload = json.loads(raw)
    rebuilt = BuildIntent.model_validate(payload)
    assert rebuilt.structure_type == StructureType.coliseum.value
    assert rebuilt.size_class == SizeClass.epic.value
    assert rebuilt.coords is not None
    assert rebuilt.coords.x == 1
    assert rebuilt.reference_image_id == "coliseum:v1"


def test_to_log_payload_is_json_serializable() -> None:
    intent = BuildIntent(**_minimal_kwargs())
    payload = intent.to_log_payload()
    rebuilt = json.loads(json.dumps(payload, default=str))
    assert rebuilt["proposer_id"] == "rex"
    assert rebuilt["motivation"] == "i want a place to sleep"

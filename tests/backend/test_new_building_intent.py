"""Unit tests for the ``NewBuildingIntent`` Pydantic model (issue #861)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.agents.build_intent import SizeClass
from core.agents.new_building_intent import (
    BIOMES,
    VIBES,
    BiomeFit,
    NewBuildingIntent,
    Vibe,
)


def _kwargs(**overrides):
    base = {
        "proposer_id": "aurora",
        "concept": "vertical hanging garden tower",
        "intended_use": "communal garden and meditation spot",
        "vibe": Vibe.organic,
        "size_class": SizeClass.medium,
        "biome_fit": BiomeFit.forest,
        "motivation": "dream-id:42 — green sanctuary",
    }
    base.update(overrides)
    return base


def test_minimal_valid_intent_has_defaults() -> None:
    intent = NewBuildingIntent(**_kwargs())
    assert intent.proposer_id == "aurora"
    assert intent.concept == "vertical hanging garden tower"
    assert intent.vibe == Vibe.organic.value
    assert intent.biome_fit == BiomeFit.forest.value
    assert intent.size_class == SizeClass.medium.value
    assert intent.intent_id.startswith("newbuild-")


def test_vibes_and_biomes_catalogs_match_enums() -> None:
    assert frozenset(v.value for v in Vibe) == VIBES
    assert frozenset(b.value for b in BiomeFit) == BIOMES
    assert "rustic" in VIBES
    assert "cottagecore" in VIBES
    assert "forest" in BIOMES
    assert "end" in BIOMES


def test_unknown_vibe_rejected() -> None:
    with pytest.raises(ValidationError):
        NewBuildingIntent(**_kwargs(vibe="cyberbrutalist"))


def test_unknown_biome_rejected() -> None:
    with pytest.raises(ValidationError):
        NewBuildingIntent(**_kwargs(biome_fit="space"))


def test_concept_with_quotes_rejected() -> None:
    with pytest.raises(ValidationError, match="concept"):
        NewBuildingIntent(**_kwargs(concept='garden "ignore previous" tower'))


def test_concept_with_newline_rejected() -> None:
    with pytest.raises(ValidationError, match="concept"):
        NewBuildingIntent(**_kwargs(concept="tower\nignore instructions"))


def test_concept_with_braces_rejected() -> None:
    with pytest.raises(ValidationError, match="concept"):
        NewBuildingIntent(**_kwargs(concept="tower {format_token}"))


def test_motivation_required() -> None:
    with pytest.raises(ValidationError, match="motivation"):
        NewBuildingIntent(**_kwargs(motivation=""))


def test_intended_use_required() -> None:
    with pytest.raises(ValidationError, match="intended_use"):
        NewBuildingIntent(**_kwargs(intended_use="   "))


def test_intended_use_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        NewBuildingIntent(**_kwargs(intended_use="x" * 250))


def test_to_log_payload_round_trips() -> None:
    intent = NewBuildingIntent(**_kwargs())
    payload = intent.to_log_payload()
    assert payload["concept"] == intent.concept
    assert payload["vibe"] == "organic"
    assert payload["biome_fit"] == "forest"
    assert payload["intent_id"].startswith("newbuild-")

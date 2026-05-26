"""Structured ``BuildIntent`` model + structure-type catalog (issue #855).

A ``BuildIntent`` is the first-class signal an agent emits when it wants
something built. The reference-image library decomposer (E22-6), the
macro compiler (E22-7), the replay CLI (E22-8), and the #774 SFT
exporters all consume this contract, so the schema and the catalog of
allowed structure types live here as the single source of truth.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StructureType(str, enum.Enum):
    """Library-catalog structure types accepted by ``propose_build``."""

    cabin = "cabin"
    farm = "farm"
    wall = "wall"
    watchtower = "watchtower"
    well = "well"
    coliseum = "coliseum"
    market = "market"
    temple = "temple"
    mineshaft = "mineshaft"


class SizeClass(str, enum.Enum):
    small = "small"
    medium = "medium"
    large = "large"
    epic = "epic"


class LocationIntent(str, enum.Enum):
    near_me = "near_me"
    near_alliance_hq = "near_alliance_hq"
    open_area = "open_area"
    claim_specified = "claim_specified"


STRUCTURE_TYPES: frozenset[str] = frozenset(s.value for s in StructureType)
SIZE_CLASSES: frozenset[str] = frozenset(s.value for s in SizeClass)
LOCATION_INTENTS: frozenset[str] = frozenset(s.value for s in LocationIntent)


class BuildCoords(BaseModel):
    """Optional block-space coordinates for ``claim_specified`` intents."""

    model_config = ConfigDict(extra="forbid")

    x: int
    y: int = 64
    z: int

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "z": self.z}


class BuildIntent(BaseModel):
    """An agent's structured request that a particular building be built.

    Intents are validated by :class:`tools.build_tools.ProposeBuildTool`,
    appended to ``<sim-folder>/build_intents.jsonl`` by the embodiment
    executor, and (in embodied mode) handed off to the Director V2 build
    macro scheduler.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    intent_id: str = Field(default_factory=lambda: f"build-{uuid.uuid4().hex[:12]}")
    proposer_id: str = Field(min_length=1)
    structure_type: StructureType
    size_class: SizeClass
    location_intent: LocationIntent
    coords: BuildCoords | None = None
    materials_preference: list[str] | None = None
    motivation: str = Field(min_length=1)
    reference_image_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("proposer_id")
    @classmethod
    def _proposer_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("proposer_id must be a non-empty string")
        return stripped

    @field_validator("motivation")
    @classmethod
    def _motivation_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("motivation is required and must link to a goal/need/dream")
        return stripped

    @field_validator("materials_preference")
    @classmethod
    def _materials_non_empty_entries(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned or None

    @model_validator(mode="after")
    def _coords_required_when_claim_specified(self) -> BuildIntent:
        if self.location_intent == LocationIntent.claim_specified.value and self.coords is None:
            raise ValueError("coords are required when location_intent='claim_specified'")
        return self

    def to_log_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable dict suitable for build_intents.jsonl."""
        return self.model_dump(mode="json")


__all__ = [
    "STRUCTURE_TYPES",
    "SIZE_CLASSES",
    "LOCATION_INTENTS",
    "BuildCoords",
    "BuildIntent",
    "LocationIntent",
    "SizeClass",
    "StructureType",
]

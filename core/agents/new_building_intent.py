"""Structured ``NewBuildingIntent`` for dream-up builds (issue #861).

Distinct from :class:`core.agents.build_intent.BuildIntent`, which picks a
library structure. ``NewBuildingIntent`` lets an agent describe a brand-new
building via a small set of *enum-validated* fields. The image-generation
prompt template (``core.minecraft.blueprint_generator``) reads only the
validated fields; agents cannot inject free text into the image prompt.
"""

from __future__ import annotations

import enum
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.agents.build_intent import SizeClass

_CONCEPT_PATTERN = re.compile(r"^[A-Za-z0-9 \-]+$")


class Vibe(str, enum.Enum):
    rustic = "rustic"
    classical = "classical"
    futuristic = "futuristic"
    organic = "organic"
    brutalist = "brutalist"
    gothic = "gothic"
    cyberpunk = "cyberpunk"
    cottagecore = "cottagecore"


class BiomeFit(str, enum.Enum):
    forest = "forest"
    desert = "desert"
    mountain = "mountain"
    water = "water"
    plains = "plains"
    nether = "nether"
    end = "end"


VIBES: frozenset[str] = frozenset(v.value for v in Vibe)
BIOMES: frozenset[str] = frozenset(b.value for b in BiomeFit)


class NewBuildingIntent(BaseModel):
    """Agent-authored request to dream up a brand-new building.

    Every field is structurally validated (enum or short regex-checked
    noun phrase). The image-generation prompt template only interpolates
    these validated fields, so no agent free-text reaches the image model
    directly.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    intent_id: str = Field(
        default_factory=lambda: f"newbuild-{uuid.uuid4().hex[:12]}"
    )
    proposer_id: str = Field(min_length=1)
    concept: str = Field(min_length=2, max_length=80)
    intended_use: str = Field(min_length=1, max_length=200)
    vibe: Vibe
    size_class: SizeClass
    biome_fit: BiomeFit
    motivation: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("proposer_id")
    @classmethod
    def _proposer_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("proposer_id must be a non-empty string")
        return stripped

    @field_validator("concept")
    @classmethod
    def _concept_locked_vocabulary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("concept must be a non-empty noun phrase")
        if not _CONCEPT_PATTERN.match(stripped):
            raise ValueError(
                "concept must contain only letters, digits, spaces, and "
                "hyphens — punctuation, quotes, and template tokens are "
                "rejected to prevent image-prompt injection"
            )
        return stripped

    @field_validator("intended_use")
    @classmethod
    def _intended_use_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("intended_use must be a non-empty string")
        return stripped

    @field_validator("motivation")
    @classmethod
    def _motivation_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "motivation is required and must link to a goal/need/dream"
            )
        return stripped

    def to_log_payload(self) -> dict[str, Any]:
        """JSON-serializable form suitable for decision_log + jsonl artifacts."""
        return self.model_dump(mode="json")


__all__ = [
    "BIOMES",
    "VIBES",
    "BiomeFit",
    "NewBuildingIntent",
    "Vibe",
]

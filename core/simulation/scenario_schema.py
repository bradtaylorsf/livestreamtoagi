"""Pydantic schema for scenario YAML files.

A scenario YAML is the authoring surface for a simulation run: it declares
which agents participate, what phases unfold, optional pre-seeded factions
and persona overrides, run-mode flags, and — added by E22-3 — which eval
categories the scenario is meant to exercise (``eval_targets``).

The schema also defines a placeholder ``WorldEventsBlock`` (full shape
landed by E22-4) so authors can stub headless world-event configuration
without breaking validation while E22-4 is in flight.

Use :func:`validate_scenario_dict` for the canonical entrypoint.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.eval.prompt_loader import discover_categories
from core.models import (
    ExperimentalGoalConfig,
    FactionConfig,
    MemorySeedConfig,
    PersonaOverride,
    WorldConfig,
)
from core.simulation.phases import PhaseType

PHASE_TYPE_VALUES: set[str] = {t.value for t in PhaseType}


@lru_cache(maxsize=1)
def _eval_categories() -> tuple[str, ...]:
    """Snapshot of evals/prompts/*.yaml category names at import time."""
    return tuple(discover_categories())


class MetaBlock(BaseModel):
    """The ``meta:`` block — human-facing scenario identity.

    Strongly recommended on every committed scenario (the public Scenario
    Library reads it), but optional at the schema level so internal
    fixtures and in-test scenarios can stay minimal.
    """

    model_config = ConfigDict(extra="allow")

    name: str = ""
    description: str = ""
    agents: list[str] = Field(default_factory=list)
    supports_modes: list[str] | None = None
    expected_max_cost: float = 0.0
    expected_runtime_minutes: int = 0


class AudienceBlock(BaseModel):
    """The ``audience:`` block — Twitch audience simulator config."""

    model_config = ConfigDict(extra="allow")

    initial_viewers: int = 0
    growth_rate: str | None = None
    chat_frequency: str | None = None
    viewer_personas: list[dict[str, Any]] = Field(default_factory=list)


class PhaseSpec(BaseModel):
    """A single phase entry from the scenario ``phases:`` list.

    Extra keys are allowed and flow through into ``Phase.config`` so phase
    runners can read scenario-specific options (e.g. ``topics``, ``count``,
    ``trigger``) without the schema needing to enumerate every variant.
    """

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    type: str

    @field_validator("type")
    @classmethod
    def _known_phase_type(cls, v: str) -> str:
        if v not in PHASE_TYPE_VALUES:
            raise ValueError(
                f"unknown phase type {v!r}; must be one of {sorted(PHASE_TYPE_VALUES)}"
            )
        return v


def _validate_world_event_type(value: str) -> str:
    """Cross-check against the canonical event vocabulary from E22-4."""
    from core.simulation.world_events import WORLD_EVENT_TYPES

    if value not in WORLD_EVENT_TYPES:
        raise ValueError(
            f"unknown world event {value!r}; must be one of {list(WORLD_EVENT_TYPES)}"
        )
    return value


class ScheduledWorldEvent(BaseModel):
    """A world event that fires on a specific simulation tick."""

    model_config = ConfigDict(extra="forbid")

    tick: int = Field(ge=0)
    event: str = Field(min_length=1)

    @field_validator("event")
    @classmethod
    def _known_event(cls, v: str) -> str:
        return _validate_world_event_type(v)


class ProbabilisticWorldEvent(BaseModel):
    """A world event with per-tick fire probability and optional gating."""

    model_config = ConfigDict(extra="forbid")

    event: str = Field(min_length=1)
    prob_per_tick: float = Field(ge=0.0, le=1.0)
    requires: str | None = None

    @field_validator("event")
    @classmethod
    def _known_event(cls, v: str) -> str:
        return _validate_world_event_type(v)

    @field_validator("requires")
    @classmethod
    def _known_requires(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _validate_world_event_type(v)


class NeedDecayConfig(BaseModel):
    """Decay/threshold config for a single agent need (hunger, sleep, ...)."""

    model_config = ConfigDict(extra="forbid")

    tick_decay: float = Field(ge=0.0)
    critical_threshold: float = Field(ge=0.0, le=100.0)
    warning_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    recovery_per_action: float | None = Field(default=None, ge=0.0)


class WorldEventsBlock(BaseModel):
    """The ``world_events:`` block — headless environmental triggers (E22-4).

    Authors declare scheduled events (fire on a specific tick), probabilistic
    events (per-tick roll, optionally gated on another event), and per-need
    decay/threshold config. The :class:`WorldEventScheduler` and
    :class:`NeedsManager` consume this block at runtime.
    """

    model_config = ConfigDict(extra="forbid")

    schedule: list[ScheduledWorldEvent] = Field(default_factory=list)
    probabilistic: list[ProbabilisticWorldEvent] = Field(default_factory=list)
    needs: dict[str, NeedDecayConfig] = Field(default_factory=dict)
    disable_world_event_scheduler: bool = False

    @field_validator("needs")
    @classmethod
    def _known_need_names(
        cls, v: dict[str, NeedDecayConfig]
    ) -> dict[str, NeedDecayConfig]:
        from core.agent_needs import NEED_NAMES

        unknown = [name for name in v if name not in NEED_NAMES]
        if unknown:
            raise ValueError(
                f"unknown need names {unknown}; valid: {list(NEED_NAMES)}"
            )
        return v


class EvalTargetsBlock(BaseModel):
    """The ``eval_targets:`` block — what eval categories this scenario exercises.

    ``primary`` and ``secondary`` reference categories defined under
    ``evals/prompts/*.yaml``; ``success_criteria`` maps a category to a
    human-readable assertion (parsed by the scorer in E22-9). The dashboard
    (E22-10) reads this block to filter and color scenarios.
    """

    model_config = ConfigDict(extra="forbid")

    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)
    success_criteria: dict[str, str] = Field(default_factory=dict)

    @field_validator("primary", "secondary")
    @classmethod
    def _known_eval_categories(cls, v: list[str]) -> list[str]:
        valid = set(_eval_categories())
        if not valid:
            return v
        unknown = [item for item in v if item not in valid]
        if unknown:
            raise ValueError(
                f"unknown eval categories {unknown}; valid: {sorted(valid)}"
            )
        return v

    @model_validator(mode="after")
    def _success_criteria_categories_known(self) -> EvalTargetsBlock:
        valid = set(_eval_categories())
        if not valid:
            return self
        unknown = [c for c in self.success_criteria if c not in valid]
        if unknown:
            raise ValueError(
                f"success_criteria references unknown eval categories: {unknown}"
            )
        return self


class ScenarioSchema(BaseModel):
    """Top-level scenario YAML schema."""

    model_config = ConfigDict(extra="forbid")

    meta: MetaBlock = Field(default_factory=MetaBlock)
    phases: list[PhaseSpec] = Field(default_factory=list)
    audience: AudienceBlock | None = None
    seed_tasks: bool = False
    seed_goals: bool = False
    memory_seed: MemorySeedConfig | None = None
    persona_overrides: list[PersonaOverride] = Field(default_factory=list)
    agent_goals: dict[str, list[str] | str] | None = None
    factions: list[FactionConfig] = Field(default_factory=list)
    world: WorldConfig | None = None
    world_events: WorldEventsBlock | None = None
    eval_targets: EvalTargetsBlock | None = None
    run_mode: Literal["persistent", "experimental", "headless"] | None = None
    management_policy: Literal["off", "shadow", "enforce"] | None = None
    experimental_goal: ExperimentalGoalConfig | None = None
    agents: list[str] | None = None

    @model_validator(mode="after")
    def _unique_faction_names(self) -> ScenarioSchema:
        seen: set[str] = set()
        for faction in self.factions:
            if faction.name in seen:
                raise ValueError(f"duplicate faction name: {faction.name}")
            seen.add(faction.name)
        return self


def validate_scenario_dict(data: dict[str, Any]) -> ScenarioSchema:
    """Validate a raw parsed-YAML dict against the scenario schema."""
    return ScenarioSchema.model_validate(data)

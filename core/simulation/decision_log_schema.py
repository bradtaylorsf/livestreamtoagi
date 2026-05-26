"""Pydantic schema for the headless decision log (issue #852).

Every row in ``<sim-folder>/decision_log.jsonl`` is a :class:`DecisionLogRow`
instance — a discriminated union over ``event_type``. The schema is the
contract between the headless sim, the Minecraft replay tool, eval scoring,
and the synthetic-data exporters in #774.

Bumping ``SCHEMA_VERSION`` requires writing a corresponding reader migration
(see :class:`DecisionLogReader`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class MotivationLink(BaseModel):
    """A pointer back to the goal/dream/need that triggered an event."""

    kind: Literal["goal", "dream", "need", "blackboard", "world_event"]
    ref_id: str | None = None
    description: str | None = None


# ─── Event-specific payloads ───────────────────────────────────────────────


class UtterancePayload(BaseModel):
    text: str
    channel: str = "chat"
    model: str | None = None
    tokens: int | None = None
    cost: str | None = None


class ToolIntentPayload(BaseModel):
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["executed", "blocked", "simulated"]
    block_reason: str | None = None
    outcome: Any | None = None


class RelationshipDeltaPayload(BaseModel):
    a: str
    b: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class AllianceDeltaPayload(BaseModel):
    alliance_id: str
    members: list[str] = Field(default_factory=list)
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class DreamPayload(BaseModel):
    dream_narrative: str
    insights: list[str] = Field(default_factory=list)
    new_goals: list[dict[str, Any]] = Field(default_factory=list)
    mood_shift: str | None = None


class NewGoalPayload(BaseModel):
    goal_id: str | None = None
    description: str
    category: str | None = None
    priority: int | None = None
    source: str | None = None


class BlackboardMutationPayload(BaseModel):
    key: str
    before: Any | None = None
    after: Any | None = None
    source: str | None = None


class WorldEventPayload(BaseModel):
    event_type: str
    trigger: str | None = None
    severity: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class NeedsStatePayload(BaseModel):
    hunger: float | None = None
    sleep: float | None = None
    energy: float | None = None
    other: dict[str, float] = Field(default_factory=dict)


# ─── Row types ─────────────────────────────────────────────────────────────


class _BaseRow(BaseModel):
    """Common fields on every decision-log row."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    tick: int
    wall_time: datetime
    sim_time: float
    actor_id: str | None = None
    motivation_chain: list[MotivationLink] | None = None


class UtteranceRow(_BaseRow):
    event_type: Literal["utterance"] = "utterance"
    payload: UtterancePayload


class ToolIntentRow(_BaseRow):
    event_type: Literal["tool_intent"] = "tool_intent"
    payload: ToolIntentPayload


class RelationshipDeltaRow(_BaseRow):
    event_type: Literal["relationship_delta"] = "relationship_delta"
    payload: RelationshipDeltaPayload


class AllianceDeltaRow(_BaseRow):
    event_type: Literal["alliance_delta"] = "alliance_delta"
    payload: AllianceDeltaPayload


class DreamRow(_BaseRow):
    event_type: Literal["dream"] = "dream"
    payload: DreamPayload


class NewGoalRow(_BaseRow):
    event_type: Literal["new_goal"] = "new_goal"
    payload: NewGoalPayload


class BlackboardMutationRow(_BaseRow):
    event_type: Literal["blackboard_mutation"] = "blackboard_mutation"
    payload: BlackboardMutationPayload


class WorldEventRow(_BaseRow):
    event_type: Literal["world_event"] = "world_event"
    payload: WorldEventPayload


class NeedsStateRow(_BaseRow):
    event_type: Literal["needs_state"] = "needs_state"
    payload: NeedsStatePayload


DecisionLogRow = Annotated[
    UtteranceRow
    | ToolIntentRow
    | RelationshipDeltaRow
    | AllianceDeltaRow
    | DreamRow
    | NewGoalRow
    | BlackboardMutationRow
    | WorldEventRow
    | NeedsStateRow,
    Field(discriminator="event_type"),
]


class DecisionLogRowEnvelope(BaseModel):
    """Validation envelope so callers can parse a single row via Pydantic."""

    model_config = ConfigDict(extra="forbid")

    row: DecisionLogRow


__all__ = [
    "SCHEMA_VERSION",
    "AllianceDeltaPayload",
    "AllianceDeltaRow",
    "BlackboardMutationPayload",
    "BlackboardMutationRow",
    "DecisionLogRow",
    "DecisionLogRowEnvelope",
    "DreamPayload",
    "DreamRow",
    "MotivationLink",
    "NeedsStatePayload",
    "NeedsStateRow",
    "NewGoalPayload",
    "NewGoalRow",
    "RelationshipDeltaPayload",
    "RelationshipDeltaRow",
    "ToolIntentPayload",
    "ToolIntentRow",
    "UtterancePayload",
    "UtteranceRow",
    "WorldEventPayload",
    "WorldEventRow",
]

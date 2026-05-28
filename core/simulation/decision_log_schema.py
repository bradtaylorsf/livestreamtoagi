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
    runtime_model: str | None = None
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


class OwnershipDeltaPayload(BaseModel):
    """Ownership claim/release/conflict (issue #891).

    ``action='conflict'`` rows record an *attempted* claim that lost to an
    earlier owner — ``owner_agent_id`` is the would-be claimant and
    ``claim_id`` is the existing winning claim's id.
    """

    claim_id: str
    owner_agent_id: str
    target_type: Literal["region", "structure", "container"]
    target_ref: dict[str, Any] = Field(default_factory=dict)
    action: Literal["claim", "release", "conflict"]
    motivation: str | None = None


class TradeEventPayload(BaseModel):
    """Trade offer / acceptance / rejection / expiry (issue #892)."""

    offer_id: str
    proposer_id: str
    recipient_id: str
    give: dict[str, int] = Field(default_factory=dict)
    want: dict[str, int] = Field(default_factory=dict)
    motivation: str | None = None
    action: Literal["proposed", "accepted", "rejected", "expired"]
    reject_reason: str | None = None
    price_observation: dict[str, Any] | None = None


class TheftEventPayload(BaseModel):
    """Theft attempt + outcome (issue #893).

    ``detected`` reflects the detection roll at attempt time; a witness
    that later reports the theft re-emits a row with ``detected=True`` so
    consequence logic can fire from the report alone.
    """

    attempt_id: str
    thief_id: str
    victim_id: str
    container_ref: dict[str, Any] = Field(default_factory=dict)
    items: dict[str, int] = Field(default_factory=dict)
    detected: bool
    witnesses: list[str] = Field(default_factory=list)
    motivation: str | None = None


class DiplomacyEventPayload(BaseModel):
    """Treaty lifecycle + faction defection (issue #894).

    The same row shape covers proposal, signing, breaking, and defection.
    ``treaty_id`` is None for defection-only events. ``parties`` lists the
    faction ids involved (for treaty actions); defection records its
    movement via ``from_faction`` / ``to_faction``.
    """

    treaty_id: str | None = None
    parties: list[str] = Field(default_factory=list)
    action: Literal["proposed", "signed", "broken", "defected"]
    terms: dict[str, Any] = Field(default_factory=dict)
    breaker_id: str | None = None
    defector_id: str | None = None
    from_faction: str | None = None
    to_faction: str | None = None
    motivation: str | None = None
    reason: str | None = None


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


class OwnershipDeltaRow(_BaseRow):
    event_type: Literal["ownership_delta"] = "ownership_delta"
    payload: OwnershipDeltaPayload


class TradeEventRow(_BaseRow):
    event_type: Literal["trade_event"] = "trade_event"
    payload: TradeEventPayload


class TheftEventRow(_BaseRow):
    event_type: Literal["theft_event"] = "theft_event"
    payload: TheftEventPayload


class DiplomacyEventRow(_BaseRow):
    event_type: Literal["diplomacy_event"] = "diplomacy_event"
    payload: DiplomacyEventPayload


DecisionLogRow = Annotated[
    UtteranceRow
    | ToolIntentRow
    | RelationshipDeltaRow
    | AllianceDeltaRow
    | DreamRow
    | NewGoalRow
    | BlackboardMutationRow
    | WorldEventRow
    | NeedsStateRow
    | OwnershipDeltaRow
    | TradeEventRow
    | TheftEventRow
    | DiplomacyEventRow,
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
    "DiplomacyEventPayload",
    "DiplomacyEventRow",
    "DreamPayload",
    "DreamRow",
    "MotivationLink",
    "NeedsStatePayload",
    "NeedsStateRow",
    "NewGoalPayload",
    "NewGoalRow",
    "OwnershipDeltaPayload",
    "OwnershipDeltaRow",
    "RelationshipDeltaPayload",
    "RelationshipDeltaRow",
    "TheftEventPayload",
    "TheftEventRow",
    "ToolIntentPayload",
    "ToolIntentRow",
    "TradeEventPayload",
    "TradeEventRow",
    "UtterancePayload",
    "UtteranceRow",
    "WorldEventPayload",
    "WorldEventRow",
]

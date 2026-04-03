"""Pydantic models for all database tables."""

from __future__ import annotations

import enum
import uuid  # noqa: TC003
from datetime import datetime  # noqa: TC003
from decimal import Decimal  # noqa: TC003
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ── Agents ──────────────────────────────────────────────────────


class AgentStatus(str, enum.Enum):
    active = "active"
    sleeping = "sleeping"
    paused = "paused"
    muted = "muted"


class Agent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    display_name: str
    model_conversation: str
    model_building: str
    voice_id: str | None = None
    status: str = "active"
    created_at: datetime | None = None


class AgentCreate(BaseModel):
    id: str
    display_name: str
    model_conversation: str
    model_building: str
    voice_id: str | None = None
    status: str = "active"


class AgentConfig(BaseModel):
    """Rich agent configuration loaded from YAML files."""

    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: str
    display_name: str
    model_conversation: str
    model_building: str
    voice_id: str | None = None
    chattiness: float = Field(ge=0.0, le=1.0)
    initiative: float = Field(ge=0.0, le=1.0)
    interrupt_tendency: float = Field(ge=0.0, le=1.0)
    eavesdrop_tendency: float = Field(ge=0.0, le=1.0, default=0.0)
    closing_weight: float = Field(ge=0.0, le=1.0, default=0.0)
    status: AgentStatus = AgentStatus.active
    system_prompt: str = ""
    behaviors: dict[str, Any] = {}  # YAML-defined structure, varies per agent


# ── Core Memory ─────────────────────────────────────────────────

class CoreMemory(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    agent_id: str
    content: str
    token_count: int
    last_updated: datetime | None = None
    version: int = 1


class CoreMemoryHistory(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    content: str
    version: int
    changed_at: datetime | None = None
    change_reason: str | None = None


# ── Recall Memory ───────────────────────────────────────────────

class RecallMemory(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    summary: str
    embedding: list[float]
    event_type: str | None = None
    participants: list[str] | None = None
    transcript_id: int | None = None
    importance_score: float = 0.5
    timestamp: datetime | None = None
    recalled_count: int = 0


class RecallMemoryCreate(BaseModel):
    agent_id: str
    summary: str
    embedding: list[float]
    event_type: str | None = None
    participants: list[str] | None = None
    transcript_id: int | None = None
    importance_score: float = 0.5


# ── Conversation Buffer ─────────────────────────────────────────

class ConversationBuffer(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    role: str
    speaker: str | None = None
    content: str
    created_at: datetime | None = None


class ConversationBufferCreate(BaseModel):
    agent_id: str
    role: Literal["user", "assistant", "system"]
    speaker: str | None = None
    content: str


# ── Transcripts ─────────────────────────────────────────────────

class Transcript(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str
    participants: list[str]
    content: str
    token_count: int
    created_at: datetime | None = None


class TranscriptCreate(BaseModel):
    event_type: str
    participants: list[str]
    content: str
    token_count: int


# ── Journal Entries ─────────────────────────────────────────────

class JournalEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    reflection_type: str
    content: str
    token_count: int
    created_at: datetime | None = None


class JournalEntryCreate(BaseModel):
    agent_id: str
    reflection_type: str
    content: str
    token_count: int


# ── Self-Modification Proposals ─────────────────────────────────

class SelfModificationProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    proposal_type: str
    description: str
    reasoning: str
    status: str = "pending"
    created_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


class SelfModificationProposalCreate(BaseModel):
    agent_id: str
    proposal_type: str
    description: str
    reasoning: str


# ── Reflection Result ───────────────────────────────────────────

class ReflectionResult(BaseModel):
    promoted_count: int = 0
    importance_updates: int = 0
    journal_entry: JournalEntry | None = None
    proposals: list[SelfModificationProposal] = []


# ── Conversations ───────────────────────────────────────────────

class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    started_at: datetime | None = None
    ended_at: datetime | None = None
    trigger_type: str
    trigger_details: dict[str, Any] | None = None
    initial_energy: float = Field(ge=0.0, le=1.0)
    final_energy: float | None = Field(None, ge=0.0, le=1.0)
    turn_count: int = 0
    participating_agents: list[str]
    topics_discussed: list[str] | None = None
    closed_by: str | None = None
    location: str | None = None
    audience_events_during: int = 0
    config_hash: str | None = None


class ConversationCreate(BaseModel):
    id: uuid.UUID | None = None
    trigger_type: str
    trigger_details: dict[str, Any] | None = None
    initial_energy: float = Field(ge=0.0, le=1.0)
    participating_agents: list[str]
    location: str | None = None
    config_hash: str | None = None


# ── Selection Log ───────────────────────────────────────────────

class SelectionLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    turn_number: int
    timestamp: datetime | None = None
    selected_agent_id: str
    was_interrupt: bool = False
    agent_scores: dict[str, Any]
    detected_topic: str | None = None
    previous_speaker_id: str | None = None
    conversation_energy: float | None = None
    active_agents: list[str] | None = None
    trigger_type: str | None = None
    config_hash: str | None = None


class SelectionLogCreate(BaseModel):
    conversation_id: uuid.UUID
    turn_number: int
    selected_agent_id: str
    was_interrupt: bool = False
    agent_scores: dict[str, Any]
    detected_topic: str | None = None
    previous_speaker_id: str | None = None
    conversation_energy: float | None = None
    active_agents: list[str] | None = None
    trigger_type: str | None = None
    config_hash: str | None = None


# ── Interrupt Log ───────────────────────────────────────────────

class InterruptLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    timestamp: datetime | None = None
    attempting_agent_id: str
    would_have_spoken_id: str
    interrupt_score: float
    threshold_at_time: float
    succeeded: bool
    reason: str | None = None


class InterruptLogCreate(BaseModel):
    conversation_id: uuid.UUID
    attempting_agent_id: str
    would_have_spoken_id: str
    interrupt_score: float
    threshold_at_time: float
    succeeded: bool
    reason: str | None = None


# ── Energy Change Log ──────────────────────────────────────────


class EnergyLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID
    turn_number: int
    timestamp: datetime | None = None
    changes: dict[str, Any]


class EnergyLogCreate(BaseModel):
    conversation_id: uuid.UUID
    turn_number: int
    changes: dict[str, Any]


# ── World Chunks ────────────────────────────────────────────────

class WorldChunk(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    x_offset: int
    y_offset: int
    width: int
    height: int
    tile_data: dict[str, Any]
    objects: list[dict[str, Any]] | None = None
    built_by: list[str] | None = None
    built_date: datetime | None = None
    description: str | None = None
    proposal_votes: dict[str, int] | None = None
    tileset_url: str | None = None


class WorldChunkCreate(BaseModel):
    name: str
    x_offset: int
    y_offset: int
    width: int
    height: int
    tile_data: dict[str, Any]
    objects: list[dict[str, Any]] | None = None
    built_by: list[str] | None = None
    description: str | None = None
    tileset_url: str | None = None


# ── World Events ────────────────────────────────────────────────

class WorldEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_type: str | None = None
    description: str | None = None
    agents_involved: list[str] | None = None
    audience_participation: bool = False
    created_at: datetime | None = None


class WorldEventCreate(BaseModel):
    event_type: str | None = None
    description: str | None = None
    agents_involved: list[str] | None = None
    audience_participation: bool = False


# ── Expansion Proposals ─────────────────────────────────────────

class ExpansionProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    proposed_by: str
    title: str
    description: str
    status: str = "proposed"
    votes_for: int = 0
    votes_against: int = 0
    created_at: datetime | None = None


class ExpansionProposalCreate(BaseModel):
    proposed_by: str
    title: str
    description: str


# ── Cost Events ─────────────────────────────────────────────────

class CostEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str | None = None
    cost_type: str | None = None
    amount: Decimal | None = None
    details: dict[str, Any] | None = None
    created_at: datetime | None = None


class CostEventCreate(BaseModel):
    agent_id: str | None = None
    cost_type: str | None = None
    amount: Decimal
    details: dict[str, Any] | None = None


# ── Revenue Events ──────────────────────────────────────────────

class RevenueEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str | None = None
    amount: Decimal | None = None
    details: dict[str, Any] | None = None
    created_at: datetime | None = None


class RevenueEventCreate(BaseModel):
    source: str | None = None
    amount: Decimal
    details: dict[str, Any] | None = None


# ── Challenges ──────────────────────────────────────────────────

class Challenge(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    description: str
    submitted_by: str | None = None
    source: str | None = None
    status: str = "pending"
    assigned_agents: list[str] | None = None
    result: str | None = None
    cost_estimate: float | None = None
    actual_cost: float | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ChallengeCreate(BaseModel):
    description: str
    submitted_by: str | None = None
    source: str | None = None
    assigned_agents: list[str] | None = None
    cost_estimate: float | None = None


# ── LLM Client ─────────────────────────────────────────────────

class LLMResponse(BaseModel):
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal
    latency_ms: int
    openrouter_id: str | None = None


class StreamChunk(BaseModel):
    delta: str
    finish_reason: str | None = None


# ── Conversation Config ────────────────────────────────


class SelectionWeights(BaseModel):
    """Speaker selection weights — must sum to 1.0."""

    model_config = ConfigDict(frozen=True)
    time_since_spoke: float = Field(ge=0.0, le=1.0)
    topic_relevance: float = Field(ge=0.0, le=1.0)
    chattiness: float = Field(ge=0.0, le=1.0)
    adjacency_fit: float = Field(ge=0.0, le=1.0)
    random_jitter: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> SelectionWeights:
        total = (
            self.time_since_spoke
            + self.topic_relevance
            + self.chattiness
            + self.adjacency_fit
            + self.random_jitter
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"selection_weights must sum to 1.0 (got {total:.4f})"
            )
        return self


class PauseMultipliers(BaseModel):
    model_config = ConfigDict(frozen=True)
    after_question: float = Field(ge=0.0)
    after_statement: float = Field(ge=0.0)
    after_interrupt: float = Field(ge=0.0)
    after_joke: float = Field(ge=0.0)
    after_emotional: float = Field(ge=0.0)


class TimingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    min_pause_seconds: float = Field(ge=0.0)
    max_pause_seconds: float = Field(ge=0.0)
    pause_strategy: Literal["fixed", "random", "weighted"]
    pause_multipliers: PauseMultipliers


class EnergyConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    initial_range: tuple[int, int]
    decay_per_turn: float = Field(ge=0.0)
    boost_on_topic_shift: float = Field(ge=0.0)
    boost_on_disagreement: float = Field(ge=0.0)
    boost_on_audience_event: float = Field(ge=0.0)
    boost_on_new_participant: float = Field(ge=0.0)
    drain_on_repetition: float = Field(ge=0.0)
    minimum_turns: int = Field(ge=1)
    maximum_turns: int = Field(ge=1)
    closer_weights: dict[str, float]


class InterruptConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool
    relevance_threshold: float = Field(ge=0.0, le=1.0)
    max_interrupts_per_conversation: int = Field(ge=0)
    cooldown_seconds: int = Field(ge=0)
    agent_interrupt_tendency: dict[str, float]


class ProximityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    enabled: bool
    max_conversation_size: int = Field(ge=1)
    eavesdrop_tendency: dict[str, float]


class ScheduledEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_name: str
    starter_agent_id: str


class TriggerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    idle_timeout_seconds: int = Field(ge=1)
    agent_initiative: dict[str, float]
    trigger_type_weights: dict[str, float]
    memory_trigger_chance: float = Field(ge=0.0, le=1.0, default=0.02)
    daily_schedule: dict[int, ScheduledEvent] = {}


class TopicConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    relevance_map: dict[str, dict[str, float]]
    fallback_to_llm: bool
    classifier_model: str


class LoggingConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    log_every_selection: bool = True
    log_interrupts: bool = True
    log_energy_changes: bool = True
    log_trigger_events: bool = True
    log_topic_classifications: bool = True
    retention_days: int = Field(ge=1, default=30)
    export_format: str = "jsonl"


# ── Speaker Selection Result ───────────────────────────


class InterruptAttempt(BaseModel):
    """Record of a single interrupt attempt (successful or failed)."""

    attempting_agent_id: str
    would_have_spoken_id: str
    interrupt_score: float
    threshold: float
    succeeded: bool
    reason: str | None = None


class SelectionResult(BaseModel):
    """Result of the 5-factor speaker selection algorithm."""

    selected_agent_id: str
    scores: dict[str, float]
    score_breakdown: dict[str, dict[str, float]]
    eligible_agents: list[str]
    previous_speaker_id: str | None = None
    detected_topic: str | None = None
    was_interrupt: bool = False
    interrupted_agent_id: str | None = None
    interrupt_attempts: list[InterruptAttempt] = []


class ConversationConfig(BaseModel):
    """Top-level conversation engine configuration — loaded from YAML."""

    model_config = ConfigDict(frozen=True)
    selection_weights: SelectionWeights
    timing: TimingConfig
    energy: EnergyConfig
    interrupts: InterruptConfig
    proximity: ProximityConfig
    triggers: TriggerConfig
    topics: TopicConfig
    adjacency: dict[str, dict[str, float]]
    logging: LoggingConfig

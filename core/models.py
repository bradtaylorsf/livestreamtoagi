"""Pydantic models for all database tables."""

from __future__ import annotations

import enum
import uuid  # noqa: TC003
from datetime import datetime, timedelta  # noqa: TC003
from decimal import Decimal  # noqa: TC003
from typing import Any, Generic, Literal, TypeVar

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
    role: str = ""
    model_conversation: str
    model_building: str
    voice_id: str | None = None
    color_hex: str = "#888888"
    color_rich: str = "white"
    audio_effects: str | None = None
    chattiness: float = Field(ge=0.0, le=1.0)
    initiative: float = Field(ge=0.0, le=1.0)
    interrupt_tendency: float = Field(ge=0.0, le=1.0)
    eavesdrop_tendency: float = Field(ge=0.0, le=1.0, default=0.0)
    closing_weight: float = Field(ge=0.0, le=1.0, default=0.0)
    role_priority_bonus: float = Field(ge=0.0, default=0.0)
    cross_agent_writer: bool = False
    tools: list[str] = Field(default_factory=list)
    topic_relevance: dict[str, float] = Field(default_factory=dict)
    adjacency: dict[str, float] = Field(default_factory=dict)
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
    conversation_id: uuid.UUID | None = None


# ── Prompt Logs ────────────────────────────────────────────────


class PromptLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    conversation_id: uuid.UUID | None = None
    simulation_id: uuid.UUID | None = None
    agent_id: str
    turn_number: int = 0
    full_prompt: str
    sections_included: dict[str, Any] = Field(default_factory=dict)
    total_tokens: int = 0
    created_at: datetime | None = None


class PromptLogCreate(BaseModel):
    conversation_id: uuid.UUID | None = None
    simulation_id: uuid.UUID | None = None
    agent_id: str
    turn_number: int = 0
    full_prompt: str
    sections_included: dict[str, Any] = Field(default_factory=dict)
    total_tokens: int = 0


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
    file: str | None = None
    new_content: str | None = None
    impact_notes: str | None = None
    status: str = "queued_for_review"
    created_at: datetime | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


class SelfModificationProposalCreate(BaseModel):
    agent_id: str
    proposal_type: str
    description: str
    reasoning: str
    file: str | None = None
    new_content: str | None = None
    impact_notes: str | None = None


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
    simulation_id: uuid.UUID | None = None
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
    simulation_id: uuid.UUID | None = None


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
    simulation_id: uuid.UUID | None = None
    created_at: datetime | None = None


class CostEventCreate(BaseModel):
    agent_id: str | None = None
    cost_type: str | None = None
    amount: Decimal
    details: dict[str, Any] | None = None
    simulation_id: uuid.UUID | None = None


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


# ── Management / Content Filter ──────────────────────────────────


class ContentReviewResult(BaseModel):
    """Result of Management content review."""

    approved: bool
    reason: str
    severity: int = Field(ge=1, le=5)
    replacement: str | None = None


# ── LLM Client ─────────────────────────────────────────────────

class ToolCall(BaseModel):
    """A single tool/function call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal
    latency_ms: int
    openrouter_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


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


class ReflectionScheduleConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    six_hour_interval_hours: int = Field(default=6, ge=1)
    daily_hour: int = Field(default=23, ge=0, le=23)
    weekly_day: int = Field(default=7, ge=1, le=7)


class TopicConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    relevance_map: dict[str, dict[str, float]]
    topic_keywords: dict[str, list[str]] = {}
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


# ── Artifacts ──────────────────────────────────────────────────


# Maps tool names to artifact_type values
ARTIFACT_TYPE_MAP: dict[str, str] = {
    "draft_social_post": "social_post",
    "draft_email": "email",
    "execute_code": "code_execution",
    "web_search": "web_search",
    "fetch_url": "web_search",
    "generate_tilemap": "tilemap",
    "create_poll": "poll",
    "recall_memory": "memory_operation",
    "update_core_memory": "memory_operation",
    "retrieve_transcript": "memory_operation",
    "dispatch_alpha": "alpha_dispatch",
    "propose_self_modification": "self_modification",
    "view_evolution_log": "self_modification",
    "send_message": "message",
}

# Tools whose artifacts should default to pending_approval status
PENDING_APPROVAL_TOOLS: set[str] = {"draft_social_post", "draft_email"}


class Artifact(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    simulation_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    agent_id: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    artifact_type: str
    status: str = "executed"
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class ArtifactCreate(BaseModel):
    simulation_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    agent_id: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    artifact_type: str
    status: str = "executed"
    metadata: dict[str, Any] | None = None


# ── Simulations ──────────────────────────────────────────────────


class SimulationStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SimulationCreate(BaseModel):
    name: str
    description: str | None = None
    config: dict[str, Any]
    status: SimulationStatus = SimulationStatus.running
    simulated_duration: timedelta | None = None
    agents_participated: list[str] = Field(default_factory=list)
    error_log: dict[str, Any] | list[Any] | None = None


class Simulation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None
    config: dict[str, Any]
    status: str = "running"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    simulated_duration: timedelta | None = None
    real_duration: timedelta | None = None
    total_conversations: int = 0
    total_turns: int = 0
    total_tokens: int = 0
    total_cost: Decimal = Decimal("0")
    total_artifacts: int = 0
    total_management_flags: int = 0
    agents_participated: list[str] = Field(default_factory=list)
    error_log: dict[str, Any] | list[Any] | None = None
    created_at: datetime | None = None


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
    reflection: ReflectionScheduleConfig = ReflectionScheduleConfig()


# ── Admin API Response Models ──────────────────────────────────

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Generic paginated response wrapper."""

    items: list[T]
    total: int
    limit: int
    offset: int


class PersonalityTraits(BaseModel):
    chattiness: float = 0.0
    initiative: float = 0.0
    interrupt_tendency: float = 0.0
    eavesdrop_tendency: float = 0.0
    closing_weight: float = 0.0


class AgentSummary(BaseModel):
    id: str
    display_name: str
    role: str = ""
    color: str = "#888888"
    status: str
    conversation_model: str = ""
    building_model: str = ""
    total_cost: str = "0"
    message_count: int = 0
    conversation_count: int = 0
    artifact_count: int = 0
    personality_traits: PersonalityTraits = PersonalityTraits()


class AgentDetail(AgentSummary):
    voice: str | None = None
    behaviors: dict[str, Any] = {}


class SystemPromptLayer(BaseModel):
    name: str
    content: str
    token_count: int = 0


class SystemPromptResponse(BaseModel):
    assembled_prompt: str
    layers: list[SystemPromptLayer] = []
    total_tokens: int = 0


class CoreMemoryVersionEntry(BaseModel):
    version: int
    content: str
    changed_at: str | None = None
    change_reason: str | None = None


class CoreMemoryResponse(BaseModel):
    current_content: str = ""
    current_version: int = 0
    token_count: int = 0
    last_updated: str | None = None
    version_history: list[CoreMemoryVersionEntry] = []


class CostByDay(BaseModel):
    date: str
    cost: str = "0"


class CostByType(BaseModel):
    type: str
    cost: str = "0"
    tokens: int = 0


class CostBreakdownResponse(BaseModel):
    by_day: list[CostByDay] = []
    by_type: list[CostByType] = []
    total: str = "0"
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class TimelineEvent(BaseModel):
    timestamp: str | None = None
    event_type: str
    agent_id: str | None = None
    details: dict[str, Any] = {}


class ConversationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    simulation_id: uuid.UUID | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    trigger_type: str
    trigger_details: dict[str, Any] | None = None
    initial_energy: float
    final_energy: float | None = None
    turn_count: int = 0
    participating_agents: list[str]
    topics_discussed: list[str] | None = None
    closed_by: str | None = None
    location: str | None = None
    energy_history: list[dict[str, Any]] = []
    transcript: str | None = None
    total_tokens: int = 0
    total_cost: str = "0"


class TurnDetail(BaseModel):
    turn_number: int
    selected_agent_id: str
    was_interrupt: bool = False
    agent_scores: dict[str, Any] = {}
    detected_topic: str | None = None
    previous_speaker_id: str | None = None
    conversation_energy: float | None = None
    timestamp: datetime | None = None


class EvalRunRequest(BaseModel):
    eval_suite: str = "full"
    categories: list[str] | None = None


class EvalRunResponse(BaseModel):
    eval_run_id: str
    status: str = "running"


class EvalRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    simulation_id: uuid.UUID
    eval_suite: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    overall_score: Decimal | None = None
    cost: Decimal = Decimal("0")
    created_at: datetime | None = None


class EvalResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    eval_run_id: uuid.UUID
    category: str
    score: Decimal | None = None
    reasoning: str | None = None
    evidence: dict[str, Any] | None = None
    sub_scores: dict[str, Any] | None = None
    tokens_used: int = 0
    cost: Decimal = Decimal("0")
    created_at: datetime | None = None


class EvalRunDetail(BaseModel):
    """Eval run with nested results for API responses."""
    id: uuid.UUID
    simulation_id: uuid.UUID
    eval_suite: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    overall_score: Decimal | None = None
    cost: Decimal = Decimal("0")
    created_at: datetime | None = None
    results: list[EvalResult] = []


class EvalComparisonResponse(BaseModel):
    """Side-by-side comparison of two eval runs."""
    run_a: EvalRunDetail
    run_b: EvalRunDetail


class EvalHistoryPoint(BaseModel):
    """Single data point for eval score history charts."""
    score: float | None = None
    created_at: str | None = None
    simulation_id: str
    eval_run_id: str


class EvalExportResponse(BaseModel):
    """Full eval export payload."""
    eval_run: EvalRun
    results: list[EvalResult]


class SimulationCostResponse(BaseModel):
    by_agent: list[dict[str, str]] = []
    total: str = "0"
    total_input_tokens: int = 0
    total_output_tokens: int = 0


# ── Agent Goals ────────────────────────────────────────────────────


class AgentGoal(BaseModel):
    """A persistent goal in an agent's goal queue (DB-backed)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent_id: str
    goal: str
    priority: int = 5
    status: str = "active"  # active, completed, abandoned, blocked
    source: str | None = "self"  # self, assigned, eval_loop, reflection
    progress_notes: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    parent_goal_id: uuid.UUID | None = None


# ── Versioned Agent Config ─────────────────────────────────────────


class AgentPromptVersion(BaseModel):
    """A versioned snapshot of an agent's prompt, behaviors, and config params."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    agent_id: str
    version: int
    system_prompt: str
    behaviors: dict[str, Any] = Field(default_factory=dict)
    config_params: dict[str, Any] = Field(default_factory=dict)
    change_reason: str | None = None
    source: str  # 'seed', 'manual', 'eval_loop'
    eval_run_id: uuid.UUID | None = None
    created_at: datetime | None = None


class ConversationParamVersion(BaseModel):
    """A versioned snapshot of conversation engine parameters."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: int
    params: dict[str, Any]
    change_reason: str | None = None
    source: str  # 'seed', 'manual', 'eval_loop'
    eval_run_id: uuid.UUID | None = None
    created_at: datetime | None = None


class ActiveConfig(BaseModel):
    """Pointer to the active prompt and conversation param versions for an agent."""

    model_config = ConfigDict(from_attributes=True)
    agent_id: str
    prompt_version: int
    conversation_param_version: int


# ── Relationships ──────────────────────────────────────────────────


class EvolutionEvent(BaseModel):
    """A single event in a relationship's evolution timeline."""

    timestamp: str
    event: str
    sentiment_before: float | None = None
    sentiment_after: float | None = None
    trust_before: float | None = None
    trust_after: float | None = None


class Relationship(BaseModel):
    """Read model for an agent relationship."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    simulation_id: uuid.UUID
    agent_id: str
    target_agent_id: str
    sentiment_score: Decimal | None = None
    trust_score: Decimal | None = None
    interaction_count: int = 0
    last_interaction_at: datetime | None = None
    relationship_summary: str | None = None
    evolution_log: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime | None = None
    created_at: datetime | None = None


class RelationshipCreate(BaseModel):
    simulation_id: uuid.UUID
    agent_id: str
    target_agent_id: str
    sentiment_score: Decimal | None = None
    trust_score: Decimal | None = None
    interaction_count: int = 0
    relationship_summary: str | None = None


class RelationshipUpdate(BaseModel):
    sentiment_score: Decimal | None = None
    trust_score: Decimal | None = None
    interaction_count: int | None = None
    relationship_summary: str | None = None


# ── Eval Analysis ──────────────────────────────────────────────


class ProposedChange(BaseModel):
    """A single change proposal from the eval analyzer."""

    type: str  # prompt_change, param_change, conversation_config_change, technical_issue
    agent_id: str | None = None
    section: str | None = None
    param_path: str | None = None
    current_value: Any | None = None
    proposed_value: Any | None = None
    current_text: str | None = None
    proposed_text: str | None = None
    title: str | None = None
    body: str | None = None
    labels: list[str] | None = None
    severity: str | None = None
    reasoning: str = ""


class AnalysisResult(BaseModel):
    """Result of eval analysis — structured change proposals."""

    summary: str = ""
    confidence: float = 0.0
    proposals: list[ProposedChange] = Field(default_factory=list)
    trend_data: dict[str, Any] | None = None


class EvalAnalysis(BaseModel):
    """Stored eval analysis record."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    eval_run_id: uuid.UUID
    summary: str | None = None
    confidence: Decimal | None = None
    proposals: list[dict[str, Any]] = Field(default_factory=list)
    trend_data: dict[str, Any] | None = None
    created_at: datetime | None = None


# ── Evolution Loop ─────────────────────────────────────────────


class EvolutionConfig(BaseModel):
    """Configuration for an evolution loop run."""

    max_cycles: int = 5
    auto_apply: bool = False
    cost_cap_per_cycle: float = 5.0
    convergence_threshold: float = 2.0
    convergence_window: int = 3
    regression_threshold: float = 10.0


class EvolutionCycle(BaseModel):
    """A single cycle in an evolution loop run."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    loop_run_id: uuid.UUID
    cycle_number: int
    simulation_id: uuid.UUID | None = None
    eval_run_id: uuid.UUID | None = None
    overall_score: Decimal | None = None
    score_delta: Decimal | None = None
    changes_applied: int = 0
    issues_filed: int = 0
    config_version_before: int | None = None
    config_version_after: int | None = None
    status: str = "running"
    cost: Decimal = Decimal("0")
    created_at: datetime | None = None


class CycleResult(BaseModel):
    """In-memory result of a single evolution cycle."""

    cycle_number: int
    simulation_id: uuid.UUID | None = None
    eval_run_id: uuid.UUID | None = None
    overall_score: float | None = None
    changes_applied: int = 0
    issues_filed: int = 0
    cost: float = 0.0
    status: str = "completed"


class EvolutionReport(BaseModel):
    """Final report of an evolution loop run."""

    loop_run_id: uuid.UUID
    cycles: list[CycleResult] = Field(default_factory=list)
    baseline_score: float | None = None
    final_score: float | None = None
    total_cost: float = 0.0
    total_cycles: int = 0
    stop_reason: str = ""  # completed, converged, regressed, cost_cap


# ── Phase Assertions ───────────────────────────────────────────


class AssertionResult(BaseModel):
    """Outcome of a single assertion check."""

    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    severity: str = "warning"  # "error", "warning", "info"
    error_message: str | None = None


class AssertionDefinition(BaseModel):
    """Definition of an assertion from seed YAML or config."""

    type: str  # conversation, tool, memory, relationship, cost, safety
    severity: str = "warning"
    # Type-specific fields
    min_turns: int | None = None
    required_participants: list[str] | None = None
    any_of: list[str] | None = None
    all_of: list[str] | None = None
    recall_created: bool | None = None
    core_memory_updated: bool | None = None
    max_cost: float | None = None
    max_management_severity: int | None = None
    interaction_count_increased: bool | None = None

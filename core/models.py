"""Pydantic models for all database tables."""

from __future__ import annotations

import uuid  # noqa: TC003
from datetime import datetime  # noqa: TC003
from decimal import Decimal  # noqa: TC003
from typing import Any

from pydantic import BaseModel, ConfigDict

# ── Agents ──────────────────────────────────────────────────────

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


class CoreMemoryUpsert(BaseModel):
    content: str
    token_count: int
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
    role: str
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


# ── Conversations ───────────────────────────────────────────────

class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    started_at: datetime | None = None
    ended_at: datetime | None = None
    trigger_type: str
    trigger_details: dict[str, Any] | None = None
    initial_energy: float
    final_energy: float | None = None
    turn_count: int = 0
    participating_agents: Any
    topics_discussed: Any | None = None
    closed_by: str | None = None
    location: str | None = None
    audience_events_during: int = 0
    config_hash: str | None = None


class ConversationCreate(BaseModel):
    id: uuid.UUID | None = None
    trigger_type: str
    trigger_details: dict[str, Any] | None = None
    initial_energy: float
    participating_agents: Any
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
    active_agents: Any | None = None
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
    active_agents: Any | None = None
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
    objects: Any | None = None
    built_by: list[str] | None = None
    built_date: datetime | None = None
    description: str | None = None
    proposal_votes: Any | None = None
    tileset_url: str | None = None


class WorldChunkCreate(BaseModel):
    name: str
    x_offset: int
    y_offset: int
    width: int
    height: int
    tile_data: dict[str, Any]
    objects: Any | None = None
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

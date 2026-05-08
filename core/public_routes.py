"""Public API endpoints for the website.

Read-only endpoints for agents, conversations, blog, evals, world,
challenges, lore, and stats. Chat and challenge submission are rate-limited
by IP via Redis counters.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.auth.dependencies import get_current_user
from core.constants import LIVE_SIMULATION_ID
from core.models import (
    Challenge,
    Conversation,
    User,
    WorldChunk,
    WorldEvent,
)
from core.repos.conversation_repo import ConversationRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ── Helpers ──────────────────────────────────────────────────────


def _get_services():
    from core.main import app

    return app.state.services


def _get_db():
    return _get_services().db


def _get_redis():
    return _get_services().redis


def _get_registry():
    return _get_services().agent_registry


async def _check_rate_limit(
    redis,
    key: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    if redis is None:
        return True
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_seconds)
    return current <= max_requests


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Request/Response Models ─────────────────────────────────────


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    agent_id: str
    message: str
    timestamp: str


class ChallengeSubmitRequest(BaseModel):
    description: str
    category: str | None = None
    submitter_name: str | None = None


class ChallengeResponse(BaseModel):
    id: int
    description: str
    submitted_by: str | None = None
    status: str = "pending"
    assigned_agents: list[str] | None = None
    result: str | None = None
    cost_estimate: float | None = None
    actual_cost: float | None = None
    votes: int = 0
    category: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class AgentPublicProfile(BaseModel):
    id: str
    display_name: str
    role: str = ""
    color: str = "#888888"
    status: str = "active"
    conversation_model: str = ""
    building_model: str = ""
    chattiness: float = 0.0
    initiative: float = 0.0
    voice: str | None = None
    behaviors: list[str] = []
    interrupt_tendency: float = 0.0
    eavesdrop_tendency: float = 0.0
    closing_weight: float = 0.0
    total_cost: str = "0"
    message_count: int = 0
    conversation_count: int = 0
    artifact_count: int = 0


class StatsResponse(BaseModel):
    total_simulations: int = 0
    total_agents: int = 0
    total_cost: str = "0"
    total_conversations: int = 0


class LoreEventResponse(BaseModel):
    id: int
    event_type: str | None = None
    description: str | None = None
    agents_involved: list[str] | None = None
    audience_participation: bool = False
    created_at: str | None = None


class ConversationSummary(BaseModel):
    id: str
    simulation_id: str | None = None
    trigger_type: str
    participating_agents: list[str]
    topics_discussed: list[str] | None = None
    turn_count: int = 0
    location: str | None = None
    started_at: str | None = None


class ConversationDetailResponse(BaseModel):
    id: str
    simulation_id: str | None = None
    trigger_type: str
    trigger_details: dict[str, Any] | None = None
    participating_agents: list[str]
    topics_discussed: list[str] | None = None
    turn_count: int = 0
    closed_by: str | None = None
    location: str | None = None
    initial_energy: float = 0.0
    final_energy: float | None = None
    started_at: str | None = None
    ended_at: str | None = None
    energy_history: list[dict[str, Any]] = []
    transcript: str | None = None
    total_tokens: int = 0
    total_cost: str = "0"


class SelectionLogResponse(BaseModel):
    turn_number: int
    selected_agent_id: str
    was_interrupt: bool = False
    agent_scores: dict[str, Any] = {}
    detected_topic: str | None = None
    previous_speaker_id: str | None = None
    conversation_energy: float | None = None


class EvalSummaryItem(BaseModel):
    category: str
    score: float | None = None


class EvalHistoryItem(BaseModel):
    score: float | None = None
    created_at: str | None = None


class PublicEvalRun(BaseModel):
    id: str
    simulation_id: str
    simulation_name: str | None = None
    date: str
    overall_score: float | None = None
    cost: float = 0
    model_versions: dict[str, str] = {}
    category_scores: dict[str, float | None] = {}


class PublicEvalRunDetail(PublicEvalRun):
    status: str = ""
    results: list[dict[str, Any]] = []


class BlogPostSummary(BaseModel):
    slug: str
    title: str
    date: str
    excerpt: str
    tags: list[str] = []


class BlogPostDetail(BlogPostSummary):
    content: str


# ── Serialization helpers ────────────────────────────────────────


def _challenge_to_response(c: Challenge) -> ChallengeResponse:
    return ChallengeResponse(
        id=c.id,
        description=c.description,
        submitted_by=c.submitted_by,
        status=c.status,
        assigned_agents=c.assigned_agents,
        result=c.result,
        cost_estimate=c.cost_estimate,
        actual_cost=c.actual_cost,
        votes=c.votes,
        category=c.category,
        created_at=c.created_at.isoformat() if c.created_at else None,
        completed_at=c.completed_at.isoformat() if c.completed_at else None,
    )


def _conversation_to_summary(c: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=str(c.id),
        simulation_id=str(c.simulation_id) if c.simulation_id else None,
        trigger_type=c.trigger_type,
        participating_agents=c.participating_agents,
        topics_discussed=c.topics_discussed,
        turn_count=c.turn_count,
        location=c.location,
        started_at=c.started_at.isoformat() if c.started_at else None,
    )


def _conversation_to_detail(
    c: Conversation,
    *,
    energy_history: list[dict[str, Any]] | None = None,
    transcript: str | None = None,
    total_tokens: int = 0,
    total_cost: str = "0",
) -> ConversationDetailResponse:
    return ConversationDetailResponse(
        id=str(c.id),
        simulation_id=str(c.simulation_id) if c.simulation_id else None,
        trigger_type=c.trigger_type,
        trigger_details=c.trigger_details,
        participating_agents=c.participating_agents,
        topics_discussed=c.topics_discussed,
        turn_count=c.turn_count,
        closed_by=c.closed_by,
        location=c.location,
        initial_energy=c.initial_energy,
        final_energy=c.final_energy,
        started_at=c.started_at.isoformat() if c.started_at else None,
        ended_at=c.ended_at.isoformat() if c.ended_at else None,
        energy_history=energy_history or [],
        transcript=transcript,
        total_tokens=total_tokens,
        total_cost=total_cost,
    )


def _event_to_response(e: WorldEvent) -> LoreEventResponse:
    return LoreEventResponse(
        id=e.id,
        event_type=e.event_type,
        description=e.description,
        agents_involved=e.agents_involved,
        audience_participation=e.audience_participation,
        created_at=e.created_at.isoformat() if e.created_at else None,
    )


# ── Agent Endpoints ──────────────────────────────────────────────


async def _build_agent_profile(
    a: Any,
    *,
    db: Any,
    services: Any,
    simulation_id: uuid.UUID | None,
) -> AgentPublicProfile:
    """Assemble an AgentPublicProfile with cost and activity totals."""
    from core.repos.cost_repo import CostRepo

    cost_repo = CostRepo(db)
    costs = await cost_repo.get_costs_by_agent(a.id, simulation_id=simulation_id)
    total_cost = sum(c.amount for c in costs if c.amount) if costs else 0

    conversation_count = 0
    artifact_count = 0
    if db is not None:
        conversation_count = await ConversationRepo(db).count_by_agent(
            a.id, simulation_id=simulation_id
        )
    if services and getattr(services, "artifact_repo", None):
        artifact_count = await services.artifact_repo.count_by_agent(
            a.id, simulation_id=simulation_id
        )

    return AgentPublicProfile(
        id=a.id,
        display_name=a.display_name,
        role=a.role,
        color=a.color_hex,
        status=a.status.value if hasattr(a.status, "value") else str(a.status),
        conversation_model=a.model_conversation,
        building_model=a.model_building,
        chattiness=a.chattiness,
        initiative=a.initiative,
        voice=a.voice_id,
        behaviors=list(a.behaviors.keys()) if a.behaviors else [],
        interrupt_tendency=a.interrupt_tendency,
        eavesdrop_tendency=a.eavesdrop_tendency,
        closing_weight=a.closing_weight,
        total_cost=f"{total_cost:.6f}",
        message_count=len(costs) if costs else 0,
        conversation_count=conversation_count,
        artifact_count=artifact_count,
    )


@router.get("/agents")
async def get_agents(
    simulation_id: str | None = Query(default=None),
) -> list[AgentPublicProfile]:
    registry = _get_registry()
    db = _get_db()
    services = _get_services()
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    agents = registry.get_all_agents()
    return [
        await _build_agent_profile(a, db=db, services=services, simulation_id=sim_id)
        for a in agents
    ]


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
) -> AgentPublicProfile:
    registry = _get_registry()
    db = _get_db()
    services = _get_services()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    return await _build_agent_profile(agent, db=db, services=services, simulation_id=sim_id)


@router.get("/agents/{agent_id}/system-prompt")
async def get_agent_system_prompt(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Current assembled system prompt (all 3 layers) with token counts."""
    registry = _get_registry()
    db = _get_db()
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    from core.repos.memory_repo import MemoryRepo
    from core.system_prompt import INFRASTRUCTURE_PROMPT

    memory_repo = MemoryRepo(db)
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    core_mem = await memory_repo.get_core_memory(agent_id, simulation_id=sim_id)

    raw_layers = {
        "Infrastructure": INFRASTRUCTURE_PROMPT,
        "Character": agent.system_prompt,
        "Memory Context": core_mem.content if core_mem else "",
    }
    assembled = "\n\n".join(v for v in raw_layers.values() if v)

    def _estimate_tokens(text: str) -> int:
        return len(text) // 4 if text else 0

    layers = [
        {"name": name, "content": content, "token_count": _estimate_tokens(content)}
        for name, content in raw_layers.items()
        if content
    ]
    total_tokens = sum(layer["token_count"] for layer in layers)

    return {
        "assembled_prompt": assembled,
        "layers": layers,
        "total_tokens": total_tokens,
    }


@router.get("/agents/{agent_id}/costs")
async def get_agent_costs(
    agent_id: str,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    simulation_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Cost breakdown: by day, by type, total."""
    from datetime import datetime as dt

    db = _get_db()
    from core.repos.cost_repo import CostRepo

    cost_repo = CostRepo(db)

    parsed_from = dt.fromisoformat(from_date) if from_date else None
    parsed_to = dt.fromisoformat(to_date) if to_date else None
    sim_id = uuid.UUID(simulation_id) if simulation_id else None

    data = await cost_repo.get_costs_by_agent_grouped(
        agent_id,
        from_date=parsed_from,
        to_date=parsed_to,
        simulation_id=sim_id,
    )

    by_day = [
        {"date": d.get("day", ""), "cost": d.get("total", "0")} for d in data.get("by_day", [])
    ]
    by_type = [
        {"type": d.get("type", ""), "cost": d.get("total", "0"), "tokens": int(d.get("tokens", 0))}
        for d in data.get("by_type", [])
    ]

    return {
        "by_day": by_day,
        "by_type": by_type,
        "total": data.get("total", "0"),
        "total_input_tokens": data.get("total_input_tokens", 0),
        "total_output_tokens": data.get("total_output_tokens", 0),
    }


@router.get("/agents/{agent_id}/journal")
async def get_agent_journal(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    db = _get_db()
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    if sim_id is None:
        rows = await db.fetch(
            """SELECT * FROM journal_entries
               WHERE agent_id = $1
               ORDER BY created_at DESC
               LIMIT $2 OFFSET $3""",
            agent_id,
            limit,
            offset,
        )
    else:
        rows = await db.fetch(
            """SELECT * FROM journal_entries
               WHERE agent_id = $1 AND simulation_id = $4
               ORDER BY created_at DESC
               LIMIT $2 OFFSET $3""",
            agent_id,
            limit,
            offset,
            sim_id,
        )
    return [
        {
            "id": r["id"],
            "agent_id": r["agent_id"],
            "reflection_type": r["reflection_type"],
            "content": r["content"],
            "image_url": r.get("image_url"),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/agents/{agent_id}/relationships")
async def get_agent_relationships(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    svc = _get_services()
    if not svc.relationship_repo:
        return []
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    relationships = await svc.relationship_repo.get_all_for_agent(
        sim_id,
        agent_id,
    )
    return [
        {
            "id": str(r.id),
            "target_agent_id": r.target_agent_id,
            "sentiment_score": float(r.sentiment_score) if r.sentiment_score is not None else 0,
            "trust_score": float(r.trust_score) if r.trust_score is not None else 0,
            "interaction_count": r.interaction_count,
            "relationship_summary": r.relationship_summary,
        }
        for r in relationships
    ]


@router.get("/agents/{agent_id}/conversations")
async def get_agent_conversations(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    db = _get_db()
    repo = ConversationRepo(db)
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    convs, total = await repo.get_conversations_by_agent(
        agent_id,
        simulation_id=sim_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_conversation_to_summary(c) for c in convs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/agents/{agent_id}/artifacts")
async def get_agent_artifacts(
    agent_id: str,
    artifact_type: str | None = Query(None, alias="type"),
    simulation_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    svc = _get_services()
    if not svc.artifact_repo:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    artifacts, total = await svc.artifact_repo.get_all_artifacts(
        simulation_id=sim_id,
        agent_ids=[agent_id],
        artifact_type=artifact_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "id": str(a.id),
                "agent_id": a.agent_id,
                "tool_name": a.tool_name,
                "artifact_type": a.artifact_type,
                "status": a.status,
                "summary": _artifact_summary(a.artifact_type, a.tool_input),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/agents/{agent_id}/core-memory")
async def get_agent_core_memory(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Current core memory content with version history."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo

    memory_repo = MemoryRepo(db)

    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    current = await memory_repo.get_core_memory(agent_id, simulation_id=sim_id)
    history = await memory_repo.get_core_memory_history(agent_id, simulation_id=sim_id)

    version_history = [
        {
            "version": h.version,
            "content": h.content,
            "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            "change_reason": h.change_reason,
        }
        for h in history
    ]

    return {
        "current_content": current.content if current else "",
        "current_version": current.version if current else 0,
        "token_count": current.token_count if current else 0,
        "last_updated": (
            current.last_updated.isoformat() if current and current.last_updated else None
        ),
        "version_history": version_history,
    }


@router.get("/agents/{agent_id}/recall-memories")
async def get_agent_recall_memories(
    agent_id: str,
    search: str | None = Query(default=None),
    simulation_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Paginated recall memories (read-only, embeddings hidden). Supports keyword search."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo

    memory_repo = MemoryRepo(db)

    sim_id = uuid.UUID(simulation_id) if simulation_id else None

    if search:
        memories, total = await memory_repo.search_recall_memories_by_keyword(
            agent_id,
            search,
            limit=limit,
            offset=offset,
            simulation_id=sim_id,
        )
    else:
        memories, total = await memory_repo.get_recall_memories_paginated(
            agent_id,
            limit=limit,
            offset=offset,
            simulation_id=sim_id,
        )

    items = []
    for m in memories:
        d = m.model_dump()
        d.pop("embedding", None)
        # Serialize datetimes
        for key in ("created_at", "updated_at", "last_accessed"):
            if key in d and hasattr(d[key], "isoformat"):
                d[key] = d[key].isoformat()
        # Serialize UUIDs
        for key in ("id", "simulation_id"):
            if key in d and d[key] is not None:
                d[key] = str(d[key])
        items.append(d)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/agents/{agent_id}/evolution")
async def get_agent_evolution(
    agent_id: str,
    simulation_id: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    svc = _get_services()
    if not svc.config_version_repo:
        return []
    sim_id = uuid.UUID(simulation_id) if simulation_id else None
    versions = await svc.config_version_repo.get_prompt_history(
        agent_id,
        simulation_id=sim_id,
    )
    return [
        {
            "id": str(v.id),
            "version": v.version,
            "change_reason": v.change_reason,
            "source": v.source if v.source in ("manual", "system", "evolution") else "system",
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
        if v.source in ("manual", "system", "evolution")
    ]


@router.post("/agents/{agent_id}/chat")
async def chat_with_agent(
    agent_id: str,
    req: ChatRequest,
    request: Request,
) -> ChatResponse:
    svc = _get_services()
    ip = _client_ip(request)
    allowed = await _check_rate_limit(
        svc.redis,
        f"ratelimit:chat:{ip}:{agent_id}",
        10,
        3600,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded (10/hr)")

    registry = _get_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not svc.llm_client:
        raise HTTPException(status_code=503, detail="LLM client not available")

    from datetime import UTC, datetime

    response = await svc.llm_client.chat(
        model=agent.model_conversation,
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are {agent.display_name}, {agent.role}. "
                    f"{agent.system_prompt[:500] if agent.system_prompt else ''}"
                ),
            },
            {"role": "user", "content": req.message},
        ],
    )
    return ChatResponse(
        agent_id=agent_id,
        message=response.content,
        timestamp=datetime.now(UTC).isoformat(),
    )


# ── Conversation Endpoints ───────────────────────────────────────


@router.get("/conversations")
async def get_conversations(
    simulation_id: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    db = _get_db()
    if simulation_id:
        sim_id = uuid.UUID(simulation_id)
        total = await db.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE simulation_id = $1",
            sim_id,
        )
        rows = await db.fetch(
            """SELECT * FROM conversations
               WHERE simulation_id = $3
               ORDER BY started_at DESC
               LIMIT $1 OFFSET $2""",
            limit,
            offset,
            sim_id,
        )
    else:
        total = await db.fetchval("SELECT COUNT(*) FROM conversations")
        rows = await db.fetch(
            """SELECT * FROM conversations
               ORDER BY started_at DESC
               LIMIT $1 OFFSET $2""",
            limit,
            offset,
        )
    items = []
    for r in rows:
        d = dict(r)
        for key in ("trigger_details", "participating_agents", "topics_discussed"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key])
        c = Conversation(**d)
        items.append(_conversation_to_summary(c))
    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> ConversationDetailResponse:
    db = _get_db()
    repo = ConversationRepo(db)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID",
        ) from exc
    conv = await repo.get(conv_uuid)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Fetch transcript
    from core.repos.transcript_repo import TranscriptRepo

    transcript_repo = TranscriptRepo(db)
    transcript_record = await transcript_repo.get_by_conversation(conv_uuid)
    transcript_text = transcript_record.content if transcript_record else None
    total_tokens = len(transcript_text) // 4 if transcript_text else 0

    # Fetch energy history
    energy_log = await repo.get_energy_log(conv_uuid)

    return _conversation_to_detail(
        conv,
        energy_history=energy_log,
        transcript=transcript_text,
        total_tokens=total_tokens,
    )


@router.get("/conversations/{conversation_id}/selections")
async def get_conversation_selections(
    conversation_id: str,
) -> list[SelectionLogResponse]:
    db = _get_db()
    repo = ConversationRepo(db)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID",
        ) from exc
    logs = await repo.get_selection_log(conv_uuid)
    return [
        SelectionLogResponse(
            turn_number=log.turn_number,
            selected_agent_id=log.selected_agent_id,
            was_interrupt=log.was_interrupt,
            agent_scores=log.agent_scores,
            detected_topic=log.detected_topic,
            previous_speaker_id=log.previous_speaker_id,
            conversation_energy=log.conversation_energy,
        )
        for log in logs
    ]


@router.get("/conversations/{conversation_id}/turns")
async def get_conversation_turns(
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Turn-by-turn detail with selection scores."""
    db = _get_db()
    repo = ConversationRepo(db)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID",
        ) from exc
    logs = await repo.get_selection_log(conv_uuid)
    return [
        {
            "turn_number": log.turn_number,
            "selected_agent_id": log.selected_agent_id,
            "was_interrupt": log.was_interrupt,
            "agent_scores": log.agent_scores,
            "detected_topic": log.detected_topic,
            "previous_speaker_id": log.previous_speaker_id,
            "conversation_energy": log.conversation_energy,
            "timestamp": (
                log.timestamp.isoformat() if hasattr(log, "timestamp") and log.timestamp else None
            ),
        }
        for log in logs
    ]


@router.get("/conversations/{conversation_id}/management-flags")
async def get_conversation_management_flags(
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Management shadow flags for this conversation."""
    db = _get_db()
    repo = ConversationRepo(db)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID",
        ) from exc
    return await repo.get_management_flags(conv_uuid)


@router.get("/conversations/{conversation_id}/artifacts")
async def get_conversation_artifacts(
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Tool invocation artifacts for this conversation."""
    db = _get_db()
    repo = ConversationRepo(db)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID",
        ) from exc
    return await repo.get_artifacts(conv_uuid)


@router.get("/conversations/{conversation_id}/interrupts")
async def get_conversation_interrupts(
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Interrupt events for this conversation."""
    db = _get_db()
    repo = ConversationRepo(db)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid conversation ID",
        ) from exc
    return await repo.get_interrupts(conv_uuid)


# ── Blog Endpoints ──────────────────────────────────────────────


@router.get("/blog")
async def get_blog_posts() -> list[BlogPostSummary]:
    from core.blog import list_posts

    return list_posts()


@router.get("/blog/{slug}")
async def get_blog_post(slug: str) -> BlogPostDetail:
    from core.blog import get_post

    post = get_post(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return post


# ── Eval Prompt Endpoints ──────────────────────────────────────


@router.get("/evals/prompts")
async def get_eval_prompts() -> list[dict[str, Any]]:
    """Return all eval category prompts for public display."""
    from core.eval.prompt_loader import discover_categories, load_prompt

    categories = discover_categories()
    result = []
    for cat in categories:
        try:
            data = load_prompt(cat)
            result.append(
                {
                    "name": data.get("name", cat),
                    "description": data.get("description", ""),
                    "system": data.get("system", ""),
                    "rubric": data.get("rubric", {}),
                    "sub_scores": data.get("sub_scores", []),
                    "output_schema": data.get("output_schema", {}),
                    "model": data.get("model", ""),
                    "temperature": data.get("temperature"),
                    "max_tokens": data.get("max_tokens"),
                }
            )
        except Exception:
            logger.warning("Failed to load eval prompt for %s", cat)
    return result


@router.get("/evals/prompts/{category}")
async def get_eval_prompt(category: str) -> dict[str, Any]:
    """Return a single eval category prompt."""
    from core.eval.prompt_loader import load_prompt

    try:
        data = load_prompt(category)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Eval prompt '{category}' not found",
        ) from exc
    return {
        "name": data.get("name", category),
        "description": data.get("description", ""),
        "system": data.get("system", ""),
        "rubric": data.get("rubric", {}),
        "sub_scores": data.get("sub_scores", []),
        "output_schema": data.get("output_schema", {}),
        "model": data.get("model", ""),
        "temperature": data.get("temperature"),
        "max_tokens": data.get("max_tokens"),
    }


# ── Eval Endpoints ──────────────────────────────────────────────


@router.get("/evals/summary")
async def get_evals_summary() -> list[EvalSummaryItem]:
    db = _get_db()
    if not db:
        return []
    rows = await db.fetch(
        """SELECT DISTINCT ON (category) category, score
           FROM eval_results er
           JOIN eval_runs e ON e.id = er.eval_run_id
           ORDER BY category, er.created_at DESC""",
    )
    return [
        EvalSummaryItem(
            category=r["category"],
            score=float(r["score"]) if r["score"] is not None else None,
        )
        for r in rows
    ]


@router.get("/evals/history")
async def get_evals_history(
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[EvalHistoryItem]:
    db = _get_db()
    if not db:
        return []
    if category:
        rows = await db.fetch(
            """SELECT er.score, er.created_at FROM eval_results er
               JOIN eval_runs e ON e.id = er.eval_run_id
               WHERE er.category = $1
               ORDER BY er.created_at DESC LIMIT $2""",
            category,
            limit,
        )
    else:
        rows = await db.fetch(
            """SELECT er.score, er.created_at FROM eval_results er
               JOIN eval_runs e ON e.id = er.eval_run_id
               ORDER BY er.created_at DESC LIMIT $1""",
            limit,
        )
    return [
        EvalHistoryItem(
            score=float(r["score"]) if r["score"] is not None else None,
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
        )
        for r in rows
    ]


@router.get("/evals/categories")
async def get_eval_categories() -> list[str]:
    db = _get_db()
    if not db:
        return []
    rows = await db.fetch(
        """SELECT DISTINCT er.category FROM eval_results er
           ORDER BY er.category""",
    )
    return [r["category"] for r in rows]


@router.get("/evals/runs")
async def get_eval_runs(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    simulation_id: str | None = Query(default=None),
) -> list[PublicEvalRun]:
    db = _get_db()
    if not db:
        return []
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    sim_uuid = uuid.UUID(simulation_id) if simulation_id else None
    runs = await eval_repo.get_all_eval_runs(
        limit=limit,
        offset=offset,
        simulation_id=sim_uuid,
    )

    # Batch-fetch simulation names for all unique simulation IDs
    sim_ids = list({run.simulation_id for run in runs})
    sim_names: dict[uuid.UUID, str] = {}
    if sim_ids:
        name_rows = await db.fetch(
            "SELECT id, name FROM simulations WHERE id = ANY($1::uuid[])",
            sim_ids,
        )
        sim_names = {r["id"]: r["name"] for r in name_rows}

    result = []
    for run in runs:
        results = await eval_repo.get_eval_results(run.id)
        # Flatten model_versions: agent_id -> conversation model for display
        flat_versions: dict[str, str] = {}
        for agent_id, models in (run.model_versions or {}).items():
            if isinstance(models, dict):
                flat_versions[agent_id] = models.get("conversation", "unknown")
            else:
                flat_versions[agent_id] = str(models)
        category_scores = {
            r.category: float(r.score) if r.score is not None else None for r in results
        }
        result.append(
            PublicEvalRun(
                id=str(run.id),
                simulation_id=str(run.simulation_id),
                simulation_name=sim_names.get(run.simulation_id),
                date=run.started_at.isoformat() if run.started_at else "",
                overall_score=float(run.overall_score) if run.overall_score is not None else None,
                cost=float(run.cost),
                model_versions=flat_versions,
                category_scores=category_scores,
            )
        )
    return result


@router.get("/evals/latest")
async def get_latest_eval_run(
    simulation_id: str | None = Query(default=None),
) -> PublicEvalRun | None:
    db = _get_db()
    if not db:
        return None
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    sim_uuid = uuid.UUID(simulation_id) if simulation_id else None
    # Get most recent eval run; scoped if simulation_id provided.
    runs = await eval_repo.get_all_eval_runs(
        limit=1,
        offset=0,
        simulation_id=sim_uuid,
    )
    if not runs:
        return None
    run = runs[0]

    # Fetch simulation name
    sim_row = await db.fetchrow(
        "SELECT name FROM simulations WHERE id = $1",
        run.simulation_id,
    )
    sim_name = sim_row["name"] if sim_row else None

    results = await eval_repo.get_eval_results(run.id)
    flat_versions: dict[str, str] = {}
    for agent_id, models in (run.model_versions or {}).items():
        if isinstance(models, dict):
            flat_versions[agent_id] = models.get("conversation", "unknown")
        else:
            flat_versions[agent_id] = str(models)
    category_scores = {r.category: float(r.score) if r.score is not None else None for r in results}
    return PublicEvalRun(
        id=str(run.id),
        simulation_id=str(run.simulation_id),
        simulation_name=sim_name,
        date=run.started_at.isoformat() if run.started_at else "",
        overall_score=float(run.overall_score) if run.overall_score is not None else None,
        cost=float(run.cost),
        model_versions=flat_versions,
        category_scores=category_scores,
    )


@router.get("/evals/runs/{run_id}")
async def get_eval_run_detail(run_id: str) -> PublicEvalRunDetail:
    db = _get_db()
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    run = await eval_repo.get_eval_run(uuid.UUID(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")

    sim_row = await db.fetchrow(
        "SELECT name FROM simulations WHERE id = $1",
        run.simulation_id,
    )
    sim_name = sim_row["name"] if sim_row else None

    results = await eval_repo.get_eval_results(run.id)
    flat_versions: dict[str, str] = {}
    for agent_id, models in (run.model_versions or {}).items():
        if isinstance(models, dict):
            flat_versions[agent_id] = models.get("conversation", "unknown")
        else:
            flat_versions[agent_id] = str(models)
    category_scores = {r.category: float(r.score) if r.score is not None else None for r in results}
    return PublicEvalRunDetail(
        id=str(run.id),
        simulation_id=str(run.simulation_id),
        simulation_name=sim_name,
        date=run.started_at.isoformat() if run.started_at else "",
        overall_score=float(run.overall_score) if run.overall_score is not None else None,
        cost=float(run.cost),
        model_versions=flat_versions,
        category_scores=category_scores,
        status=run.status,
        results=[
            {"category": r.category, "score": float(r.score) if r.score is not None else None}
            for r in results
        ],
    )


# ── World & Challenge Endpoints ──────────────────────────────────


@router.get("/world/chunks")
async def get_world_chunks() -> list[dict[str, Any]]:
    # Intentional: /world is the live-show map only. Do not generalize to a
    # simulation_id query param without first deciding how non-live sims
    # should expose their world state (separate endpoint, different schema).
    svc = _get_services()
    if not svc.world_repo:
        return []
    rows = await svc.db.fetch(
        "SELECT * FROM world_chunks WHERE simulation_id = $1 ORDER BY id",
        LIVE_SIMULATION_ID,
    )
    results = []
    for r in rows:
        d = dict(r)
        for key in ("tile_data", "objects", "proposal_votes"):
            if isinstance(d.get(key), str):
                d[key] = json.loads(d[key])
        chunk = WorldChunk(**d)
        results.append(
            {
                "id": chunk.id,
                "name": chunk.name,
                "x": chunk.x_offset,
                "y": chunk.y_offset,
                "width": chunk.width,
                "height": chunk.height,
                "tiles": chunk.tile_data,
                "objects": chunk.objects or [],
            }
        )
    return results


@router.get("/challenges")
async def get_challenges(
    status: str | None = Query(None),
    category: str | None = Query(None),
    sort: str = Query("newest"),
) -> list[ChallengeResponse]:
    db = _get_db()
    clauses: list[str] = ["simulation_id = $1"]
    params: list[object] = [LIVE_SIMULATION_ID]
    idx = 2

    if status:
        clauses.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if category:
        clauses.append(f"category = ${idx}")
        params.append(category)
        idx += 1

    where = " WHERE " + " AND ".join(clauses)

    order_map = {
        "newest": "created_at DESC",
        "most_upvoted": "votes DESC",
        "status": "status ASC, created_at DESC",
    }
    order = order_map.get(sort, "created_at DESC")

    rows = await db.fetch(
        f"SELECT * FROM challenges{where} ORDER BY {order}",  # noqa: S608
        *params,
    )
    challenges = []
    for r in rows:
        c = Challenge(**dict(r))
        challenges.append(_challenge_to_response(c))
    return challenges


@router.post("/challenges")
async def submit_challenge(
    req: ChallengeSubmitRequest,
    request: Request,
) -> ChallengeResponse:
    svc = _get_services()
    ip = _client_ip(request)
    allowed = await _check_rate_limit(
        svc.redis,
        f"ratelimit:challenge:{ip}",
        5,
        3600,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded (5/hr)")

    db = _get_db()
    row = await db.fetchrow(
        """INSERT INTO challenges (description, submitted_by, source, category, votes, simulation_id)
           VALUES ($1, $2, 'website', $3, 0, $4)
           RETURNING *""",
        req.description,
        req.submitter_name,
        req.category,
        LIVE_SIMULATION_ID,
    )
    c = Challenge(**dict(row))
    return _challenge_to_response(c)


@router.post("/challenges/{challenge_id}/upvote")
async def upvote_challenge(
    challenge_id: int,
    request: Request,
) -> ChallengeResponse:
    svc = _get_services()
    ip = _client_ip(request)
    redis = svc.redis

    # Check if this IP already voted on this challenge
    if redis:
        vote_key = f"challenge_vote:{challenge_id}:{ip}"
        already_voted = await redis.get(vote_key)
        if already_voted:
            raise HTTPException(status_code=409, detail="Already voted on this challenge")
        # Mark as voted (no expiry — 1 vote per IP per challenge forever)
        await redis.set(vote_key, "1")

    db = _get_db()
    row = await db.fetchrow(
        """UPDATE challenges SET votes = votes + 1
           WHERE id = $1 AND simulation_id = $2 RETURNING *""",
        challenge_id,
        LIVE_SIMULATION_ID,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Challenge not found")
    c = Challenge(**dict(row))
    return _challenge_to_response(c)


# ── General Endpoints ────────────────────────────────────────────


@router.get("/stats")
async def get_stats() -> StatsResponse:
    db = _get_db()
    svc = _get_services()

    total_agents = len(svc.agent_registry.get_all_agents())

    sims = await db.fetchval("SELECT COUNT(*) FROM simulations") or 0
    convs = (
        await db.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE simulation_id = $1",
            LIVE_SIMULATION_ID,
        )
        or 0
    )
    total_cost_val = await db.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM cost_events WHERE simulation_id = $1",
        LIVE_SIMULATION_ID,
    )
    total_cost = str(total_cost_val) if total_cost_val else "0"

    return StatsResponse(
        total_simulations=sims,
        total_agents=total_agents,
        total_cost=total_cost,
        total_conversations=convs,
    )


@router.get("/lore")
async def get_lore(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    agent: str | None = Query(None),
    event_type: str | None = Query(None),
    simulation_id: str | None = Query(None),
) -> dict[str, Any]:
    db = _get_db()
    clauses: list[str] = []
    params: list[object] = []
    idx = 1

    if simulation_id:
        clauses.append(f"simulation_id = ${idx}")
        try:
            params.append(uuid.UUID(simulation_id))
        except ValueError:
            params.append(simulation_id)
        idx += 1
    if agent:
        clauses.append(f"${idx} = ANY(agents_involved)")
        params.append(agent)
        idx += 1
    if event_type:
        clauses.append(f"event_type = ${idx}")
        params.append(event_type)
        idx += 1

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    total = await db.fetchval(
        f"SELECT COUNT(*) FROM world_events{where}",  # noqa: S608
        *params,
    )

    query = (
        f"SELECT * FROM world_events{where}"  # noqa: S608
        f" ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
    )
    rows = await db.fetch(query, *params, limit, offset)

    items = [_event_to_response(WorldEvent(**dict(r))) for r in rows]

    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


# ── Public Simulation Endpoints (read-only) ─────────────────────


@router.get("/simulations")
async def get_simulations(
    status: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_live: bool = Query(default=False),
    is_featured: bool | None = Query(default=None),
) -> dict[str, Any]:
    """List all simulations (public read-only). Optionally filter by status.

    The seeded live channel row is excluded by default; pass include_live=true
    to include it (it represents a permanent channel, not a discrete run).
    Pass is_featured=true to retrieve only the curated set surfaced on the home
    page.
    """
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    simulations = await sim_repo.list(
        status=status,
        limit=limit,
        offset=offset,
        include_live=include_live,
        is_featured=is_featured,
    )
    total = await sim_repo.count(
        status=status,
        include_live=include_live,
        is_featured=is_featured,
    )

    return {
        "items": [
            {
                "id": str(s.id),
                "name": s.name,
                "description": s.description,
                "status": s.status,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "real_duration": str(s.real_duration) if s.real_duration else None,
                "total_conversations": s.total_conversations,
                "total_turns": s.total_turns,
                "total_cost": s.total_cost,
                "total_artifacts": s.total_artifacts,
                "agents_participated": s.agents_participated,
                "is_featured": s.is_featured,
                "video_url": s.video_url,
            }
            for s in simulations
        ],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/simulations/{sim_id}")
async def get_simulation_detail(sim_id: str) -> dict[str, Any]:
    """Public simulation detail.

    Totals (conversations/turns/cost/artifacts/flags) are computed live from
    source data so they match the executive summary in the report. The
    denormalized fields on the simulations row can drift.
    """
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)

    sim_uuid = uuid.UUID(sim_id)
    sim = await sim_repo.get(sim_uuid)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

    total_conversations = (
        await db.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE simulation_id = $1",
            sim_uuid,
        )
        or 0
    )
    total_turns = (
        await db.fetchval(
            """
        SELECT COALESCE(SUM(turn_count), 0) FROM conversations
        WHERE simulation_id = $1
        """,
            sim_uuid,
        )
        or 0
    )
    total_cost_val = await db.fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM cost_events WHERE simulation_id = $1",
        sim_uuid,
    )
    total_cost = str(total_cost_val) if total_cost_val is not None else "0"
    total_artifacts = (
        await db.fetchval(
            "SELECT COUNT(*) FROM artifacts WHERE simulation_id = $1",
            sim_uuid,
        )
        or 0
    )
    total_management_flags = (
        await db.fetchval(
            "SELECT COUNT(*) FROM management_shadow_log WHERE simulation_id = $1",
            sim_uuid,
        )
        or 0
    )

    return {
        "id": str(sim.id),
        "name": sim.name,
        "description": sim.description,
        "config": sim.config,
        "status": sim.status,
        "started_at": sim.started_at.isoformat() if sim.started_at else None,
        "completed_at": sim.completed_at.isoformat() if sim.completed_at else None,
        "real_duration": str(sim.real_duration) if sim.real_duration else None,
        "simulated_duration": str(sim.simulated_duration) if sim.simulated_duration else None,
        "total_conversations": int(total_conversations),
        "total_turns": int(total_turns),
        "total_tokens": sim.total_tokens,
        "total_cost": total_cost,
        "total_artifacts": int(total_artifacts),
        "total_management_flags": int(total_management_flags),
        "agents_participated": sim.agents_participated,
        "hypothesis": sim.hypothesis,
        "outcomes": sim.outcomes,
        "learnings": sim.learnings,
        "factions": sim.factions,
    }


@router.get("/simulations/{sim_id}/conversations")
async def get_simulation_conversations(
    sim_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """All conversations in a simulation, paginated."""
    db = _get_db()
    repo = ConversationRepo(db)
    sim_uuid = uuid.UUID(sim_id)
    conversations, total = await repo.get_conversations_by_simulation(
        sim_uuid,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_conversation_to_summary(c) for c in conversations],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/simulations/{sim_id}/costs")
async def get_simulation_costs(sim_id: str) -> dict[str, Any]:
    """Cost breakdown by agent for a simulation."""
    db = _get_db()
    from core.repos.cost_repo import CostRepo

    cost_repo = CostRepo(db)
    sim_uuid = uuid.UUID(sim_id)
    data = await cost_repo.get_costs_by_simulation(sim_uuid)
    return data


@router.get("/simulations/{sim_id}/timeline")
async def get_simulation_timeline(
    sim_id: str,
    agent_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Chronological event stream for a simulation."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo

    sim_repo = SimulationRepo(db)
    sim_uuid = uuid.UUID(sim_id)
    events = await sim_repo.get_timeline_events(
        sim_uuid,
        agent_id=agent_id,
        event_type=event_type,
    )
    return events


@router.get("/simulations/{sim_id}/energy-timeline")
async def get_simulation_energy_timeline(
    sim_id: str,
    agent_id: str | None = Query(default=None),
) -> dict[str, list[dict[str, Any]]]:
    """Time-series of conversation energy grouped by agent.

    Returns a mapping of agent_id -> ordered list of
    ``{t, energy, turn, conversation_id}`` points. Use the optional
    ``agent_id`` query parameter to filter to a single agent.
    """
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo

    repo = ConversationRepo(db)
    sim_uuid = uuid.UUID(sim_id)
    return await repo.get_energy_timeline(sim_uuid, agent_id=agent_id)


@router.get("/simulations/{sim_id}/report")
async def get_simulation_report(
    sim_id: str,
    days: str | None = Query(default=None),
) -> dict[str, Any]:
    """Public simulation report."""
    db = _get_db()

    from core.reporting.timeline_reporter import TimelineReporter
    from core.repos.relationship_repo import RelationshipRepo

    relationship_repo = RelationshipRepo(db)
    reporter = TimelineReporter(
        db=db,
        simulation_id=sim_id,
        relationship_repo=relationship_repo,
    )
    day_list = None
    if days:
        try:
            day_list = [int(d.strip()) for d in days.split(",")]
        except ValueError:
            pass
    report = await reporter.generate(days=day_list, format="json")

    from core.reporting.scorecard import LaunchScorecard
    from core.reporting.timeline_reporter import ReportSection
    from core.repos.assertion_repo import AssertionRepo

    assertion_repo = AssertionRepo(db)
    scorecard = LaunchScorecard(
        db=db,
        simulation_id=sim_id,
        assertion_repo=assertion_repo,
        relationship_repo=relationship_repo,
    )
    scorecard_result = await scorecard.evaluate()
    report.sections.append(
        ReportSection(
            title="Launch Readiness Scorecard",
            data=scorecard_result.to_dict(),
        )
    )

    return report.to_dict()


@router.get("/simulations/{sim_id}/assertions")
async def get_simulation_assertions(sim_id: str) -> list[dict[str, Any]]:
    """Public assertion results for a simulation."""
    db = _get_db()
    from core.repos.assertion_repo import AssertionRepo

    repo = AssertionRepo(db)
    rows = await repo.get_by_simulation(uuid.UUID(sim_id))
    # Transform DB fields to match frontend AssertionResult interface
    for row in rows:
        passed = row.pop("passed", False)
        severity = row.get("severity", "warning")
        if passed:
            row["status"] = "pass"
        elif severity == "warning" or severity == "info":
            row["status"] = "warning"
        else:
            row["status"] = "fail"
        if "error_message" in row:
            row["message"] = row.pop("error_message")
        if "phase_name" in row:
            row["phase"] = row.pop("phase_name")
        if "assertion_name" in row:
            row["name"] = row.pop("assertion_name")
    return rows


@router.get("/simulations/{sim_id}/assertions/summary")
async def get_simulation_assertions_summary(sim_id: str) -> dict[str, Any]:
    """Public pass/fail/warn summary for simulation assertions."""
    db = _get_db()
    from core.repos.assertion_repo import AssertionRepo

    repo = AssertionRepo(db)
    rates = await repo.get_pass_rates(uuid.UUID(sim_id))
    return {
        "passed": rates.get("passed", 0),
        "failed": rates.get("failed_error", 0),
        "warnings": rates.get("failed_warning", 0) + rates.get("failed_info", 0),
    }


@router.get("/simulations/{sim_id}/evals")
async def get_simulation_evals(sim_id: str) -> list[dict[str, Any]]:
    """Public eval results for a simulation."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)

    runs = await eval_repo.get_eval_runs(uuid.UUID(sim_id))
    result = []
    for run in runs:
        results = await eval_repo.get_eval_results(run.id)
        result.append(
            {
                "id": str(run.id),
                "simulation_id": str(run.simulation_id),
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "overall_score": float(run.overall_score)
                if run.overall_score is not None
                else None,
                "cost": float(run.cost),
                "results": [
                    {
                        "category": r.category,
                        "score": float(r.score) if r.score is not None else None,
                        "reasoning": r.reasoning,
                    }
                    for r in results
                ],
            }
        )
    return result


@router.get("/simulations/{sim_id}/social-graph")
async def get_simulation_social_graph(sim_id: str) -> list[dict[str, Any]]:
    """Public social graph for a simulation."""
    db = _get_db()
    from core.repos.relationship_repo import RelationshipRepo

    repo = RelationshipRepo(db)
    relationships = await repo.get_social_graph(uuid.UUID(sim_id))
    return [r.model_dump(mode="json") for r in relationships]


@router.get("/simulations/{sim_id}/snapshots")
async def get_simulation_snapshots(sim_id: str) -> list[dict[str, Any]]:
    """Public list of memory snapshots for a simulation."""
    import json as _json
    from datetime import UTC, datetime
    from pathlib import Path

    snapshots_dir = Path("snapshots")
    results: list[dict[str, Any]] = []
    if not snapshots_dir.exists():
        return results

    for f in sorted(snapshots_dir.glob("*.json"), reverse=True):
        try:
            data = _json.loads(f.read_text())
            source_id = data.get("source_simulation_id", "")
            if source_id == sim_id or not source_id:
                agents = data.get("agents", {})
                snapshot_at = (
                    data.get("snapshot_at")
                    or datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat()
                )
                results.append(
                    {
                        "filename": f.name,
                        "simulation_id": source_id,
                        "snapshot_at": snapshot_at,
                        "agent_count": len(agents),
                    }
                )
        except Exception:
            continue
    return results


def _artifact_summary(artifact_type: str, tool_input: dict[str, Any] | None) -> str | None:
    """Extract a short content preview from tool_input for public display."""
    if not tool_input:
        return None
    text: str | None = None
    match artifact_type:
        case "social_post":
            text = tool_input.get("content") or tool_input.get("text") or tool_input.get("message")
        case "email":
            subject = tool_input.get("subject", "")
            body = tool_input.get("body") or tool_input.get("content") or ""
            text = f"[{subject}] {body}" if subject else str(body)
        case "code_execution":
            text = tool_input.get("code") or tool_input.get("source")
        case "message":
            text = (
                tool_input.get("content")
                or tool_input.get("text")
                or tool_input.get("body")
                or tool_input.get("message")
            )
        case "memory_operation":
            text = tool_input.get("content") or tool_input.get("memory")
        case "web_search":
            text = tool_input.get("query")
        case "poll":
            text = tool_input.get("question")
    if isinstance(text, str) and text:
        return text[:200]
    return None


@router.get("/artifacts")
async def get_public_artifacts(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    agent_id: str | None = Query(None),
    artifact_type: str | None = Query(None, alias="type"),
) -> dict[str, Any]:
    """Public artifact gallery (read-only)."""
    svc = _get_services()
    if not svc.artifact_repo:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    agent_ids = [agent_id] if agent_id else None
    artifacts, total = await svc.artifact_repo.get_all_artifacts(
        simulation_id=None,
        agent_ids=agent_ids,
        artifact_type=artifact_type,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [
            {
                "id": str(a.id),
                "agent_id": a.agent_id,
                "tool_name": a.tool_name,
                "artifact_type": a.artifact_type,
                "status": a.status,
                "summary": _artifact_summary(a.artifact_type, a.tool_input),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ── Public Simulation Submission ─────────────────────────────────


class PublicSubmitRequest(BaseModel):
    scenario_id: str
    name: str
    params: dict[str, Any] | None = None
    hypothesis: str | None = Field(default=None, max_length=2000)


class PublicSubmitResponse(BaseModel):
    simulation_id: str
    status_url: str
    estimated_completion_time: str


_NAME_OK_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_"
)


def _sanitize_submission_name(raw: str) -> str:
    cleaned = "".join(c for c in (raw or "").strip() if c in _NAME_OK_CHARS)
    return cleaned[:100]


def _public_caps() -> tuple[float, float]:
    """Return (per_submission_cap_usd, lifetime_cap_usd)."""
    import os
    from decimal import InvalidOperation

    def _parse(name: str, default: float) -> float:
        raw = os.environ.get(name, "")
        if not raw:
            return default
        try:
            return float(raw)
        except (ValueError, InvalidOperation):
            return default

    return (
        _parse("PUBLIC_SIM_MAX_COST_USD", 1.0),
        _parse("PUBLIC_USER_LIFETIME_CAP_USD", 10.0),
    )


@router.post("/simulations/submit", response_model=PublicSubmitResponse)
async def submit_public_simulation(
    body: PublicSubmitRequest,
    user: User = Depends(get_current_user),
) -> PublicSubmitResponse:
    """Public-user simulation submission with cost + rate guardrails.

    Caps enforced before the orchestrator subprocess is spawned:

      * ``max_cost`` per submission (env ``PUBLIC_SIM_MAX_COST_USD``, default $1)
      * Per-user lifetime cost (``PUBLIC_USER_LIFETIME_CAP_USD``, default $10)
      * 1 concurrent simulation per user (queued or running)
      * 5 submissions / user / day via Redis counter
    """
    import os
    import subprocess
    import sys
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from pathlib import Path

    from core.models import SimulationCreate
    from core.repos.simulation_repo import SimulationRepo
    from core.repos.user_repo import UserRepo

    project_root = Path(__file__).resolve().parent.parent
    scenarios_dir = (project_root / "scenarios").resolve()
    candidate = (scenarios_dir / body.scenario_id).resolve()
    try:
        candidate.relative_to(scenarios_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="scenario_id must resolve inside scenarios/",
        ) from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=400, detail="scenario_id not found")

    sim_name = _sanitize_submission_name(body.name)
    if not sim_name:
        raise HTTPException(status_code=400, detail="name cannot be empty")

    per_sub_cap, lifetime_cap = _public_caps()
    requested_cost = float((body.params or {}).get("max_cost", per_sub_cap))
    max_cost = max(0.0, min(requested_cost, per_sub_cap))

    # Lifetime cost cap (worst-case: count requested max against the user's
    # already-spent total, even though actual cost is usually lower).
    projected_total = float(user.total_cost_spent) + max_cost
    if projected_total > lifetime_cap:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "lifetime_cap",
                "message": (
                    f"Lifetime cost cap of ${lifetime_cap:.2f} would be exceeded "
                    f"(spent ${float(user.total_cost_spent):.2f} + "
                    f"requested ${max_cost:.2f})"
                ),
            },
        )

    services = _get_services()
    db = services.db
    sim_repo = SimulationRepo(db)
    user_repo = UserRepo(db)

    # Concurrent simulations cap (1)
    active = await sim_repo.count_active_for_user(user.id)
    if active >= 1:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "concurrent_limit",
                "message": "You already have a simulation queued or running",
            },
        )

    # Daily rate limit (5/day) — Redis counter, no-op if Redis is down.
    redis = services.redis
    daily_key = f"ratelimit:sim_submit:{user.id}"
    allowed = await _check_rate_limit(redis, daily_key, 5, 86400)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_limit",
                "message": "Daily submission limit reached (5/day)",
            },
        )

    sim = await sim_repo.create(
        SimulationCreate(
            name=sim_name,
            description=body.hypothesis,
            config={
                "scenario_id": body.scenario_id,
                "max_cost": max_cost,
                "params": body.params or {},
                "source": "public_submit",
            },
            status="queued",  # type: ignore[arg-type]
            hypothesis=body.hypothesis,
            submitted_by_user_id=user.id,
        )
    )

    # Worst-case accounting: charge the user for the requested cap up-front
    # so concurrent submissions can't race past the lifetime cap. A future
    # reconciliation worker should refund the unused portion based on
    # cost_events, but that is out of scope here.
    await user_repo.increment_sims_and_cost(
        user.id,
        cost_delta=Decimal(str(max_cost)),
    )

    cmd = [
        sys.executable,
        str(project_root / "scripts" / "run_simulation.py"),
        "--name",
        sim_name,
        "--seed-file",
        str(candidate),
        "--max-cost",
        str(max_cost),
        "--sim-id",
        str(sim.id),
    ]
    # Skip subprocess spawn during pytest — tests assert on row creation.
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(project_root),
        )

    eta = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    return PublicSubmitResponse(
        simulation_id=str(sim.id),
        status_url=f"/api/simulations/{sim.id}",
        estimated_completion_time=eta,
    )


# ── Notifications: per-email opt-out via tokenised footer link ──


_UNSUB_PAGE_OK = """<!doctype html>
<html><head><meta charset="utf-8"><title>Unsubscribed</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
              padding:48px 16px;background:#f8fafc;color:#0f172a;
              text-align:center;">
  <h1 style="margin:0 0 12px;">You're unsubscribed.</h1>
  <p style="margin:0;color:#475569;">
    We won't email you when your simulations finish.
    You can opt back in from your account at any time.
  </p>
</body></html>"""

_UNSUB_PAGE_INVALID = """<!doctype html>
<html><head><meta charset="utf-8"><title>Invalid link</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
              padding:48px 16px;background:#f8fafc;color:#0f172a;
              text-align:center;">
  <h1 style="margin:0 0 12px;">This unsubscribe link is no longer valid.</h1>
  <p style="margin:0;color:#475569;">
    The token was unrecognised. If you're still receiving emails, contact
    support.
  </p>
</body></html>"""


@router.get(
    "/notifications/unsubscribe",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def unsubscribe_completion_emails(token: str = Query(...)) -> HTMLResponse:
    """Tokenised one-click opt-out of completion emails (no auth required)."""
    from core.repos.user_repo import UserRepo

    if not token:
        return HTMLResponse(_UNSUB_PAGE_INVALID, status_code=400)

    repo = UserRepo(_get_db())
    user = await repo.get_by_unsubscribe_token(token)
    if user is None:
        return HTMLResponse(_UNSUB_PAGE_INVALID, status_code=404)

    await repo.set_notify_on_complete(user.id, enabled=False)
    logger.info("[notify] user=%s opted out of completion emails", user.id)
    return HTMLResponse(_UNSUB_PAGE_OK, status_code=200)

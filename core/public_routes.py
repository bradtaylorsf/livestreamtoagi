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

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core.constants import LIVE_SIMULATION_ID
from core.models import (
    Challenge,
    Conversation,
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
    redis, key: str, max_requests: int, window_seconds: int,
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
    trigger_type: str
    participating_agents: list[str]
    topics_discussed: list[str] | None = None
    turn_count: int = 0
    location: str | None = None
    started_at: str | None = None


class ConversationDetailResponse(BaseModel):
    id: str
    trigger_type: str
    participating_agents: list[str]
    topics_discussed: list[str] | None = None
    turn_count: int = 0
    location: str | None = None
    initial_energy: float = 0.0
    final_energy: float | None = None
    started_at: str | None = None
    ended_at: str | None = None


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
        trigger_type=c.trigger_type,
        participating_agents=c.participating_agents,
        topics_discussed=c.topics_discussed,
        turn_count=c.turn_count,
        location=c.location,
        started_at=c.started_at.isoformat() if c.started_at else None,
    )


def _conversation_to_detail(c: Conversation) -> ConversationDetailResponse:
    return ConversationDetailResponse(
        id=str(c.id),
        trigger_type=c.trigger_type,
        participating_agents=c.participating_agents,
        topics_discussed=c.topics_discussed,
        turn_count=c.turn_count,
        location=c.location,
        initial_energy=c.initial_energy,
        final_energy=c.final_energy,
        started_at=c.started_at.isoformat() if c.started_at else None,
        ended_at=c.ended_at.isoformat() if c.ended_at else None,
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


@router.get("/agents")
async def get_agents() -> list[AgentPublicProfile]:
    registry = _get_registry()
    agents = registry.get_all_agents()
    return [
        AgentPublicProfile(
            id=a.id,
            display_name=a.display_name,
            role=a.role,
            color=a.color_hex,
            status=a.status.value if hasattr(a.status, "value") else str(a.status),
            conversation_model=a.model_conversation,
            building_model=a.model_building,
            chattiness=a.chattiness,
            initiative=a.initiative,
        )
        for a in agents
    ]


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> AgentPublicProfile:
    registry = _get_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    a = agent
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
    )


@router.get("/agents/{agent_id}/journal")
async def get_agent_journal(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    db = _get_db()
    rows = await db.fetch(
        """SELECT * FROM journal_entries
           WHERE agent_id = $1 AND simulation_id = $4
           ORDER BY created_at DESC
           LIMIT $2 OFFSET $3""",
        agent_id, limit, offset, LIVE_SIMULATION_ID,
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
async def get_agent_relationships(agent_id: str) -> list[dict[str, Any]]:
    svc = _get_services()
    if not svc.relationship_repo:
        return []
    relationships = await svc.relationship_repo.get_all_for_agent(
        LIVE_SIMULATION_ID, agent_id,
    )
    return [
        {
            "id": str(r.id),
            "target_agent_id": r.target_agent_id,
            "sentiment_score": float(r.sentiment_score) if r.sentiment_score else 0,
            "trust_score": float(r.trust_score) if r.trust_score else 0,
            "interaction_count": r.interaction_count,
            "relationship_summary": r.relationship_summary,
        }
        for r in relationships
    ]


@router.get("/agents/{agent_id}/conversations")
async def get_agent_conversations(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    db = _get_db()
    repo = ConversationRepo(db)
    convs, total = await repo.get_conversations_by_agent(
        agent_id, simulation_id=LIVE_SIMULATION_ID, limit=limit, offset=offset,
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    svc = _get_services()
    if not svc.artifact_repo:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    artifacts, total = await svc.artifact_repo.get_all_artifacts(
        simulation_id=LIVE_SIMULATION_ID,
        agent_ids=[agent_id], limit=limit, offset=offset,
    )
    return {
        "items": [
            {
                "id": str(a.id),
                "agent_id": a.agent_id,
                "tool_name": a.tool_name,
                "artifact_type": a.artifact_type,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/agents/{agent_id}/core-memory")
async def get_agent_core_memory(agent_id: str) -> dict[str, Any]:
    """Current core memory content (read-only, no version history)."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    current = await memory_repo.get_core_memory(agent_id, simulation_id=LIVE_SIMULATION_ID)
    return {
        "current_content": current.content if current else "",
        "last_updated": current.last_updated.isoformat() if current and current.last_updated else None,
    }


@router.get("/agents/{agent_id}/recall-memories")
async def get_agent_recall_memories(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Paginated recall memories (read-only, embeddings hidden)."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    memories, total = await memory_repo.get_recall_memories_paginated(
        agent_id, limit=limit, offset=offset, simulation_id=LIVE_SIMULATION_ID,
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
async def get_agent_evolution(agent_id: str) -> list[dict[str, Any]]:
    svc = _get_services()
    if not svc.config_version_repo:
        return []
    versions = await svc.config_version_repo.get_prompt_history(
        agent_id, simulation_id=LIVE_SIMULATION_ID,
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
    agent_id: str, req: ChatRequest, request: Request,
) -> ChatResponse:
    svc = _get_services()
    ip = _client_ip(request)
    allowed = await _check_rate_limit(
        svc.redis, f"ratelimit:chat:{ip}:{agent_id}", 10, 3600,
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    db = _get_db()
    total = await db.fetchval(
        "SELECT COUNT(*) FROM conversations WHERE simulation_id = $1",
        LIVE_SIMULATION_ID,
    )
    rows = await db.fetch(
        """SELECT * FROM conversations
           WHERE simulation_id = $3
           ORDER BY started_at DESC
           LIMIT $1 OFFSET $2""",
        limit, offset, LIVE_SIMULATION_ID,
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
            status_code=400, detail="Invalid conversation ID",
        ) from exc
    conv = await repo.get(conv_uuid, simulation_id=LIVE_SIMULATION_ID)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _conversation_to_detail(conv)


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
            status_code=400, detail="Invalid conversation ID",
        ) from exc
    logs = await repo.get_selection_log(conv_uuid, simulation_id=LIVE_SIMULATION_ID)
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
            result.append({
                "name": data.get("name", cat),
                "description": data.get("description", ""),
                "system": data.get("system", ""),
                "rubric": data.get("rubric", {}),
                "sub_scores": data.get("sub_scores", []),
                "output_schema": data.get("output_schema", {}),
                "model": data.get("model", ""),
                "temperature": data.get("temperature"),
                "max_tokens": data.get("max_tokens"),
            })
        except Exception:
            logger.warning("Failed to load eval prompt for %s", cat)
    return result


@router.get("/evals/prompts/{category}")
async def get_eval_prompt(category: str) -> dict[str, Any]:
    """Return a single eval category prompt."""
    from core.eval.prompt_loader import load_prompt

    try:
        data = load_prompt(category)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Eval prompt '{category}' not found")
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
            category, limit,
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
) -> list[PublicEvalRun]:
    db = _get_db()
    if not db:
        return []
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    runs = await eval_repo.get_all_eval_runs(limit=limit, offset=offset)

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
            r.category: float(r.score) if r.score is not None else None
            for r in results
        }
        result.append(PublicEvalRun(
            id=str(run.id),
            simulation_id=str(run.simulation_id),
            simulation_name=sim_names.get(run.simulation_id),
            date=run.started_at.isoformat() if run.started_at else "",
            overall_score=float(run.overall_score) if run.overall_score is not None else None,
            cost=float(run.cost),
            model_versions=flat_versions,
            category_scores=category_scores,
        ))
    return result


@router.get("/evals/latest")
async def get_latest_eval_run() -> PublicEvalRun | None:
    db = _get_db()
    if not db:
        return None
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    # Get most recent eval run across all simulations
    runs = await eval_repo.get_all_eval_runs(limit=1, offset=0)
    if not runs:
        return None
    run = runs[0]

    # Fetch simulation name
    sim_row = await db.fetchrow(
        "SELECT name FROM simulations WHERE id = $1", run.simulation_id,
    )
    sim_name = sim_row["name"] if sim_row else None

    results = await eval_repo.get_eval_results(run.id)
    flat_versions: dict[str, str] = {}
    for agent_id, models in (run.model_versions or {}).items():
        if isinstance(models, dict):
            flat_versions[agent_id] = models.get("conversation", "unknown")
        else:
            flat_versions[agent_id] = str(models)
    category_scores = {
        r.category: float(r.score) if r.score is not None else None
        for r in results
    }
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
        "SELECT name FROM simulations WHERE id = $1", run.simulation_id,
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
        results=[
            {"category": r.category, "score": float(r.score) if r.score is not None else None}
            for r in results
        ],
    )


# ── World & Challenge Endpoints ──────────────────────────────────


@router.get("/world/chunks")
async def get_world_chunks() -> list[dict[str, Any]]:
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
        results.append({
            "id": chunk.id,
            "name": chunk.name,
            "x": chunk.x_offset,
            "y": chunk.y_offset,
            "width": chunk.width,
            "height": chunk.height,
            "tiles": chunk.tile_data,
            "objects": chunk.objects or [],
        })
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
    req: ChallengeSubmitRequest, request: Request,
) -> ChallengeResponse:
    svc = _get_services()
    ip = _client_ip(request)
    allowed = await _check_rate_limit(
        svc.redis, f"ratelimit:challenge:{ip}", 5, 3600,
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
    challenge_id: int, request: Request,
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
    convs = await db.fetchval(
        "SELECT COUNT(*) FROM conversations WHERE simulation_id = $1",
        LIVE_SIMULATION_ID,
    ) or 0
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
) -> dict[str, Any]:
    db = _get_db()
    clauses: list[str] = ["simulation_id = $1"]
    params: list[object] = [LIVE_SIMULATION_ID]
    idx = 2

    if agent:
        clauses.append(f"${idx} = ANY(agents_involved)")
        params.append(agent)
        idx += 1
    if event_type:
        clauses.append(f"event_type = ${idx}")
        params.append(event_type)
        idx += 1

    where = " WHERE " + " AND ".join(clauses)

    total = await db.fetchval(
        f"SELECT COUNT(*) FROM world_events{where}",  # noqa: S608
        *params,
    )

    query = (
        f"SELECT * FROM world_events{where}"  # noqa: S608
        f" ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
    )
    rows = await db.fetch(query, *params, limit, offset)

    items = [
        _event_to_response(WorldEvent(**dict(r)))
        for r in rows
    ]

    return {"items": items, "total": total or 0, "limit": limit, "offset": offset}


# ── Public Simulation Endpoints (read-only) ─────────────────────


@router.get("/simulations")
async def get_simulations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List simulations (completed and running only, public read-only)."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    simulations = await sim_repo.list(
        status=None, limit=limit, offset=offset,
    )
    # Filter to only completed/running for public view
    public_statuses = {"completed", "running"}
    filtered = [s for s in simulations if s.status in public_statuses]
    total = await sim_repo.count()

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
            }
            for s in filtered
        ],
        "total": total or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/simulations/{sim_id}")
async def get_simulation_detail(sim_id: str) -> dict[str, Any]:
    """Public simulation detail."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    sim = await sim_repo.get(uuid.UUID(sim_id))
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")

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
        "total_conversations": sim.total_conversations,
        "total_turns": sim.total_turns,
        "total_tokens": sim.total_tokens,
        "total_cost": sim.total_cost,
        "total_artifacts": sim.total_artifacts,
        "total_overseer_flags": sim.total_overseer_flags,
        "agents_participated": sim.agents_participated,
    }


@router.get("/simulations/{sim_id}/report")
async def get_simulation_report(
    sim_id: str,
    days: str | None = Query(default=None),
) -> dict[str, Any]:
    """Public simulation report."""
    db = _get_db()

    from core.repos.relationship_repo import RelationshipRepo
    from core.reporting.timeline_reporter import TimelineReporter

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
    report.sections.append(ReportSection(
        title="Launch Readiness Scorecard",
        data=scorecard_result.to_dict(),
    ))

    return report.to_dict()


@router.get("/simulations/{sim_id}/assertions")
async def get_simulation_assertions(sim_id: str) -> list[dict[str, Any]]:
    """Public assertion results for a simulation."""
    db = _get_db()
    from core.repos.assertion_repo import AssertionRepo
    repo = AssertionRepo(db)
    return await repo.get_by_simulation(uuid.UUID(sim_id))


@router.get("/simulations/{sim_id}/assertions/summary")
async def get_simulation_assertions_summary(sim_id: str) -> dict[str, Any]:
    """Public pass/fail/warn summary for simulation assertions."""
    db = _get_db()
    from core.repos.assertion_repo import AssertionRepo
    repo = AssertionRepo(db)
    return await repo.get_pass_rates(uuid.UUID(sim_id))


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
        result.append({
            "id": str(run.id),
            "simulation_id": str(run.simulation_id),
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "overall_score": float(run.overall_score) if run.overall_score is not None else None,
            "cost": float(run.cost),
            "results": [
                {
                    "category": r.category,
                    "score": float(r.score) if r.score is not None else None,
                    "reasoning": r.reasoning,
                }
                for r in results
            ],
        })
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
                results.append({
                    "filename": f.name,
                    "simulation_id": source_id,
                    "snapshot_at": data.get("snapshot_at", ""),
                    "agent_count": len(agents),
                })
        except Exception:
            continue
    return results


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
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

"""Admin API endpoints for the debug dashboard.

Exposes agent internals, simulation data, conversation details,
artifacts, and eval results. Mounted at /api/admin.

Protected by ADMIN_PASSWORD env var — requests must include
``Authorization: Bearer <password>`` header.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from core.models import (
    AgentDetail,
    AgentSummary,
    Artifact,
    Conversation,
    ConversationDetail,
    CoreMemoryResponse,
    CoreMemoryVersionEntry,
    CostBreakdownResponse,
    CostByDay,
    CostByType,
    EvalComparisonResponse,
    EvalExportResponse,
    EvalHistoryPoint,
    EvalResult,
    EvalRun,
    EvalRunDetail,
    EvalRunRequest,
    EvalRunResponse,
    JournalEntry,
    PaginatedResponse,
    PersonalityTraits,
    SelectionLog,
    Simulation,
    SimulationCostResponse,
    SystemPromptLayer,
    SystemPromptResponse,
    TimelineEvent,
    TurnDetail,
)
from core.system_prompt import INFRASTRUCTURE_PROMPT

if TYPE_CHECKING:
    from datetime import datetime

_bearer_scheme = HTTPBearer()


async def _require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),  # noqa: B008
) -> None:
    """Validate the admin password from the Authorization header."""
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_PASSWORD not configured on server",
        )
    if credentials.credentials != password:
        raise HTTPException(status_code=401, detail="Invalid admin password")


router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(_require_admin)],
)

# Agent metadata not stored in YAML configs — derived from character sheets.
AGENT_ROLES: dict[str, str] = {
    "vera": "Showrunner/Coordinator",
    "rex": "Engineer/Builder",
    "aurora": "Creative Director",
    "pixel": "Researcher/Audience Liaison",
    "fork": "Contrarian/Code Reviewer",
    "sentinel": "Budget Monitor/QA",
    "grok": "Wild Card/Provocateur",
    "management": "Content Filter",
    "alpha": "Errand Runner",
}

AGENT_COLORS: dict[str, str] = {
    "vera": "#9b59b6",
    "rex": "#e74c3c",
    "aurora": "#f1c40f",
    "pixel": "#3498db",
    "fork": "#2ecc71",
    "sentinel": "#e67e22",
    "grok": "#1abc9c",
    "management": "#95a5a6",
    "alpha": "#8e44ad",
}


def _get_db():
    """Lazy import to avoid circular dependency with core.main."""
    from core.main import app
    return app.state.services.db


def _get_llm():
    from core.main import app
    return app.state.services.llm_client


def _get_registry():
    from core.main import app
    return app.state.services.agent_registry


def _agent_summary_from_config(a, *, total_cost: float = 0, message_count: int = 0,
                                conversation_count: int = 0, artifact_count: int = 0) -> AgentSummary:
    """Build AgentSummary from an AgentConfig object."""
    status = a.status.value if hasattr(a.status, "value") else str(a.status)
    return AgentSummary(
        id=a.id,
        display_name=a.display_name,
        role=AGENT_ROLES.get(a.id, ""),
        color=AGENT_COLORS.get(a.id, "#888888"),
        status=status,
        conversation_model=a.model_conversation,
        building_model=a.model_building,
        total_cost=f"{total_cost:.6f}",
        message_count=message_count,
        conversation_count=conversation_count,
        artifact_count=artifact_count,
        personality_traits=PersonalityTraits(
            chattiness=a.chattiness,
            initiative=a.initiative,
            interrupt_tendency=a.interrupt_tendency,
            eavesdrop_tendency=a.eavesdrop_tendency,
            closing_weight=a.closing_weight,
        ),
    )


# ── Global Artifact Endpoints ─────────────────────────────────


@router.get("/artifacts")
async def list_artifacts(
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
    agent_id: str | None = Query(None),
    artifact_type: str | None = Query(None, alias="type"),
    status: str | None = Query(None),
    since: datetime | None = Query(default=None),  # noqa: B008
    until: datetime | None = Query(default=None),  # noqa: B008
    search: str | None = Query(None),
    sort: str = Query("newest"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[Artifact]:
    """Browse all artifacts with filtering, search, and pagination."""
    db = _get_db()
    from core.repos.artifact_repo import ArtifactRepo
    artifact_repo = ArtifactRepo(db)

    # Parse comma-separated lists for multi-select filters
    agent_ids = [a.strip() for a in agent_id.split(",") if a.strip()] if agent_id else None
    types = [t.strip() for t in artifact_type.split(",") if t.strip()] if artifact_type else None
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else None

    artifacts, total = await artifact_repo.get_all_artifacts(
        simulation_id=simulation_id,
        agent_ids=agent_ids,
        artifact_type=types,
        status=statuses,
        since=since,
        until=until,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=artifacts, total=total, limit=limit, offset=offset)


# ── Agent Endpoints ────────────────────────────────────────────


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents() -> list[AgentSummary]:
    """List all agents with current status, total cost, message count."""
    registry = _get_registry()
    db = _get_db()

    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)

    agents = registry.get_all_agents()
    result = []
    for a in agents:
        costs = await cost_repo.get_costs_by_agent(a.id)
        total = sum(c.amount for c in costs if c.amount) if costs else 0
        result.append(_agent_summary_from_config(
            a, total_cost=total, message_count=len(costs) if costs else 0,
        ))
    return result


@router.get("/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: str) -> AgentDetail:
    """Full agent detail: config, personality traits, model assignments, voice."""
    registry = _get_registry()
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    db = _get_db()
    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)
    costs = await cost_repo.get_costs_by_agent(agent_id)
    total_cost = sum(c.amount for c in costs if c.amount) if costs else 0

    summary = _agent_summary_from_config(
        agent, total_cost=total_cost, message_count=len(costs) if costs else 0,
    )
    return AgentDetail(
        **summary.model_dump(),
        voice=agent.voice_id,
        behaviors=agent.behaviors,
    )


@router.get("/agents/{agent_id}/system-prompt", response_model=SystemPromptResponse)
async def get_agent_system_prompt(agent_id: str) -> SystemPromptResponse:
    """Current assembled system prompt (all 3 layers)."""
    registry = _get_registry()
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)
    core_mem = await memory_repo.get_core_memory(agent_id)

    raw_layers = {
        "Infrastructure": INFRASTRUCTURE_PROMPT,
        "Character": agent.system_prompt,
        "Memory Context": core_mem.content if core_mem else "",
    }
    assembled = "\n\n".join(v for v in raw_layers.values() if v)

    def _estimate_tokens(text: str) -> int:
        """Rough heuristic: ~4 chars per token. Not exact — for display only."""
        return len(text) // 4 if text else 0

    layers = [
        SystemPromptLayer(name=name, content=content, token_count=_estimate_tokens(content))
        for name, content in raw_layers.items()
        if content
    ]
    total_tokens = sum(l.token_count for l in layers)

    return SystemPromptResponse(
        assembled_prompt=assembled,
        layers=layers,
        total_tokens=total_tokens,
    )


@router.get("/agents/{agent_id}/core-memory", response_model=CoreMemoryResponse)
async def get_agent_core_memory(agent_id: str) -> CoreMemoryResponse:
    """Current core memory contents + version history."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    current = await memory_repo.get_core_memory(agent_id)
    history = await memory_repo.get_core_memory_history(agent_id)

    version_entries = [
        CoreMemoryVersionEntry(
            version=h.version,
            content=h.content,
            changed_at=h.changed_at.isoformat() if h.changed_at else None,
            change_reason=h.change_reason,
        )
        for h in history
    ]

    return CoreMemoryResponse(
        current_content=current.content if current else "",
        current_version=current.version if current else 0,
        token_count=current.token_count if current else 0,
        last_updated=current.last_updated.isoformat() if current and current.last_updated else None,
        version_history=version_entries,
    )


@router.get("/agents/{agent_id}/recall-memories")
async def get_agent_recall_memories(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
) -> PaginatedResponse[dict[str, Any]]:
    """Paginated recall memories (embeddings hidden, content shown)."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    if search:
        memories, total = await memory_repo.search_recall_memories_by_keyword(
            agent_id, search, limit=limit, offset=offset
        )
    else:
        memories, total = await memory_repo.get_recall_memories_paginated(
            agent_id, limit=limit, offset=offset
        )

    # Strip embeddings from response
    items = []
    for m in memories:
        d = m.model_dump()
        d.pop("embedding", None)
        items.append(d)

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/agents/{agent_id}/conversations")
async def get_agent_conversations(
    agent_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[Conversation]:
    """Paginated conversation history for this agent."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    conversations, total = await conv_repo.get_conversations_by_agent(
        agent_id, simulation_id=simulation_id, limit=limit, offset=offset
    )
    return PaginatedResponse(items=conversations, total=total, limit=limit, offset=offset)


@router.get("/agents/{agent_id}/artifacts")
async def get_agent_artifacts(
    agent_id: str,
    artifact_type: str | None = Query(None, alias="type"),
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[Artifact]:
    """All artifacts produced by this agent."""
    db = _get_db()
    from core.repos.artifact_repo import ArtifactRepo
    artifact_repo = ArtifactRepo(db)

    artifacts, total = await artifact_repo.get_artifacts_by_agent(
        agent_id,
        artifact_type=artifact_type,
        simulation_id=simulation_id,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=artifacts, total=total, limit=limit, offset=offset)


@router.get("/agents/{agent_id}/costs", response_model=CostBreakdownResponse)
async def get_agent_costs(
    agent_id: str,
    from_date: datetime | None = Query(default=None, alias="from"),  # noqa: B008
    to_date: datetime | None = Query(default=None, alias="to"),  # noqa: B008
) -> CostBreakdownResponse:
    """Cost breakdown: by day, by type, total."""
    db = _get_db()
    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)

    data = await cost_repo.get_costs_by_agent_grouped(
        agent_id, from_date=from_date, to_date=to_date
    )

    by_day = [
        CostByDay(date=d.get("day", ""), cost=d.get("total", "0"))
        for d in data.get("by_day", [])
    ]
    by_type = [
        CostByType(
            type=d.get("type", ""),
            cost=d.get("total", "0"),
            tokens=int(d.get("tokens", 0)),
        )
        for d in data.get("by_type", [])
    ]

    return CostBreakdownResponse(
        by_day=by_day,
        by_type=by_type,
        total=data.get("total", "0"),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
    )


@router.get("/agents/{agent_id}/journal")
async def get_agent_journal(
    agent_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[JournalEntry]:
    """Journal entries with full content."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    entries, total = await memory_repo.get_journal_entries(agent_id, limit=limit, offset=offset)
    return PaginatedResponse(items=entries, total=total, limit=limit, offset=offset)


# ── Simulation Endpoints ──────────────────────────────────────


class NewSimulationRequest(BaseModel):
    """Request body for launching a simulation from the dashboard."""

    name: str | None = None
    agents: list[str] = Field(default_factory=list)
    convo_type: str = "freeform"
    topic: str | None = None
    turns: int | None = None
    management_shadow: bool = True


class NewSimulationResponse(BaseModel):
    simulation_id: str
    name: str
    status: str


@router.post("/simulations", response_model=NewSimulationResponse)
async def create_simulation(body: NewSimulationRequest) -> NewSimulationResponse:
    """Create a new simulation and launch it as a background subprocess."""
    import subprocess
    import sys
    from pathlib import Path

    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    import time as _time
    sim_name = body.name or f"dashboard-{body.convo_type}-{_time.strftime('%Y%m%d-%H%M%S')}"

    registry = _get_registry()
    agents = body.agents or [
        a.id for a in registry.get_all_agents()
        if a.id not in ("management", "alpha")
    ]

    from core.models import SimulationCreate
    sim = await sim_repo.create(SimulationCreate(
        name=sim_name,
        config={
            "convo_type": body.convo_type,
            "turns": body.turns,
            "topic": body.topic,
            "management_shadow": body.management_shadow,
            "agents": agents,
            "source": "dashboard",
        },
        agents_participated=agents,
    ))

    # Launch watch_conversations.py in the background
    project_root = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable,
        str(project_root / "scripts" / "watch_conversations.py"),
        "--test",
        "--test-type", body.convo_type,
        "--agents", ",".join(agents),
        "--sim-id", str(sim.id),
    ]
    if body.turns is not None:
        cmd += ["--turns", str(body.turns)]
    if body.topic is not None:
        cmd += ["--topic", body.topic]
    if body.management_shadow:
        cmd.append("--management-shadow")

    subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return NewSimulationResponse(
        simulation_id=str(sim.id),
        name=sim_name,
        status="running",
    )


@router.get("/simulations")
async def list_simulations(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[Simulation]:
    """List all simulations with summary stats."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    simulations = await sim_repo.list(status=status, limit=limit, offset=offset)
    total = await sim_repo.count(status=status)
    return PaginatedResponse(items=simulations, total=total, limit=limit, offset=offset)


@router.get("/simulations/compare")
async def compare_simulations(
    sim_a: uuid_mod.UUID = Query(...),
    sim_b: uuid_mod.UUID = Query(...),
) -> dict[str, Any]:
    """Side-by-side comparison of two simulation runs."""
    db = _get_db()
    from core.repos.relationship_repo import RelationshipRepo
    from core.reporting.comparison import CrossRunComparison

    relationship_repo = RelationshipRepo(db)
    cross = CrossRunComparison(
        db=db,
        simulation_ids=[str(sim_a), str(sim_b)],
        relationship_repo=relationship_repo,
    )
    result = await cross.compare()

    # Also load daily cost breakdown for chart overlay
    daily_costs: dict[str, list[dict[str, Any]]] = {"run_a": [], "run_b": []}
    for label, sim_id in [("run_a", sim_a), ("run_b", sim_b)]:
        rows = await db.fetch(
            """SELECT DATE(created_at) as day, SUM(cost) as daily_cost
               FROM cost_events WHERE simulation_id = $1
               GROUP BY DATE(created_at) ORDER BY day""",
            sim_id,
        )
        daily_costs[label] = [
            {"day": str(r["day"]), "cost": str(r["daily_cost"])} for r in rows
        ]

    data = result.to_dict()
    data["daily_costs"] = daily_costs
    return data


@router.get("/simulations/{sim_id}", response_model=Simulation)
async def get_simulation(sim_id: uuid_mod.UUID) -> Simulation:
    """Full simulation detail: config, stats, phases, timing."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    sim = await sim_repo.get(sim_id)
    if sim is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sim


@router.get("/simulations/{sim_id}/timeline", response_model=list[TimelineEvent])
async def get_simulation_timeline(
    sim_id: uuid_mod.UUID,
    agent_id: str | None = Query(None),
    event_type: str | None = Query(None),
) -> list[TimelineEvent]:
    """Chronological event stream for a simulation."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    events = await sim_repo.get_timeline_events(
        sim_id, agent_id=agent_id, event_type=event_type
    )
    return [TimelineEvent(**e) for e in events]


@router.get("/simulations/{sim_id}/conversations")
async def get_simulation_conversations(
    sim_id: uuid_mod.UUID,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> PaginatedResponse[Conversation]:
    """All conversations in this simulation."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    conversations, total = await conv_repo.get_conversations_by_simulation(
        sim_id, limit=limit, offset=offset
    )
    return PaginatedResponse(items=conversations, total=total, limit=limit, offset=offset)


@router.get("/simulations/{sim_id}/artifacts")
async def get_simulation_artifacts(
    sim_id: uuid_mod.UUID,
    agent_id: str | None = Query(None),
    artifact_type: str | None = Query(None, alias="type"),
) -> list[Artifact]:
    """All artifacts from this simulation."""
    db = _get_db()
    from core.repos.artifact_repo import ArtifactRepo
    artifact_repo = ArtifactRepo(db)

    return await artifact_repo.get_artifacts_by_simulation(
        sim_id, agent_id=agent_id, artifact_type=artifact_type
    )


@router.get("/simulations/{sim_id}/management-log")
async def get_simulation_management_log(
    sim_id: uuid_mod.UUID,
    severity_min: int = Query(1, ge=1, le=5),
) -> list[dict[str, Any]]:
    """All Management shadow flags from this simulation."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    return await sim_repo.get_management_log(sim_id, severity_min=severity_min)


@router.get("/simulations/{sim_id}/costs", response_model=SimulationCostResponse)
async def get_simulation_costs(sim_id: uuid_mod.UUID) -> SimulationCostResponse:
    """Cost breakdown by agent, by tool type, total."""
    db = _get_db()
    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)

    data = await cost_repo.get_costs_by_simulation(sim_id)
    return SimulationCostResponse(**data)


# ── Conversation Endpoints ─────────────────────────────────────


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(conv_id: uuid_mod.UUID) -> ConversationDetail:
    """Full conversation: transcript, participants, trigger, energy history."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    from core.repos.transcript_repo import TranscriptRepo
    conv_repo = ConversationRepo(db)
    transcript_repo = TranscriptRepo(db)

    conv = await conv_repo.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    energy_log = await conv_repo.get_energy_log(conv_id)
    transcript_record = await transcript_repo.get_by_conversation(conv_id)

    # Estimate tokens from transcript length (cost_events lacks conversation_id)
    transcript_text = transcript_record.content if transcript_record else ""
    total_tokens = len(transcript_text) // 4 if transcript_text else 0

    return ConversationDetail(
        id=conv.id,
        simulation_id=conv.simulation_id,
        started_at=conv.started_at,
        ended_at=conv.ended_at,
        trigger_type=conv.trigger_type,
        trigger_details=conv.trigger_details,
        initial_energy=conv.initial_energy,
        final_energy=conv.final_energy,
        turn_count=conv.turn_count,
        participating_agents=conv.participating_agents,
        topics_discussed=conv.topics_discussed,
        closed_by=conv.closed_by,
        location=conv.location,
        energy_history=energy_log,
        transcript=transcript_record.content if transcript_record else None,
        total_tokens=total_tokens,
        total_cost="0",
    )


@router.get("/conversations/{conv_id}/turns", response_model=list[TurnDetail])
async def get_conversation_turns(conv_id: uuid_mod.UUID) -> list[TurnDetail]:
    """Turn-by-turn detail with selection scores."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    logs = await conv_repo.get_selection_log(conv_id)
    return [
        TurnDetail(
            turn_number=log.turn_number,
            selected_agent_id=log.selected_agent_id,
            was_interrupt=log.was_interrupt,
            agent_scores=log.agent_scores,
            detected_topic=log.detected_topic,
            previous_speaker_id=log.previous_speaker_id,
            conversation_energy=log.conversation_energy,
            timestamp=log.timestamp,
        )
        for log in logs
    ]


@router.get("/conversations/{conv_id}/selection-log", response_model=list[SelectionLog])
async def get_conversation_selection_log(conv_id: uuid_mod.UUID) -> list[SelectionLog]:
    """Speaker selection scores for every turn (all candidates scored)."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    return await conv_repo.get_selection_log(conv_id)


@router.get("/conversations/{conv_id}/management-flags")
async def get_conversation_management_flags(
    conv_id: uuid_mod.UUID,
) -> list[dict[str, Any]]:
    """Management shadow flags for this conversation."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    return await conv_repo.get_management_flags(conv_id)


@router.get("/conversations/{conv_id}/artifacts")
async def get_conversation_artifacts(
    conv_id: uuid_mod.UUID,
) -> list[dict[str, Any]]:
    """Tool invocation artifacts for this conversation."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    return await conv_repo.get_artifacts(conv_id)


@router.get("/conversations/{conv_id}/interrupts")
async def get_conversation_interrupts(
    conv_id: uuid_mod.UUID,
) -> list[dict[str, Any]]:
    """Interrupt events for this conversation."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    return await conv_repo.get_interrupts(conv_id)


# ── Eval Endpoints ─────────────────────────────────────────────


@router.get("/simulations/{sim_id}/evals", response_model=list[EvalRunDetail])
async def get_simulation_evals(sim_id: uuid_mod.UUID) -> list[EvalRunDetail]:
    """All eval runs for this simulation with nested results."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    runs = await eval_repo.get_eval_runs(sim_id)
    result = []
    for run in runs:
        results = await eval_repo.get_eval_results(run.id)
        result.append(EvalRunDetail(
            **run.model_dump(),
            results=results,
        ))
    return result


@router.post("/simulations/{sim_id}/evals/run", response_model=EvalRunResponse)
async def run_simulation_evals(
    sim_id: uuid_mod.UUID, body: EvalRunRequest
) -> EvalRunResponse:
    """Trigger eval run — dispatches asynchronously and returns immediately."""
    db = _get_db()
    llm = _get_llm()
    from core.eval.engine import EvalEngine
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    engine = EvalEngine(db=db, llm_client=llm, eval_repo=eval_repo)

    # Pre-create the eval run record so we can return its ID immediately
    eval_run = await eval_repo.create_eval_run(sim_id, body.eval_suite or "full")
    run_id = eval_run.id

    # Fire-and-forget — run evals in background task
    async def _run_eval_background() -> None:
        try:
            await engine.run(
                sim_id,
                categories=body.categories,
                suite=body.eval_suite,
                existing_run_id=run_id,
            )
        except Exception:
            logger.exception("Background eval run %s failed", run_id)
            await eval_repo.update_eval_run(run_id, status="failed")

    asyncio.create_task(_run_eval_background())

    return EvalRunResponse(
        eval_run_id=str(run_id),
        status="running",
    )


@router.get("/evals", response_model=list[EvalRun])
async def list_eval_runs(
    limit: int = 50,
    offset: int = 0,
) -> list[EvalRun]:
    """Paginated list of all eval runs across simulations."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    return await eval_repo.get_all_eval_runs(limit=limit, offset=offset)


@router.get("/evals/categories")
async def eval_categories() -> list[str]:
    """Distinct eval categories from all results. Used by frontend charts."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    return await eval_repo.get_eval_categories()


@router.get("/evals/compare", response_model=EvalComparisonResponse)
async def compare_evals(
    run_a: str,
    run_b: str,
) -> EvalComparisonResponse:
    """Side-by-side comparison of two eval runs."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    try:
        a_id = uuid_mod.UUID(run_a)
        b_id = uuid_mod.UUID(run_b)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format for run_a or run_b")

    run_a_obj = await eval_repo.get_eval_run(a_id)
    run_b_obj = await eval_repo.get_eval_run(b_id)
    if run_a_obj is None or run_b_obj is None:
        raise HTTPException(status_code=404, detail="One or both eval runs not found")

    results_a = await eval_repo.get_eval_results(a_id)
    results_b = await eval_repo.get_eval_results(b_id)

    return EvalComparisonResponse(
        run_a=EvalRunDetail(**run_a_obj.model_dump(), results=results_a),
        run_b=EvalRunDetail(**run_b_obj.model_dump(), results=results_b),
    )


@router.get("/evals/history", response_model=list[EvalHistoryPoint])
async def eval_history(category: str) -> list[EvalHistoryPoint]:
    """Score history for a category across all runs, for charting."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    rows = await eval_repo.get_eval_history(category)
    return [EvalHistoryPoint(**r) for r in rows]


@router.get("/evals/{eval_id}", response_model=EvalRunDetail)
async def get_eval_result(eval_id: uuid_mod.UUID) -> EvalRunDetail:
    """Full eval run with all results."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    run = await eval_repo.get_eval_run(eval_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    results = await eval_repo.get_eval_results(run.id)
    return EvalRunDetail(**run.model_dump(), results=results)


# ── Relationship Endpoints ────────────────────────────────────────


@router.get("/agents/{agent_id}/relationships")
async def get_agent_relationships(
    agent_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
) -> list[dict[str, Any]]:
    """All relationships for an agent in a simulation."""
    if simulation_id is None:
        raise HTTPException(status_code=400, detail="simulation_id query parameter required")
    db = _get_db()
    from core.repos.relationship_repo import RelationshipRepo
    repo = RelationshipRepo(db)
    relationships = await repo.get_all_for_agent(simulation_id, agent_id)
    return [r.model_dump(mode="json") for r in relationships]


@router.get("/agents/{agent_id}/relationships/{target_id}")
async def get_agent_relationship_detail(
    agent_id: str,
    target_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),  # noqa: B008
) -> dict[str, Any]:
    """Specific relationship with evolution timeline."""
    if simulation_id is None:
        raise HTTPException(status_code=400, detail="simulation_id query parameter required")
    db = _get_db()
    from core.repos.relationship_repo import RelationshipRepo
    repo = RelationshipRepo(db)
    rel = await repo.get(simulation_id, agent_id, target_id)
    if rel is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    data = rel.model_dump(mode="json")
    data["evolution"] = await repo.get_evolution(simulation_id, agent_id, target_id)
    return data


@router.get("/simulations/{sim_id}/assertions")
async def get_simulation_assertions(sim_id: uuid_mod.UUID) -> list[dict[str, Any]]:
    """All assertion results for a simulation."""
    db = _get_db()
    from core.repos.assertion_repo import AssertionRepo
    repo = AssertionRepo(db)
    return await repo.get_by_simulation(sim_id)


@router.get("/simulations/{sim_id}/assertions/summary")
async def get_simulation_assertions_summary(sim_id: uuid_mod.UUID) -> dict[str, Any]:
    """Pass/fail/warn summary for simulation assertions."""
    db = _get_db()
    from core.repos.assertion_repo import AssertionRepo
    repo = AssertionRepo(db)
    return await repo.get_pass_rates(sim_id)


@router.get("/simulations/{sim_id}/social-graph")
async def get_social_graph(sim_id: uuid_mod.UUID) -> list[dict[str, Any]]:
    """Full relationship matrix for a simulation."""
    db = _get_db()
    from core.repos.relationship_repo import RelationshipRepo
    repo = RelationshipRepo(db)
    relationships = await repo.get_social_graph(sim_id)
    return [r.model_dump(mode="json") for r in relationships]


@router.get("/simulations/{sim_id}/snapshots")
async def list_snapshots(sim_id: uuid_mod.UUID) -> list[dict[str, Any]]:
    """List available memory snapshots for a simulation."""
    import json
    from pathlib import Path

    snapshots_dir = Path("snapshots")
    results: list[dict[str, Any]] = []
    if not snapshots_dir.exists():
        return results

    for f in sorted(snapshots_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            source_id = data.get("source_simulation_id", "")
            if source_id == str(sim_id) or not source_id:
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


@router.get("/simulations/{sim_id}/snapshots/{filename}")
async def get_snapshot(sim_id: uuid_mod.UUID, filename: str) -> dict[str, Any]:
    """Read and return a specific snapshot file."""
    import json
    from pathlib import Path

    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    snapshot_path = Path("snapshots") / safe_name
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    try:
        data = json.loads(snapshot_path.read_text())
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/simulations/{sim_id}/snapshots")
async def create_snapshot(sim_id: uuid_mod.UUID) -> dict[str, Any]:
    """Export a new memory snapshot for this simulation."""
    import json
    from pathlib import Path
    from core.repos.memory_repo import MemoryRepo
    from core.repos.relationship_repo import RelationshipRepo
    from core.memory.snapshot import MemorySnapshotExporter

    db = _get_db()
    memory_repo = MemoryRepo(db)
    relationship_repo = RelationshipRepo(db)
    exporter = MemorySnapshotExporter(
        db=db, memory_repo=memory_repo, relationship_repo=relationship_repo,
    )
    snapshot_data = await exporter.export(str(sim_id))

    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(exist_ok=True)
    timestamp = snapshot_data.get("snapshot_at", "unknown").replace(":", "-").replace("+", "")[:19]
    filename = f"snapshot-{str(sim_id)[:8]}-{timestamp}.json"
    filepath = snapshots_dir / filename
    filepath.write_text(json.dumps(snapshot_data, indent=2, default=str))

    return {
        "filename": filename,
        "simulation_id": str(sim_id),
        "snapshot_at": snapshot_data.get("snapshot_at", ""),
        "agent_count": len(snapshot_data.get("agents", {})),
    }


@router.get("/simulations/{sim_id}/memory-current")
async def get_current_memory_state(sim_id: uuid_mod.UUID) -> dict[str, Any]:
    """Return current memory state for comparison with snapshots."""
    db = _get_db()
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    # Get agents from simulation
    row = await db.fetchrow(
        "SELECT agents_participated FROM simulations WHERE id = $1", sim_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Simulation not found")

    agents = row.get("agents_participated") or []
    result: dict[str, Any] = {"agents": {}}

    for agent_id in agents:
        agent_data: dict[str, Any] = {"core_memory": "", "recall_count": 0, "journal_count": 0}
        core = await memory_repo.get_core_memory(agent_id)
        if core:
            agent_data["core_memory"] = core.content

        recall, total_recall = await memory_repo.get_recall_memories_paginated(
            agent_id, limit=0
        )
        agent_data["recall_count"] = total_recall

        entries, total_journal = await memory_repo.get_journal_entries(agent_id, limit=0)
        agent_data["journal_count"] = total_journal

        result["agents"][agent_id] = agent_data

    return result


@router.get("/simulations/{sim_id}/report")
async def get_simulation_report(
    sim_id: uuid_mod.UUID,
    days: str | None = Query(default=None),
) -> dict[str, Any]:
    """Generate structured timeline report for a simulation."""
    db = _get_db()
    from core.repos.relationship_repo import RelationshipRepo
    from core.reporting.timeline_reporter import TimelineReporter

    relationship_repo = RelationshipRepo(db)
    reporter = TimelineReporter(
        db=db,
        simulation_id=str(sim_id),
        relationship_repo=relationship_repo,
    )
    day_list = None
    if days:
        try:
            day_list = [int(d.strip()) for d in days.split(",")]
        except ValueError:
            pass
    report = await reporter.generate(days=day_list, format="json")

    # Append launch-readiness scorecard
    from core.reporting.scorecard import LaunchScorecard
    from core.reporting.timeline_reporter import ReportSection
    from core.repos.assertion_repo import AssertionRepo

    assertion_repo = AssertionRepo(db)
    scorecard = LaunchScorecard(
        db=db,
        simulation_id=str(sim_id),
        assertion_repo=assertion_repo,
        relationship_repo=relationship_repo,
    )
    scorecard_result = await scorecard.evaluate()
    report.sections.append(ReportSection(
        title="Launch Readiness Scorecard",
        data=scorecard_result.to_dict(),
    ))

    return report.to_dict()


@router.post("/evals/{eval_id}/create-issues")
async def create_issues_from_eval(
    eval_id: uuid_mod.UUID,
    threshold: int = Query(default=60),
) -> list[dict[str, Any]]:
    """Generate GitHub issues from low-scoring eval categories."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo
    from core.eval.issue_generator import EvalIssueGenerator

    eval_repo = EvalRepo(db)
    generator = EvalIssueGenerator(
        db=db,
        eval_repo=eval_repo,
        eval_run_id=eval_id,
        score_threshold=threshold,
    )
    return await generator.generate_and_create()


@router.get("/evals/{eval_id}/export", response_model=EvalExportResponse)
async def export_eval(eval_id: uuid_mod.UUID) -> EvalExportResponse:
    """Export full eval results as JSON."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo

    eval_repo = EvalRepo(db)
    run = await eval_repo.get_eval_run(eval_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    results = await eval_repo.get_eval_results(run.id)
    return EvalExportResponse(eval_run=run, results=results)


# ── Config Version Endpoints ─────────────────────────────────────


def _get_config_version_repo():
    from core.main import app
    return app.state.services.config_version_repo


class RollbackRequest(BaseModel):
    version: int


@router.get("/config/agents/{agent_id}/versions")
async def get_agent_config_versions(
    agent_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """Get prompt version history for an agent."""
    repo = _get_config_version_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    versions = await repo.get_prompt_history(agent_id, limit=limit)
    return [v.model_dump(mode="json") for v in versions]


@router.post("/config/agents/{agent_id}/rollback")
async def rollback_agent_config(
    agent_id: str,
    body: RollbackRequest,
) -> dict:
    """Rollback an agent's config to a previous version."""
    repo = _get_config_version_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    try:
        await repo.rollback_prompt(agent_id, body.version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    # Hot-swap the agent config
    registry = _get_registry()
    await registry.reload_agent(agent_id)
    return {"status": "ok", "agent_id": agent_id, "version": body.version}


@router.get("/config/conversation/versions")
async def get_conversation_config_versions(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    """Get conversation parameter version history."""
    repo = _get_config_version_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    versions = await repo.get_conversation_param_history(limit=limit)
    return [v.model_dump(mode="json") for v in versions]


@router.post("/evals/{eval_id}/analyze")
async def analyze_eval(eval_id: uuid_mod.UUID) -> dict:
    """Run eval analyzer on a completed eval run."""
    db = _get_db()
    llm = _get_llm()
    from core.repos.eval_repo import EvalRepo
    from core.eval.analyzer import EvalAnalyzer

    eval_repo = EvalRepo(db)
    analyzer = EvalAnalyzer(db=db, eval_repo=eval_repo, llm_client=llm)
    try:
        result = await analyzer.analyze(eval_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result.model_dump()


@router.get("/evals/{eval_id}/analysis")
async def get_eval_analysis(eval_id: uuid_mod.UUID) -> dict:
    """Get stored analysis for an eval run."""
    db = _get_db()
    from core.repos.eval_repo import EvalRepo
    from core.eval.analyzer import EvalAnalyzer

    eval_repo = EvalRepo(db)
    llm = _get_llm()
    analyzer = EvalAnalyzer(db=db, eval_repo=eval_repo, llm_client=llm)
    result = await analyzer.get_analysis(eval_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No analysis found for this eval run")
    return result.model_dump()


@router.post("/config/conversation/rollback")
async def rollback_conversation_config(body: RollbackRequest) -> dict:
    """Rollback conversation params to a previous version."""
    repo = _get_config_version_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    try:
        await repo.rollback_conversation_params(body.version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "version": body.version}


# ── Evolution Loop Endpoints ─────────────────────────────────────


@router.get("/evolution/history")
async def get_evolution_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    """List all evolution loop runs."""
    db = _get_db()
    from core.repos.evolution_repo import EvolutionRepo

    repo = EvolutionRepo(db)
    return await repo.get_all_loops(limit=limit, offset=offset)


@router.get("/evolution/compare")
async def compare_evolution_cycles(
    cycle_a: uuid_mod.UUID = Query(...),
    cycle_b: uuid_mod.UUID = Query(...),
) -> dict:
    """Compare two evolution cycles side by side."""
    db = _get_db()
    from core.repos.evolution_repo import EvolutionRepo

    repo = EvolutionRepo(db)
    try:
        return await repo.compare_cycles(cycle_a, cycle_b)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/evolution/{loop_run_id}")
async def get_evolution_loop(loop_run_id: uuid_mod.UUID) -> list[dict]:
    """Get cycle details for a specific loop run."""
    db = _get_db()
    from core.repos.evolution_repo import EvolutionRepo

    repo = EvolutionRepo(db)
    cycles = await repo.get_loop_history(loop_run_id)
    return [c.model_dump(mode="json") for c in cycles]

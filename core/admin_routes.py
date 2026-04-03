"""Admin API endpoints for the debug dashboard.

Exposes agent internals, simulation data, conversation details,
artifacts, and eval results. Mounted at /api/admin.
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

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

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Agent metadata not stored in YAML configs — derived from character sheets.
AGENT_ROLES: dict[str, str] = {
    "vera": "Showrunner/Coordinator",
    "rex": "Engineer/Builder",
    "aurora": "Creative Director",
    "pixel": "Researcher/Audience Liaison",
    "fork": "Contrarian/Code Reviewer",
    "sentinel": "Budget Monitor/QA",
    "grok": "Wild Card/Provocateur",
    "overseer": "Content Filter",
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
    "overseer": "#95a5a6",
    "alpha": "#8e44ad",
}


def _get_db():
    """Lazy import to avoid circular dependency with core.main."""
    from core.main import db
    return db


def _get_registry():
    from core.main import agent_registry
    return agent_registry


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

    artifacts = await artifact_repo.get_artifacts_by_agent(
        agent_id, artifact_type=artifact_type, limit=limit
    )
    total = len(artifacts)
    # Apply offset manually since the base method doesn't support it
    paged = artifacts[offset:offset + limit]
    return PaginatedResponse(items=paged, total=total, limit=limit, offset=offset)


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
        CostByDay(date=d.get("date", ""), cost=d.get("cost", "0"))
        for d in data.get("by_day", [])
    ]
    by_type = [
        CostByType(
            type=d.get("type", ""),
            cost=d.get("cost", "0"),
            tokens=int(d.get("tokens", 0)),
        )
        for d in data.get("by_type", [])
    ]

    return CostBreakdownResponse(
        by_day=by_day,
        by_type=by_type,
        total=data.get("total", "0"),
        total_input_tokens=int(data.get("total_input_tokens", 0)),
        total_output_tokens=int(data.get("total_output_tokens", 0)),
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

    entries = await memory_repo.get_journal_entries(agent_id, limit=limit + offset)
    # Apply offset manually; repo method returns most recent entries
    paged = entries[offset:offset + limit]
    return PaginatedResponse(items=paged, total=len(entries), limit=limit, offset=offset)


# ── Simulation Endpoints ──────────────────────────────────────


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


@router.get("/simulations/{sim_id}/overseer-log")
async def get_simulation_overseer_log(
    sim_id: uuid_mod.UUID,
    severity_min: int = Query(1, ge=1, le=5),
) -> list[dict[str, Any]]:
    """All Overseer shadow flags from this simulation."""
    db = _get_db()
    from core.repos.simulation_repo import SimulationRepo
    sim_repo = SimulationRepo(db)

    return await sim_repo.get_overseer_log(sim_id, severity_min=severity_min)


@router.get("/simulations/{sim_id}/costs", response_model=SimulationCostResponse)
async def get_simulation_costs(sim_id: uuid_mod.UUID) -> SimulationCostResponse:
    """Cost breakdown by agent, by tool type, total."""
    db = _get_db()
    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)

    data = await cost_repo.get_costs_by_simulation(str(sim_id))
    return SimulationCostResponse(**data)


# ── Conversation Endpoints ─────────────────────────────────────


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(conv_id: uuid_mod.UUID) -> ConversationDetail:
    """Full conversation: transcript, participants, trigger, energy history."""
    db = _get_db()
    from core.repos.conversation_repo import ConversationRepo
    conv_repo = ConversationRepo(db)

    conv = await conv_repo.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    energy_log = await conv_repo.get_energy_log(conv_id)

    return ConversationDetail(
        id=conv.id,
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


# ── Eval Endpoints ─────────────────────────────────────────────


@router.get("/simulations/{sim_id}/evals")
async def get_simulation_evals(sim_id: uuid_mod.UUID) -> list[dict[str, Any]]:
    """All eval results for this simulation (placeholder)."""
    # Eval system not yet implemented — return empty list
    return []


@router.post("/simulations/{sim_id}/evals/run", response_model=EvalRunResponse)
async def run_simulation_evals(
    sim_id: uuid_mod.UUID, body: EvalRunRequest
) -> EvalRunResponse:
    """Trigger eval run (async, returns job ID)."""
    # Eval system not yet implemented — return placeholder job ID
    job_id = str(uuid_mod.uuid4())
    return EvalRunResponse(job_id=job_id, status="queued")


@router.get("/evals/{eval_id}")
async def get_eval_result(eval_id: str) -> dict[str, Any]:
    """Full eval result (placeholder)."""
    # Eval system not yet implemented
    raise HTTPException(status_code=404, detail="Eval system not yet implemented")

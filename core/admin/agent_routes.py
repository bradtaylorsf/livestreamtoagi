"""Agent inspection endpoints.

Provides agent profiles, system prompts, core/recall memory,
conversations, artifacts, costs, journal entries, and relationships.
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from core.admin.dependencies import get_db, get_registry
from core.constants import LIVE_SIMULATION_ID
from core.models import (
    AgentConfig,
    AgentDetail,
    AgentSummary,
    Artifact,
    Conversation,
    CoreMemoryResponse,
    CoreMemoryVersionEntry,
    CostBreakdownResponse,
    CostByDay,
    CostByType,
    JournalEntry,
    PaginatedResponse,
    PersonalityTraits,
    SystemPromptLayer,
    SystemPromptResponse,
)
from core.system_prompt import INFRASTRUCTURE_PROMPT

if TYPE_CHECKING:
    from datetime import datetime

    from core.agent_registry import AgentRegistry
    from core.database import Database

router = APIRouter(tags=["agents"])


def _agent_summary_from_config(
    a: AgentConfig, *, total_cost: float = 0, message_count: int = 0,
    conversation_count: int = 0, artifact_count: int = 0,
) -> AgentSummary:
    """Build AgentSummary from an AgentConfig object."""
    status = a.status.value if hasattr(a.status, "value") else str(a.status)
    return AgentSummary(
        id=a.id,
        display_name=a.display_name,
        role=a.role,
        color=a.color_hex,
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


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(
    registry: AgentRegistry = Depends(get_registry),
    db: Database = Depends(get_db),
) -> list[AgentSummary]:
    """List all agents with current status, total cost, message count."""
    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)

    agents = registry.get_all_agents()
    result = []
    for a in agents:
        costs = await cost_repo.get_costs_by_agent(a.id, simulation_id=LIVE_SIMULATION_ID)
        total = sum(c.amount for c in costs if c.amount) if costs else 0
        result.append(_agent_summary_from_config(
            a, total_cost=total, message_count=len(costs) if costs else 0,
        ))
    return result


@router.get("/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: str,
    registry: AgentRegistry = Depends(get_registry),
    db: Database = Depends(get_db),
) -> AgentDetail:
    """Full agent detail: config, personality traits, model assignments, voice."""
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    from core.repos.cost_repo import CostRepo
    cost_repo = CostRepo(db)
    costs = await cost_repo.get_costs_by_agent(agent_id, simulation_id=LIVE_SIMULATION_ID)
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
async def get_agent_system_prompt(
    agent_id: str,
    registry: AgentRegistry = Depends(get_registry),
    db: Database = Depends(get_db),
) -> SystemPromptResponse:
    """Current assembled system prompt (all 3 layers)."""
    agent = registry.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)
    core_mem = await memory_repo.get_core_memory(agent_id, simulation_id=LIVE_SIMULATION_ID)

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
async def get_agent_core_memory(
    agent_id: str,
    db: Database = Depends(get_db),
) -> CoreMemoryResponse:
    """Current core memory contents + version history."""
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    current = await memory_repo.get_core_memory(agent_id, simulation_id=LIVE_SIMULATION_ID)
    history = await memory_repo.get_core_memory_history(agent_id, simulation_id=LIVE_SIMULATION_ID)

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
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    db: Database = Depends(get_db),
) -> PaginatedResponse[dict[str, Any]]:
    """Paginated recall memories (embeddings hidden, content shown)."""
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    if search:
        memories, total = await memory_repo.search_recall_memories_by_keyword(
            agent_id, search, limit=limit, offset=offset, simulation_id=simulation_id,
        )
    else:
        memories, total = await memory_repo.get_recall_memories_paginated(
            agent_id, limit=limit, offset=offset, simulation_id=simulation_id,
        )

    items = []
    for m in memories:
        d = m.model_dump()
        d.pop("embedding", None)
        items.append(d)

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/agents/{agent_id}/conversations")
async def get_agent_conversations(
    agent_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> PaginatedResponse[Conversation]:
    """Paginated conversation history for this agent."""
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
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> PaginatedResponse[Artifact]:
    """All artifacts produced by this agent."""
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
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    db: Database = Depends(get_db),
) -> CostBreakdownResponse:
    """Cost breakdown: by day, by type, total."""
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
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_db),
) -> PaginatedResponse[JournalEntry]:
    """Journal entries with full content."""
    from core.repos.memory_repo import MemoryRepo
    memory_repo = MemoryRepo(db)

    entries, total = await memory_repo.get_journal_entries(
        agent_id, limit=limit, offset=offset, simulation_id=simulation_id,
    )
    return PaginatedResponse(items=entries, total=total, limit=limit, offset=offset)


@router.get("/agents/{agent_id}/relationships")
async def get_agent_relationships(
    agent_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """All relationships for an agent in a simulation."""
    if simulation_id is None:
        raise HTTPException(status_code=400, detail="simulation_id query parameter required")
    from core.repos.relationship_repo import RelationshipRepo
    repo = RelationshipRepo(db)
    relationships = await repo.get_all_for_agent(simulation_id, agent_id)
    return [r.model_dump(mode="json") for r in relationships]


@router.get("/agents/{agent_id}/relationships/{target_id}")
async def get_agent_relationship_detail(
    agent_id: str,
    target_id: str,
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Specific relationship with evolution timeline."""
    if simulation_id is None:
        raise HTTPException(status_code=400, detail="simulation_id query parameter required")
    from core.repos.relationship_repo import RelationshipRepo
    repo = RelationshipRepo(db)
    rel = await repo.get(simulation_id, agent_id, target_id)
    if rel is None:
        raise HTTPException(status_code=404, detail="Relationship not found")
    data = rel.model_dump(mode="json")
    data["evolution"] = await repo.get_evolution(simulation_id, agent_id, target_id)
    return data

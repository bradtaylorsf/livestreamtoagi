"""Config version and evolution loop endpoints.

Provides config version history, rollback, and evolution loop inspection.
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.admin.dependencies import get_config_version_repo, get_db, get_registry

if TYPE_CHECKING:
    from core.agent_registry import AgentRegistry
    from core.database import Database
    from core.repos.config_version_repo import ConfigVersionRepo

router = APIRouter(tags=["config"])


class RollbackRequest(BaseModel):
    version: int


@router.get("/config/agents/{agent_id}/versions")
async def get_agent_config_versions(
    agent_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    repo: ConfigVersionRepo = Depends(get_config_version_repo),
) -> list[dict]:
    """Get prompt version history for an agent."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    versions = await repo.get_prompt_history(agent_id, limit=limit, simulation_id=simulation_id)
    return [v.model_dump(mode="json") for v in versions]


@router.post("/config/agents/{agent_id}/rollback")
async def rollback_agent_config(
    agent_id: str,
    body: RollbackRequest,
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    repo: ConfigVersionRepo = Depends(get_config_version_repo),
    registry: AgentRegistry = Depends(get_registry),
) -> dict:
    """Rollback an agent's config to a previous version."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    try:
        await repo.rollback_prompt(agent_id, body.version, simulation_id=simulation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await registry.reload_agent(agent_id)
    return {"status": "ok", "agent_id": agent_id, "version": body.version}


@router.get("/config/conversation/versions")
async def get_conversation_config_versions(
    limit: int = Query(default=20, ge=1, le=100),
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    repo: ConfigVersionRepo = Depends(get_config_version_repo),
) -> list[dict]:
    """Get conversation parameter version history."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    versions = await repo.get_conversation_param_history(limit=limit, simulation_id=simulation_id)
    return [v.model_dump(mode="json") for v in versions]


@router.post("/config/conversation/rollback")
async def rollback_conversation_config(
    body: RollbackRequest,
    simulation_id: uuid_mod.UUID | None = Query(default=None),
    repo: ConfigVersionRepo = Depends(get_config_version_repo),
) -> dict:
    """Rollback conversation params to a previous version."""
    if repo is None:
        raise HTTPException(status_code=503, detail="Config version repo not available")
    try:
        await repo.rollback_conversation_params(body.version, simulation_id=simulation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "version": body.version}


@router.get("/evolution/history")
async def get_evolution_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
) -> list[dict]:
    """List all evolution loop runs."""
    from core.repos.evolution_repo import EvolutionRepo

    repo = EvolutionRepo(db)
    return await repo.get_all_loops(limit=limit, offset=offset)


@router.get("/evolution/compare")
async def compare_evolution_cycles(
    cycle_a: uuid_mod.UUID = Query(...),
    cycle_b: uuid_mod.UUID = Query(...),
    db: Database = Depends(get_db),
) -> dict:
    """Compare two evolution cycles side by side."""
    from core.repos.evolution_repo import EvolutionRepo

    repo = EvolutionRepo(db)
    try:
        return await repo.compare_cycles(cycle_a, cycle_b)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/evolution/{loop_run_id}")
async def get_evolution_loop(
    loop_run_id: uuid_mod.UUID,
    db: Database = Depends(get_db),
) -> list[dict]:
    """Get cycle details for a specific loop run."""
    from core.repos.evolution_repo import EvolutionRepo

    repo = EvolutionRepo(db)
    cycles = await repo.get_loop_history(loop_run_id)
    return [c.model_dump(mode="json") for c in cycles]

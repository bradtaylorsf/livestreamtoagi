"""Read-only bridge handlers for the memory subsystem."""

from __future__ import annotations

import uuid
from typing import Any

from core.bridge.contract import BridgeRequest, MemoryRecallRequest


def _simulation_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


async def handle_memory_read(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Read core or recall memory through the existing memory managers only."""
    payload = MemoryRecallRequest.model_validate(env.payload)
    simulation_id = _simulation_uuid(env.simulation_id)

    if payload.tier == "core":
        core_memory = await services.core_memory.get_core_memory(
            env.agent_id,
            simulation_id=simulation_id,
        )
        return {"results": [], "core_memory": core_memory}

    formatted = await services.recall_memory.retrieve_recall_memories(
        env.agent_id,
        payload.query,
        limit=payload.limit,
        simulation_id=simulation_id,
    )
    return {"results": [], "formatted": formatted}

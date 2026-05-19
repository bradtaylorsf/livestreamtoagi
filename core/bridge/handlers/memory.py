"""Bridge handlers for the memory subsystem.

The memory backend protocol in ``core.memory`` is the single source of truth for
Tier 2 recall reads, with ``RecallMemoryManager`` behind the default backend.
``CoreMemoryManager.get_core_memory`` remains the Tier 1 core read path, and
``MemoryCompactor.compact_interaction`` remains the append/write compaction
path. These bridge verbs intentionally stay thin adapters over that manager
layer. The recall bridge path uses the same method and arguments as
``tools.memory_tools.RecallMemoryTool``; core reads and writes delegate directly
to their source-of-truth managers rather than introducing bridge-specific
memory logic.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.bridge.contract import BridgeRequest, MemoryRecallRequest, MemoryWriteRequest


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

    recall_backend = getattr(services, "memory_backend", None) or services.recall_memory
    formatted = await recall_backend.retrieve_recall_memories(
        env.agent_id,
        payload.query,
        limit=payload.limit,
        simulation_id=simulation_id,
    )
    return {"results": [], "formatted": formatted}


async def handle_memory_write(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Append memory through the existing compactor write path only."""
    payload = MemoryWriteRequest.model_validate(env.payload)
    metadata = payload.metadata
    result = await services.compactor.compact_interaction(
        agent_id=env.agent_id,
        interaction=payload.content,
        event_type=payload.kind,
        participants=metadata.get("participants") or [env.agent_id],
        conversation_id=metadata.get("conversation_id"),
    )
    if result is None:
        raise ValueError("memory.write produced no memory for empty content")
    return {"memory_id": str(result.recall_memory.id)}

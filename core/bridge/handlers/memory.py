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

import asyncio
import logging
import uuid
from typing import Any
from weakref import WeakValueDictionary

from core.bridge.contract import BridgeRequest, MemoryRecallRequest, MemoryWriteRequest

logger = logging.getLogger(__name__)

MEMORY_WRITE_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_MEMORY_WRITE_CACHE_ATTR = "_bridge_memory_write_cache"
_MEMORY_WRITE_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_MEMORY_WRITE_LOCKS_GUARD = asyncio.Lock()


def _simulation_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError):
        return None


def _memory_write_idempotency_key(env: BridgeRequest) -> str:
    return f"bridge:memory.write:{env.simulation_id}:{env.agent_id}:{env.request_id}"


async def _memory_write_lock(key: str) -> asyncio.Lock:
    async with _MEMORY_WRITE_LOCKS_GUARD:
        lock = _MEMORY_WRITE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _MEMORY_WRITE_LOCKS[key] = lock
        return lock


def _local_memory_write_cache(services: Any) -> dict[str, str]:
    cache = getattr(services, _MEMORY_WRITE_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(services, _MEMORY_WRITE_CACHE_ATTR, cache)
    return cache


def _idempotency_redis(services: Any) -> Any | None:
    return getattr(services, "scoped_redis", None) or getattr(services, "redis", None)


async def _cached_memory_write_id(services: Any, key: str) -> str | None:
    redis = _idempotency_redis(services)
    if redis is not None:
        try:
            return await redis.get(key)
        except Exception:
            logger.warning(
                "Memory write idempotency lookup failed; falling back to process cache",
                exc_info=True,
            )
    return _local_memory_write_cache(services).get(key)


async def _cache_memory_write_id(services: Any, key: str, memory_id: str) -> None:
    redis = _idempotency_redis(services)
    if redis is not None:
        try:
            await redis.set(key, memory_id, ex=MEMORY_WRITE_IDEMPOTENCY_TTL_SECONDS)
            return
        except Exception:
            logger.warning(
                "Memory write idempotency store failed; falling back to process cache",
                exc_info=True,
            )
    _local_memory_write_cache(services)[key] = memory_id


def _log_memory_read(
    *,
    agent_id: str,
    tier: str,
    simulation_id: uuid.UUID | None,
    result_size: int,
) -> None:
    fields = {
        "agent_id": agent_id,
        "tier": tier,
        "simulation_id": str(simulation_id) if simulation_id is not None else None,
        "result_size": result_size,
    }
    logger.info(
        "bridge_memory_read agent_id=%s tier=%s simulation_id=%s result_size=%s",
        fields["agent_id"],
        fields["tier"],
        fields["simulation_id"] or "-",
        fields["result_size"],
        extra={"bridge_memory": fields},
    )


async def handle_memory_read(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Read core or recall memory through the existing memory managers only."""
    payload = MemoryRecallRequest.model_validate(env.payload)
    simulation_id = _simulation_uuid(env.simulation_id)

    if payload.tier == "core":
        core_memory = await services.core_memory.get_core_memory(
            env.agent_id,
            simulation_id=simulation_id,
        )
        _log_memory_read(
            agent_id=env.agent_id,
            tier=payload.tier,
            simulation_id=simulation_id,
            result_size=len(core_memory or ""),
        )
        return {"results": [], "core_memory": core_memory}

    recall_backend = getattr(services, "memory_backend", None) or services.recall_memory
    formatted = await recall_backend.retrieve_recall_memories(
        env.agent_id,
        payload.query,
        limit=payload.limit,
        simulation_id=simulation_id,
    )
    _log_memory_read(
        agent_id=env.agent_id,
        tier=payload.tier,
        simulation_id=simulation_id,
        result_size=len(formatted or ""),
    )
    return {"results": [], "formatted": formatted}


async def handle_memory_write(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Append memory through the existing compactor write path, idempotent on request_id."""
    payload = MemoryWriteRequest.model_validate(env.payload)
    metadata = payload.metadata
    idempotency_key = _memory_write_idempotency_key(env)
    lock = await _memory_write_lock(idempotency_key)
    async with lock:
        cached_memory_id = await _cached_memory_write_id(services, idempotency_key)
        if cached_memory_id is not None:
            return {"memory_id": cached_memory_id}

        result = await services.compactor.compact_interaction(
            agent_id=env.agent_id,
            interaction=payload.content,
            event_type=payload.kind,
            participants=metadata.get("participants") or [env.agent_id],
            conversation_id=metadata.get("conversation_id"),
        )
        if result is None:
            raise ValueError("memory.write produced no memory for empty content")

        memory_id = str(result.recall_memory.id)
        await _cache_memory_write_id(services, idempotency_key, memory_id)
        return {"memory_id": memory_id}

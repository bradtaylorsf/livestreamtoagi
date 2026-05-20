"""Bridge handlers for Alpha errand outcomes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from weakref import WeakValueDictionary

from core.bridge.contract import BridgeRequest, ErrandCompleteRequest
from core.bridge.errand_queue import errand_queue

logger = logging.getLogger(__name__)

ERRAND_COMPLETE_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_ERRAND_COMPLETE_CACHE_ATTR = "_bridge_errand_complete_cache"
_ERRAND_COMPLETE_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_ERRAND_COMPLETE_LOCKS_GUARD = asyncio.Lock()


def _errand_complete_idempotency_key(env: BridgeRequest, task_id: str) -> str:
    return f"bridge:errand.complete:{env.simulation_id}:{task_id}"


async def _errand_complete_lock(key: str) -> asyncio.Lock:
    async with _ERRAND_COMPLETE_LOCKS_GUARD:
        lock = _ERRAND_COMPLETE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _ERRAND_COMPLETE_LOCKS[key] = lock
        return lock


def _local_errand_complete_cache(services: Any) -> dict[str, str]:
    cache = getattr(services, _ERRAND_COMPLETE_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(services, _ERRAND_COMPLETE_CACHE_ATTR, cache)
    return cache


def _idempotency_redis(services: Any) -> Any | None:
    return getattr(services, "scoped_redis", None) or getattr(services, "redis", None)


async def _cached_errand_memory_id(services: Any, key: str) -> str | None:
    redis = _idempotency_redis(services)
    if redis is not None:
        try:
            return await redis.get(key)
        except Exception:
            logger.warning(
                "Errand completion idempotency lookup failed; falling back to process cache",
                exc_info=True,
            )
    return _local_errand_complete_cache(services).get(key)


async def _cache_errand_memory_id(services: Any, key: str, memory_id: str) -> None:
    redis = _idempotency_redis(services)
    if redis is not None:
        try:
            await redis.set(key, memory_id, ex=ERRAND_COMPLETE_IDEMPOTENCY_TTL_SECONDS)
            return
        except Exception:
            logger.warning(
                "Errand completion idempotency store failed; falling back to process cache",
                exc_info=True,
            )
    _local_errand_complete_cache(services)[key] = memory_id


def _participants(agent_id: str, from_agent: str | None) -> list[str]:
    participants = [agent_id]
    if from_agent and from_agent not in participants:
        participants.append(from_agent)
    return participants


def _format_errand_outcome(
    env: BridgeRequest,
    payload: ErrandCompleteRequest,
    *,
    from_agent: str | None,
) -> str:
    lines = [
        "Errand outcome:",
        f"- task_id: {payload.task_id}",
        f"- agent_id: {env.agent_id}",
    ]
    if from_agent:
        lines.append(f"- from_agent: {from_agent}")
    lines.extend(
        [
            f"- outcome: {payload.symbol} {payload.status}",
            f"- detail: {payload.detail}",
        ]
    )

    if not payload.step_results:
        lines.append("- step_results: []")
        return "\n".join(lines)

    lines.append("- step_results:")
    for step in payload.step_results:
        lines.extend(
            [
                f"  - action_id: {step.action_id}",
                f"    status: {step.status}",
                f"    detail: {step.detail}",
            ]
        )
    return "\n".join(lines)


async def handle_errand_complete(env: BridgeRequest, services: Any | None) -> dict[str, Any]:
    """Record an errand completion and persist its outcome through memory compaction.

    The bridge-visible ack is deliberately independent from durable memory
    availability: Alpha's completion should not be retried forever just because
    the memory subsystem is down. Successful memory writes are idempotent by
    simulation/task id so duplicate completion frames do not create duplicate
    memories.
    """
    payload = ErrandCompleteRequest.model_validate(env.payload)
    from_agent = errand_queue.from_agent_for(payload.task_id)
    errand_queue.record_completion(
        payload.task_id,
        payload.status,
        payload.symbol,
        payload.detail,
        [step.model_dump() for step in payload.step_results],
    )

    compactor = getattr(services, "compactor", None) if services is not None else None
    if compactor is None:
        logger.warning(
            "Errand completion accepted without durable memory; memory compactor unavailable",
            extra={"agent_id": env.agent_id, "task_id": payload.task_id},
        )
        return {"accepted": True}

    idempotency_key = _errand_complete_idempotency_key(env, payload.task_id)
    lock = await _errand_complete_lock(idempotency_key)
    async with lock:
        cached_memory_id = await _cached_errand_memory_id(services, idempotency_key)
        if cached_memory_id is not None:
            return {"accepted": True}

        try:
            result = await compactor.compact_interaction(
                agent_id=env.agent_id,
                interaction=_format_errand_outcome(env, payload, from_agent=from_agent),
                event_type="errand_outcome",
                participants=_participants(env.agent_id, from_agent),
                conversation_id=None,
            )
        except Exception:
            logger.warning(
                "Errand completion accepted but durable memory write failed",
                exc_info=True,
                extra={"agent_id": env.agent_id, "task_id": payload.task_id},
            )
            return {"accepted": True}

        if result is None:
            logger.warning(
                "Errand completion accepted but durable memory write returned no memory",
                extra={"agent_id": env.agent_id, "task_id": payload.task_id},
            )
            return {"accepted": True}

        await _cache_errand_memory_id(
            services,
            idempotency_key,
            str(result.recall_memory.id),
        )
        return {"accepted": True}

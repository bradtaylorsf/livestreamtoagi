"""In-process Alpha errand delivery queue for the Minecraft bridge (E7-2)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ErrandUrgency = Literal["when_free", "now"]

DEFAULT_DUPLICATE_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class Errand:
    """One dispatched task waiting for a bridge bot to poll it."""

    agent_id: str
    task_id: str
    task: str
    from_agent: str
    urgency: ErrandUrgency
    dispatched_at_ms: int


class ErrandQueue:
    """FIFO errand queues keyed by agent id with short-lived idempotency."""

    def __init__(
        self, *, duplicate_ttl_seconds: float = DEFAULT_DUPLICATE_TTL_SECONDS
    ) -> None:
        self._duplicate_ttl_seconds = duplicate_ttl_seconds
        self._queues: dict[str, asyncio.Queue[Errand]] = {}
        self._seen_task_ids: dict[str, float] = {}

    def enqueue(
        self,
        agent_id: str,
        task_id: str,
        task: str,
        from_agent: str,
        urgency: ErrandUrgency = "when_free",
    ) -> bool:
        """Queue an errand for *agent_id*.

        Returns ``False`` when *task_id* was already accepted within the
        duplicate TTL. The duplicate window intentionally survives polling so a
        retried dispatch cannot re-deliver the same task immediately.
        """
        now = time.monotonic()
        self._prune_seen(now)
        if task_id in self._seen_task_ids:
            return False

        key = _agent_key(agent_id)
        queue = self._queues.setdefault(key, asyncio.Queue())
        queue.put_nowait(
            Errand(
                agent_id=key,
                task_id=task_id,
                task=task,
                from_agent=from_agent,
                urgency=urgency,
                dispatched_at_ms=int(time.time() * 1000),
            )
        )
        self._seen_task_ids[task_id] = now + self._duplicate_ttl_seconds
        return True

    def poll(self, agent_id: str) -> Errand | None:
        """Return the next pending errand for *agent_id*, or ``None``."""
        queue = self._queues.get(_agent_key(agent_id))
        if queue is None:
            return None
        try:
            return queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def clear(self, *, agent_ids: Iterable[str] | None = None) -> None:
        """Clear queued errands and duplicate state.

        Primarily used for tests; production code should let tasks drain by
        polling.
        """
        if agent_ids is None:
            self._queues.clear()
            self._seen_task_ids.clear()
            return
        for agent_id in agent_ids:
            self._queues.pop(_agent_key(agent_id), None)
        self._seen_task_ids.clear()

    def _prune_seen(self, now: float) -> None:
        expired = [
            task_id
            for task_id, expires_at in self._seen_task_ids.items()
            if expires_at <= now
        ]
        for task_id in expired:
            self._seen_task_ids.pop(task_id, None)


def _agent_key(agent_id: str) -> str:
    return str(agent_id).strip().lower()


errand_queue = ErrandQueue()

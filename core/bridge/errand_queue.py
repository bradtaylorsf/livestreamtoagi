"""In-process Alpha errand delivery queue for the Minecraft bridge (E7-2)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

ErrandUrgency = Literal["when_free", "now"]
ErrandStatus = Literal["success", "failure", "partial"]
ErrandSymbol = Literal["✓", "✗", "?"]

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


@dataclass(frozen=True)
class ErrandResult:
    """Verified completion reported by Alpha for one dispatched errand."""

    task_id: str
    status: ErrandStatus
    symbol: ErrandSymbol
    detail: str
    step_results: tuple[dict[str, str], ...]
    completed_at_ms: int


class ErrandQueue:
    """FIFO errand queues keyed by agent id with short-lived idempotency."""

    def __init__(
        self, *, duplicate_ttl_seconds: float = DEFAULT_DUPLICATE_TTL_SECONDS
    ) -> None:
        self._duplicate_ttl_seconds = duplicate_ttl_seconds
        self._queues: dict[str, asyncio.Queue[Errand]] = {}
        self._seen_task_ids: dict[str, float] = {}
        self._dispatchers: dict[str, str] = {}
        self._completion_expires_at: dict[str, float] = {}
        self._completions: dict[str, ErrandResult] = {}

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
        self._prune_expired(now)
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
        self._dispatchers[task_id] = from_agent
        return True

    def poll(self, agent_id: str) -> Errand | None:
        """Return the next pending errand for *agent_id*, or ``None``."""
        self._prune_expired(time.monotonic())
        queue = self._queues.get(_agent_key(agent_id))
        if queue is None:
            return None
        try:
            return queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def record_completion(
        self,
        task_id: str,
        status: ErrandStatus,
        symbol: ErrandSymbol,
        detail: str,
        step_results: Iterable[dict[str, str]],
    ) -> ErrandResult:
        """Record Alpha's verified completion for *task_id*.

        Durable memory persistence is wired by the bridge completion handler.
        This short-lived cache remains the bridge-visible handoff proving the
        errand surfaced a verified ✓/✗/? outcome.
        """
        now = time.monotonic()
        self._prune_expired(now)
        result = ErrandResult(
            task_id=task_id,
            status=status,
            symbol=symbol,
            detail=detail,
            step_results=tuple(dict(step) for step in step_results),
            completed_at_ms=int(time.time() * 1000),
        )
        self._completions[task_id] = result
        self._completion_expires_at[task_id] = now + self._duplicate_ttl_seconds
        return result

    def get_completion(self, task_id: str) -> ErrandResult | None:
        """Return a recently reported errand completion, if still retained."""
        self._prune_expired(time.monotonic())
        return self._completions.get(task_id)

    def from_agent_for(self, task_id: str) -> str | None:
        """Return the dispatcher for a recently queued task, if still retained."""
        self._prune_expired(time.monotonic())
        return self._dispatchers.get(task_id)

    def clear(self, *, agent_ids: Iterable[str] | None = None) -> None:
        """Clear queued errands and duplicate state.

        Primarily used for tests; production code should let tasks drain by
        polling.
        """
        if agent_ids is None:
            self._queues.clear()
            self._seen_task_ids.clear()
            self._dispatchers.clear()
            self._completion_expires_at.clear()
            self._completions.clear()
            return
        for agent_id in agent_ids:
            self._queues.pop(_agent_key(agent_id), None)
        self._seen_task_ids.clear()
        self._dispatchers.clear()
        self._completion_expires_at.clear()
        self._completions.clear()

    def _prune_expired(self, now: float) -> None:
        expired = [
            task_id
            for task_id, expires_at in self._seen_task_ids.items()
            if expires_at <= now
        ]
        for task_id in expired:
            self._seen_task_ids.pop(task_id, None)
            self._dispatchers.pop(task_id, None)
        expired_results = [
            task_id
            for task_id, expires_at in self._completion_expires_at.items()
            if expires_at <= now
        ]
        for task_id in expired_results:
            self._completion_expires_at.pop(task_id, None)
            self._completions.pop(task_id, None)


def _agent_key(agent_id: str) -> str:
    return str(agent_id).strip().lower()


errand_queue = ErrandQueue()

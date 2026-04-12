"""Shared working state -- a task board all agents can read and write."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.redis_keys import ScopedRedis


TASK_KEY = "shared:tasks"
DECISIONS_KEY = "shared:decisions"
PRIORITIES_KEY = "shared:priorities"
BUDGET_KEY = "shared:budget_status"

# Completed tasks older than this are pruned to prevent context bloat
_COMPLETED_TASK_TTL = 3600  # 1 hour
_MAX_COMPLETED_TASKS = 10


@dataclass
class SharedTask:
    id: str
    title: str
    owner: str
    status: str = "pending"  # pending, in_progress, done, blocked
    created_at: float = field(default_factory=time.time)
    blocked_reason: str | None = None


@dataclass
class Decision:
    summary: str
    made_by: list[str]
    timestamp: float = field(default_factory=time.time)


class SharedWorkingState:
    """Redis-backed shared state for agent coordination."""

    def __init__(self, redis: ScopedRedis) -> None:
        self._redis = redis

    async def add_task(self, task: SharedTask) -> None:
        await self._redis.hset(TASK_KEY, task.id, json.dumps(asdict(task)))

    async def update_task_status(
        self,
        task_id: str,
        status: str,
        blocked_reason: str | None = None,
        owner: str | None = None,
    ) -> bool:
        """Update a task's status. Returns True if the task was found and updated."""
        raw = await self._redis.hget(TASK_KEY, task_id)
        if raw:
            data = json.loads(raw)
            data["status"] = status
            if blocked_reason:
                data["blocked_reason"] = blocked_reason
            if owner:
                data["owner"] = owner
            await self._redis.hset(TASK_KEY, task_id, json.dumps(data))
            # Auto-prune old completed tasks when new ones are finished
            if status == "done":
                await self.prune_completed_tasks()
            return True
        return False

    async def get_tasks(self) -> list[SharedTask]:
        raw_all = await self._redis.hgetall(TASK_KEY)
        return [SharedTask(**json.loads(v)) for v in raw_all.values()]

    async def prune_completed_tasks(self) -> int:
        """Remove old completed tasks to prevent unbounded growth.

        Keeps at most _MAX_COMPLETED_TASKS completed tasks, and removes any
        completed task older than _COMPLETED_TASK_TTL seconds.
        Returns the number of tasks pruned.
        """
        tasks = await self.get_tasks()
        done = sorted(
            [t for t in tasks if t.status == "done"],
            key=lambda t: t.created_at,
        )
        now = time.time()
        pruned = 0
        for t in done:
            age = now - t.created_at
            excess = len(done) - pruned > _MAX_COMPLETED_TASKS
            if age > _COMPLETED_TASK_TTL or excess:
                await self._redis.hdel(TASK_KEY, t.id)
                pruned += 1
        return pruned

    async def add_decision(self, decision: Decision) -> None:
        await self._redis.rpush(DECISIONS_KEY, json.dumps(asdict(decision)))

    async def get_recent_decisions(self, count: int = 5) -> list[Decision]:
        raw = await self._redis.lrange(DECISIONS_KEY, -count, -1)
        return [Decision(**json.loads(r)) for r in raw]

    async def set_priorities(
        self,
        priorities: list[str],
        set_by: str,
    ) -> None:
        await self._redis.set(
            PRIORITIES_KEY,
            json.dumps(
                {
                    "priorities": priorities,
                    "set_by": set_by,
                    "timestamp": time.time(),
                }
            ),
        )

    async def get_priorities(self) -> dict[str, object] | None:
        raw = await self._redis.get(PRIORITIES_KEY)
        return json.loads(raw) if raw else None

    async def seed_initial_tasks(self) -> None:
        """Populate the task board with starter tasks for each agent.

        Safe to call multiple times — skips if tasks already exist.
        """
        existing = await self.get_tasks()
        if existing:
            return

        seeds = [
            SharedTask(
                id="seed-vera-revenue",
                title="Set up revenue streams — brainstorm and evaluate monetization options",
                owner="vera",
            ),
            SharedTask(
                id="seed-rex-build",
                title="Design and build first world area",
                owner="rex",
            ),
            SharedTask(
                id="seed-pixel-social",
                title="Create initial social media presence",
                owner="pixel",
            ),
            SharedTask(
                id="seed-fork-review",
                title="Review and critique revenue proposals",
                owner="fork",
            ),
            SharedTask(
                id="seed-sentinel-budget",
                title="Establish budget tracking and cost monitoring",
                owner="sentinel",
            ),
            SharedTask(
                id="seed-aurora-creative",
                title="Design creative content for the stream",
                owner="aurora",
            ),
            SharedTask(
                id="seed-grok-marketing",
                title="Explore viral marketing angles",
                owner="grok",
            ),
        ]
        for task in seeds:
            await self.add_task(task)

    async def get_summary_for_context(self) -> str:
        """Build a text summary suitable for injection into agent context."""
        lines: list[str] = []

        # Current priorities
        priorities = await self.get_priorities()
        if priorities:
            pri_list = priorities.get("priorities", [])
            set_by = priorities.get("set_by", "unknown")
            if isinstance(pri_list, list):
                lines.append(
                    f"**Current priorities** (set by {set_by}): "
                    f"{', '.join(str(p) for p in pri_list)}"
                )

        # Active tasks
        tasks = await self.get_tasks()
        active = [t for t in tasks if t.status in ("pending", "in_progress", "blocked")]
        if active:
            lines.append("**Active tasks:**")
            status_icons = {
                "pending": "[pending]",
                "in_progress": "[in progress]",
                "blocked": "[blocked]",
            }
            for t in active[:8]:
                icon = status_icons.get(t.status, "[?]")
                line = f"  {icon} {t.title} (owner: {t.owner}, status: {t.status})"
                if t.blocked_reason:
                    line += f" -- blocked: {t.blocked_reason}"
                lines.append(line)

        # Recent decisions
        decisions = await self.get_recent_decisions(3)
        if decisions:
            lines.append("**Recent decisions:**")
            for d in decisions:
                lines.append(f"  - {d.summary} (by {', '.join(d.made_by)})")

        return "\n".join(lines) if lines else ""

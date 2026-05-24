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
RESOURCES_KEY = "shared:resources"
CLAIMS_KEY = "shared:claims"
DANGERS_KEY = "shared:dangers"
VERIFIED_ACTIONS_KEY = "shared:verified_actions"
BUILD_SITE_KEY = "shared:build_site"
GOAL_KEY = "shared:goal"
NEXT_STEPS_KEY = "shared:next_steps"

# Completed tasks older than this are pruned to prevent context bloat
_COMPLETED_TASK_TTL = 3600  # 1 hour
_MAX_COMPLETED_TASKS = 10
_MAX_RECENT_DANGERS = 25
_MAX_RECENT_VERIFIED_ACTIONS = 25
_MAX_NEXT_STEPS = 25


def _loads(raw: str | bytes) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


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


@dataclass
class ResourceEntry:
    id: str
    kind: str
    location: dict[str, object] | str
    quantity: int | float | None
    reported_by: str
    updated_at: float = field(default_factory=time.time)


@dataclass
class AgentClaim:
    agent_id: str
    target: str
    role: str
    claimed_by: str | None = None
    claimed_at: float = field(default_factory=time.time)
    expires_at: float | None = None


@dataclass
class DangerReport:
    agent_id: str
    kind: str
    location: dict[str, object] | str | None
    severity: int
    reported_by: str | None = None
    reported_at: float = field(default_factory=time.time)


@dataclass
class VerifiedAction:
    agent_id: str
    action: str
    result: str
    observed_at: float = field(default_factory=time.time)


@dataclass
class BuildSite:
    site_id: str
    location: dict[str, object] | str
    name: str
    status: str


@dataclass
class GroupGoal:
    text: str
    set_by: str
    set_at: float = field(default_factory=time.time)


@dataclass
class NextStep:
    text: str
    added_by: str
    added_at: float = field(default_factory=time.time)


class SharedWorkingState:
    """Redis-backed shared state for agent coordination.

    Run scoping is provided by ``ScopedRedis``: callers pass a Redis proxy whose
    keys are already prefixed by simulation id, so every key below is local to
    one embodied run.
    """

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
            data = _loads(raw)
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
        return [SharedTask(**_loads(v)) for v in raw_all.values()]

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
        return [Decision(**_loads(r)) for r in raw]

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
        return _loads(raw) if raw else None

    async def set_group_goal(self, goal: GroupGoal) -> None:
        await self._redis.set(GOAL_KEY, json.dumps(asdict(goal)))

    async def get_group_goal(self) -> GroupGoal | None:
        raw = await self._redis.get(GOAL_KEY)
        return GroupGoal(**_loads(raw)) if raw else None

    async def upsert_resource(self, resource: ResourceEntry) -> None:
        await self._redis.hset(RESOURCES_KEY, resource.id, json.dumps(asdict(resource)))

    async def get_resources(self) -> list[ResourceEntry]:
        raw_all = await self._redis.hgetall(RESOURCES_KEY)
        resources = [ResourceEntry(**_loads(v)) for v in raw_all.values()]
        return sorted(resources, key=lambda r: (r.kind, r.id))

    async def set_agent_claim(self, claim: AgentClaim) -> None:
        await self._redis.hset(CLAIMS_KEY, claim.agent_id, json.dumps(asdict(claim)))

    async def get_agent_claims(self) -> list[AgentClaim]:
        raw_all = await self._redis.hgetall(CLAIMS_KEY)
        claims = [AgentClaim(**_loads(v)) for v in raw_all.values()]
        return sorted(claims, key=lambda c: c.agent_id)

    async def report_danger(self, report: DangerReport) -> None:
        await self._redis.rpush(DANGERS_KEY, json.dumps(asdict(report)))
        await self._redis.ltrim(DANGERS_KEY, -_MAX_RECENT_DANGERS, -1)

    async def get_danger_reports(self, count: int = _MAX_RECENT_DANGERS) -> list[DangerReport]:
        raw = await self._redis.lrange(DANGERS_KEY, -count, -1)
        return [DangerReport(**_loads(r)) for r in raw]

    async def record_verified_action(self, action: VerifiedAction) -> None:
        await self._redis.rpush(VERIFIED_ACTIONS_KEY, json.dumps(asdict(action)))
        await self._redis.ltrim(VERIFIED_ACTIONS_KEY, -_MAX_RECENT_VERIFIED_ACTIONS, -1)

    async def get_recent_verified_actions(
        self,
        count: int = _MAX_RECENT_VERIFIED_ACTIONS,
    ) -> list[VerifiedAction]:
        raw = await self._redis.lrange(VERIFIED_ACTIONS_KEY, -count, -1)
        return [VerifiedAction(**_loads(r)) for r in raw]

    async def set_build_site(self, site: BuildSite) -> None:
        await self._redis.set(BUILD_SITE_KEY, json.dumps(asdict(site)))

    async def get_build_site(self) -> BuildSite | None:
        raw = await self._redis.get(BUILD_SITE_KEY)
        return BuildSite(**_loads(raw)) if raw else None

    async def add_next_step(self, step: NextStep) -> None:
        await self._redis.rpush(NEXT_STEPS_KEY, json.dumps(asdict(step)))
        await self._redis.ltrim(NEXT_STEPS_KEY, -_MAX_NEXT_STEPS, -1)

    async def get_next_steps(self, count: int = _MAX_NEXT_STEPS) -> list[NextStep]:
        raw = await self._redis.lrange(NEXT_STEPS_KEY, -count, -1)
        return [NextStep(**_loads(r)) for r in raw]

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
        goal = await self.get_group_goal()
        if goal:
            lines.append(f"**Active group goal** (set by {goal.set_by}): {goal.text}")

        build_site = await self.get_build_site()
        if build_site:
            lines.append(
                "**Build site:** "
                f"{build_site.name} ({build_site.site_id}) at {build_site.location}; "
                f"status: {build_site.status}"
            )

        claims = await self.get_agent_claims()
        if claims:
            lines.append("**Agent claims:**")
            for claim in claims[:8]:
                claimed_by = claim.claimed_by or claim.agent_id
                lines.append(
                    f"  - {claim.agent_id}: {claim.role} on {claim.target} "
                    f"(claimed by {claimed_by})"
                )

        resources = await self.get_resources()
        if resources:
            lines.append("**Known resources:**")
            for resource in resources[:8]:
                qty = "" if resource.quantity is None else f" x{resource.quantity}"
                lines.append(
                    f"  - {resource.kind}{qty} at {resource.location} "
                    f"(reported by {resource.reported_by})"
                )

        dangers = await self.get_danger_reports(5)
        if dangers:
            lines.append("**Danger/stuck reports:**")
            for danger in dangers[-5:]:
                lines.append(
                    f"  - {danger.agent_id}: {danger.kind} severity {danger.severity} "
                    f"at {danger.location}"
                    + (f" (reported by {danger.reported_by})" if danger.reported_by else "")
                )

        next_steps = await self.get_next_steps(8)
        if next_steps:
            lines.append("**Open next steps:**")
            for step in next_steps[-8:]:
                lines.append(f"  - {step.text} (added by {step.added_by})")

        actions = await self.get_recent_verified_actions(5)
        if actions:
            lines.append("**Recent verified actions:**")
            for action in actions[-5:]:
                lines.append(f"  - {action.agent_id}: {action.action} -> {action.result}")

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

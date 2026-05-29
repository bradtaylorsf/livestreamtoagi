"""Shared working state -- a task board all agents can read and write."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.redis_keys import ScopedRedis


TASK_KEY = "shared:tasks"
# Per-task atomic claim marker namespace. A SET NX on
# f"{TASK_CLAIM_KEY}:{task_id}" is the first-claim-wins primitive: exactly one
# concurrent claimant sets the key, the rest observe it already exists.
TASK_CLAIM_KEY = "shared:task_claim"
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
SETTLEMENT_OBJECTIVES_KEY = "shared:settlement_objectives"

# Completed tasks older than this are pruned to prevent context bloat
_COMPLETED_TASK_TTL = 3600  # 1 hour
_MAX_COMPLETED_TASKS = 10
_MAX_RECENT_DANGERS = 25
_MAX_RECENT_VERIFIED_ACTIONS = 25
_MAX_NEXT_STEPS = 25
_MAX_SETTLEMENT_OBJECTIVES = 12

# Completion-ratio bar at/above which a settlement objective advance latches to
# "completed" (see advance_settlement_objective). This is the single source of
# truth for the completion bar; the JS success check in
# scripts/minecraft/fork-src/agent/commands/plan_and_build_action.js
# (settlementCompleteRatio()) reads the same MC_SIM_SETTLEMENT_COMPLETE_RATIO env
# var with the same default, so the two bars cannot drift.
_DEFAULT_SETTLEMENT_COMPLETE_RATIO = 0.8

DANGER_KINDS = frozenset(
    {
        "stuck",
        "drowning",
        "trapped",
        "low_health",
        "death",
        "repeated_failure",
    }
)
OPEN_DANGER_STATUSES = frozenset({"open", "rescue_dispatched", "unresolved"})
RESOLVED_DANGER_STATUSES = frozenset({"resolved", "escaped", "teleported", "failed"})


def _danger_id() -> str:
    return f"danger-{uuid.uuid4().hex[:12]}"


def _loads(raw: str | bytes) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


@dataclass
class SharedTask:
    id: str
    title: str
    owner: str | None = None  # None = open/unclaimed proposal any agent can claim
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
    danger_id: str = field(default_factory=_danger_id)
    resolved_at: float | None = None
    rescuer_id: str | None = None
    recovery_status: str = "open"
    details: str | None = None


@dataclass
class SettlementObjective:
    objective_id: str
    phase_index: int
    description: str
    owner_agent_id: str | None = None
    status: str = "pending"
    plan_id: str | None = None
    intended_blocks: int = 0
    verified_blocks: int = 0
    completion_ratio: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    reassign_reason: str | None = None
    previous_owner_agent_ids: list[str] = field(default_factory=list)
    owner_started_at_ms: int | None = None
    stale_after_ms: int | None = None
    cooldown_until_ms: int | None = None
    evidence: dict[str, object] = field(default_factory=dict)


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

    async def claim_task(self, task_id: str, agent_id: str) -> dict[str, object]:
        """Atomically claim an open task — first-claim-wins.

        Returns one of:
          - ``{"status": "ok", "owner": agent_id}`` — caller now owns the task
            (newly claimed, or an idempotent re-claim by the current owner).
          - ``{"status": "already_claimed", "owner": <other>}`` — another agent
            holds it (or it is already done/completed); a no-op for the loser.
          - ``{"status": "not_found"}`` — no such task.

        Atomicity comes from a per-task SET NX marker
        (``f"{TASK_CLAIM_KEY}:{task_id}"``): when two claims race, exactly one
        sets the marker and writes ownership; the other re-reads the winner.
        Status edits by the owner stay blind writes via ``update_task_status`` —
        only first-ownership is contended.
        """
        raw = await self._redis.hget(TASK_KEY, task_id)
        if not raw:
            return {"status": "not_found"}

        data = _loads(raw)
        current_owner = data.get("owner")
        current_status = data.get("status")

        # A finished task can never be re-owned.
        if current_status in ("done", "completed"):
            return {"status": "already_claimed", "owner": current_owner}
        # Re-claim by the current owner is idempotent.
        if current_owner == agent_id:
            return {"status": "ok", "owner": agent_id}
        # Held by a different agent who is actively working it.
        if current_owner and current_status in ("in_progress", "blocked"):
            return {"status": "already_claimed", "owner": current_owner}

        # Open (or merely pending) task — race for the atomic marker.
        won = await self._redis.set(f"{TASK_CLAIM_KEY}:{task_id}", agent_id, nx=True)
        if won:
            await self.update_task_status(task_id, "in_progress", owner=agent_id)
            return {"status": "ok", "owner": agent_id}

        # Lost the race: the marker value IS the winner's id, written atomically
        # by their SET NX. Read it directly rather than the task hash, whose
        # owner field the winner may not have written yet (the owner write
        # happens after SET NX, so a task re-read can briefly still show None).
        winner = await self._redis.get(f"{TASK_CLAIM_KEY}:{task_id}")
        if winner is None:
            # Defensive fallback: marker vanished (e.g. cleared on release) —
            # fall back to the persisted owner.
            raw_after = await self._redis.hget(TASK_KEY, task_id)
            winner = _loads(raw_after).get("owner") if raw_after else None
        return {"status": "already_claimed", "owner": winner}

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
        report.kind = _normalize_danger_kind(report.kind)
        report.severity = max(1, min(5, int(report.severity)))
        if not report.recovery_status:
            report.recovery_status = "open"
        await self._redis.rpush(DANGERS_KEY, json.dumps(asdict(report)))
        await self._redis.ltrim(DANGERS_KEY, -_MAX_RECENT_DANGERS, -1)

    async def get_danger_reports(self, count: int = _MAX_RECENT_DANGERS) -> list[DangerReport]:
        raw = await self._redis.lrange(DANGERS_KEY, -count, -1)
        return [DangerReport(**_loads(r)) for r in raw]

    async def get_unresolved_dangers(
        self,
        count: int = _MAX_RECENT_DANGERS,
    ) -> list[DangerReport]:
        dangers = await self.get_danger_reports(count)
        return [danger for danger in dangers if _is_unresolved_danger(danger)]

    async def dispatch_rescue_task(
        self,
        danger_id: str,
        *,
        rescuer_id: str,
        strategy: str = "navigate",
        mode: str = "standard",
    ) -> SharedTask | None:
        """Create a structured rescue task for an unresolved danger report."""

        updated = await self._update_danger(
            danger_id=danger_id,
            rescuer_id=rescuer_id,
            recovery_status="rescue_dispatched",
        )
        if updated is None:
            return None
        task = SharedTask(
            id=f"rescue-{updated.danger_id}",
            title=(
                f"Rescue {updated.agent_id}: {updated.kind} severity {updated.severity} "
                f"at {updated.location}; strategy={strategy}; mode={mode}"
            ),
            owner=rescuer_id,
            status="pending",
        )
        await self.add_task(task)
        return task

    async def mark_danger_resolved(
        self,
        *,
        danger_id: str | None = None,
        agent_id: str | None = None,
        rescuer_id: str | None = None,
        recovery_status: str = "resolved",
    ) -> DangerReport | None:
        """Mark one danger recovered by id, or latest unresolved danger for an agent."""

        return await self._update_danger(
            danger_id=danger_id,
            agent_id=agent_id,
            rescuer_id=rescuer_id,
            resolved_at=time.time(),
            recovery_status=recovery_status,
        )

    async def _update_danger(
        self,
        *,
        danger_id: str | None = None,
        agent_id: str | None = None,
        rescuer_id: str | None = None,
        resolved_at: float | None = None,
        recovery_status: str | None = None,
    ) -> DangerReport | None:
        raw = await self._redis.lrange(DANGERS_KEY, 0, -1)
        dangers = [DangerReport(**_loads(r)) for r in raw]
        matched_index: int | None = None
        for index in range(len(dangers) - 1, -1, -1):
            danger = dangers[index]
            if danger_id and danger.danger_id != danger_id:
                continue
            if not danger_id and agent_id and danger.agent_id != agent_id:
                continue
            if not danger_id and agent_id and not _is_unresolved_danger(danger):
                continue
            matched_index = index
            break
        if matched_index is None:
            return None

        danger = dangers[matched_index]
        if rescuer_id:
            danger.rescuer_id = rescuer_id
        if resolved_at is not None:
            danger.resolved_at = resolved_at
        if recovery_status:
            danger.recovery_status = recovery_status
        dangers[matched_index] = danger

        await self._redis.delete(DANGERS_KEY)
        if dangers:
            await self._redis.rpush(
                DANGERS_KEY,
                *(json.dumps(asdict(item)) for item in dangers[-_MAX_RECENT_DANGERS:]),
            )
        return danger

    async def set_settlement_objectives(
        self,
        objectives: list[SettlementObjective],
    ) -> None:
        """Replace the run's ordered settlement objective list."""

        ordered = sorted(
            objectives[:_MAX_SETTLEMENT_OBJECTIVES],
            key=lambda item: (int(item.phase_index), item.objective_id),
        )
        for objective in ordered:
            objective.status = _normalize_objective_status(objective.status)
            objective.phase_index = max(0, int(objective.phase_index))
            objective.intended_blocks = max(0, int(objective.intended_blocks))
            objective.verified_blocks = max(0, int(objective.verified_blocks))
            objective.completion_ratio = max(0.0, min(float(objective.completion_ratio), 1.0))
        await self._redis.set(
            SETTLEMENT_OBJECTIVES_KEY,
            json.dumps([asdict(objective) for objective in ordered]),
        )

    async def get_settlement_objectives(self) -> list[SettlementObjective]:
        raw = await self._redis.get(SETTLEMENT_OBJECTIVES_KEY)
        if not raw:
            return []
        data = _loads(raw)
        if not isinstance(data, list):
            return []
        objectives = [
            SettlementObjective(**item)
            for item in data
            if isinstance(item, dict) and item.get("objective_id")
        ]
        return sorted(objectives, key=lambda item: (item.phase_index, item.objective_id))

    async def get_active_settlement_objective(self) -> SettlementObjective | None:
        for objective in await self.get_settlement_objectives():
            if objective.status not in {"blocked", "completed", "failed"}:
                return objective
        return None

    async def assign_settlement_objective_owner(
        self,
        objective_id: str,
        owner_agent_id: str,
        *,
        reason: str | None = None,
        owner_started_at_ms: int | None = None,
    ) -> SettlementObjective | None:
        objectives = await self.get_settlement_objectives()
        for objective in objectives:
            if objective.objective_id != objective_id:
                continue
            if objective.status == "completed":
                return objective
            owner = owner_agent_id.strip().lower()
            if objective.owner_agent_id and objective.owner_agent_id != owner:
                objective.previous_owner_agent_ids = [
                    *objective.previous_owner_agent_ids,
                    objective.owner_agent_id,
                ]
            objective.owner_agent_id = owner
            objective.status = "in_progress"
            objective.reassign_reason = reason
            objective.started_at = objective.started_at or time.time()
            objective.owner_started_at_ms = owner_started_at_ms
            await self.set_settlement_objectives(objectives)
            return objective
        return None

    async def advance_settlement_objective(
        self,
        objective_id: str,
        *,
        status: str,
        plan_id: str | None = None,
        intended_blocks: int | None = None,
        verified_blocks: int | None = None,
        completion_ratio: float | None = None,
        evidence: dict[str, object] | None = None,
    ) -> SettlementObjective | None:
        objectives = await self.get_settlement_objectives()
        for objective in objectives:
            if objective.objective_id != objective_id:
                continue
            next_status = _normalize_objective_status(status)
            if objective.status == "completed" and next_status != "completed":
                return objective
            objective.status = next_status
            if plan_id:
                objective.plan_id = plan_id
            if intended_blocks is not None:
                objective.intended_blocks = max(0, int(intended_blocks))
            if verified_blocks is not None:
                objective.verified_blocks = max(0, int(verified_blocks))
            if completion_ratio is not None:
                objective.completion_ratio = max(0.0, min(float(completion_ratio), 1.0))
            # #904 positive latch: once an advance carries a completion ratio at
            # or above the bar, latch the objective to "completed" regardless of
            # the requested status. A late or build-exception "blocked" advance
            # that still cleared the bar must not leave the objective stuck
            # in_progress. The demotion guard above already prevents a later
            # lower-ratio advance from reverting an already-completed objective.
            if objective.completion_ratio >= _settlement_complete_ratio():
                objective.status = "completed"
            if evidence:
                objective.evidence.update(evidence)
            if objective.status == "completed":
                objective.completed_at = time.time()
            await self.set_settlement_objectives(objectives)
            return objective
        return None

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

        # E21-7g: render the shared task board so agents can observe open work to
        # claim and in-progress work to support (the emergent observe->claim loop).
        tasks = await self.get_tasks()
        active_tasks = [t for t in tasks if t.status != "done"]
        if active_tasks:
            open_tasks = [t for t in active_tasks if not t.owner or t.status == "pending"]
            taken_tasks = [t for t in active_tasks if t.owner and t.status != "pending"]
            lines.append("**Shared task board** (use !manageTask to propose/claim/complete):")
            for task in open_tasks[:10]:
                lines.append(f"  - [OPEN] {task.id}: {task.title} (unclaimed — claim it!)")
            for task in taken_tasks[:10]:
                lines.append(f"  - [{task.status}] {task.id}: {task.title} (owner: {task.owner})")

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
                status = danger.recovery_status or "open"
                lines.append(
                    f"  - {danger.agent_id}: {danger.kind} severity {danger.severity} "
                    f"at {danger.location}; status: {status}"
                    + (f"; rescuer: {danger.rescuer_id}" if danger.rescuer_id else "")
                    + (f" (reported by {danger.reported_by})" if danger.reported_by else "")
                )

        unresolved = await self.get_unresolved_dangers(5)
        if unresolved:
            lines.append("**Unresolved distress:**")
            for danger in unresolved[-5:]:
                lines.append(
                    f"  - {danger.agent_id} needs rescue for {danger.kind} "
                    f"(danger_id: {danger.danger_id}, severity: {danger.severity})"
                )

        next_steps = await self.get_next_steps(8)
        if next_steps:
            lines.append("**Open next steps:**")
            for step in next_steps[-8:]:
                lines.append(f"  - {step.text} (added by {step.added_by})")

        active_objective = await self.get_active_settlement_objective()
        if active_objective:
            owner = active_objective.owner_agent_id or "unassigned"
            lines.append(
                "**Active settlement objective:** "
                f"phase {active_objective.phase_index}: {active_objective.description} "
                f"(owner: {owner}, status: {active_objective.status})"
            )

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
                owner = t.owner or "unassigned"
                line = f"  {icon} {t.title} (owner: {owner}, status: {t.status})"
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


def _normalize_danger_kind(kind: str) -> str:
    text = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in DANGER_KINDS else "trapped"


def _settlement_complete_ratio() -> float:
    """Completion-ratio bar at/above which an advance latches to "completed".

    Read at call time from ``MC_SIM_SETTLEMENT_COMPLETE_RATIO`` so the bar is
    runtime-configurable and stays the single source of truth shared with the JS
    success check (see ``_DEFAULT_SETTLEMENT_COMPLETE_RATIO``). Falls back to the
    default for unset / non-numeric / non-positive values.
    """
    try:
        raw = float(os.environ.get("MC_SIM_SETTLEMENT_COMPLETE_RATIO", ""))
    except (TypeError, ValueError):
        return _DEFAULT_SETTLEMENT_COMPLETE_RATIO
    return raw if raw > 0 else _DEFAULT_SETTLEMENT_COMPLETE_RATIO


def _normalize_objective_status(status: str) -> str:
    text = str(status or "").strip().lower().replace("-", "_").replace(" ", "_")
    valid = {
        "pending",
        "in_progress",
        "blocked",
        "owner_cap_reached",
        "cooldown",
        "stale",
        "completed",
        "failed",
        "abandoned",
    }
    return text if text in valid else "pending"


def _is_unresolved_danger(danger: DangerReport) -> bool:
    if danger.resolved_at is not None:
        return False
    status = (danger.recovery_status or "open").strip().lower()
    if status in RESOLVED_DANGER_STATUSES:
        return False
    return status in OPEN_DANGER_STATUSES or not status

"""Per-agent goal queue management — persistent goals and morning agendas.

Each agent maintains a priority-ordered goal queue. Goals are stored in
PostgreSQL (via GoalRepo) for persistence across restarts, or in Redis
as a fallback when no DB is available.

Goals are created from conversation commitments, reflection cycles,
the eval loop, or agent self-direction. They are injected into every
conversation context as the agent's current agenda.
"""

from __future__ import annotations

import json
import logging
import time
import uuid as uuid_mod
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from core.repos.goal_repo import GoalRepo

logger = logging.getLogger(__name__)

_GOALS_KEY_PREFIX = "agent:goals:"
_MAX_GOALS_PER_AGENT = 10


@dataclass
class AgentGoalLegacy:
    """A single goal in an agent's goal queue (Redis legacy format)."""

    id: str = field(default_factory=lambda: f"goal-{uuid_mod.uuid4().hex[:8]}")
    goal: str = ""
    priority: int = 3  # 1 = highest
    status: str = "pending"  # pending, in_progress, blocked, done
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    related_agent: str | None = None
    blocked_reason: str | None = None


class AgentGoalManager:
    """Per-agent goal queue manager with DB-backed storage.

    Falls back to Redis if no GoalRepo is provided (backward compatibility).
    """

    def __init__(
        self,
        redis: Redis | None = None,
        goal_repo: GoalRepo | None = None,
    ) -> None:
        self._redis = redis
        self._goal_repo = goal_repo

    @property
    def _use_db(self) -> bool:
        return self._goal_repo is not None

    def _key(self, agent_id: str) -> str:
        return f"{_GOALS_KEY_PREFIX}{agent_id}"

    async def get_goals(self, agent_id: str) -> list[AgentGoalLegacy]:
        """Get all active goals for an agent, sorted by priority."""
        if self._use_db:
            return await self._get_goals_db(agent_id)
        return await self._get_goals_redis(agent_id)

    async def _get_goals_db(self, agent_id: str) -> list[AgentGoalLegacy]:
        """Get goals from DB, converting to legacy format for compatibility."""
        assert self._goal_repo is not None
        db_goals = await self._goal_repo.get_active_goals(agent_id)
        return [
            AgentGoalLegacy(
                id=str(g.id),
                goal=g.goal,
                priority=g.priority,
                status=_db_status_to_legacy(g.status),
                created=g.created_at.timestamp() if g.created_at else time.time(),
                updated=g.created_at.timestamp() if g.created_at else time.time(),
                related_agent=None,
                blocked_reason=g.progress_notes if g.status == "blocked" else None,
            )
            for g in db_goals
        ]

    async def _get_goals_redis(self, agent_id: str) -> list[AgentGoalLegacy]:
        """Get goals from Redis (legacy path)."""
        if self._redis is None:
            return []
        raw = await self._redis.get(self._key(agent_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            goals = [AgentGoalLegacy(**g) for g in data]
            goals.sort(key=lambda g: g.priority)
            return goals
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse goals for %s", agent_id)
            return []

    async def _save_goals_redis(self, agent_id: str, goals: list[AgentGoalLegacy]) -> None:
        """Persist the full goal list for an agent in Redis."""
        if self._redis is None:
            return
        data = [asdict(g) for g in goals]
        await self._redis.set(self._key(agent_id), json.dumps(data))

    async def add_goal(
        self,
        agent_id: str,
        goal_text: str,
        priority: int = 3,
        related_agent: str | None = None,
        source: str = "self",
    ) -> AgentGoalLegacy:
        """Add a new goal to an agent's queue."""
        if self._use_db:
            return await self._add_goal_db(agent_id, goal_text, priority, source)
        return await self._add_goal_redis(agent_id, goal_text, priority, related_agent)

    async def _add_goal_db(
        self, agent_id: str, goal_text: str, priority: int, source: str,
    ) -> AgentGoalLegacy:
        assert self._goal_repo is not None
        # Deduplicate
        existing = await self._goal_repo.get_active_goals(agent_id)
        for g in existing:
            if g.goal.lower() == goal_text.lower():
                return AgentGoalLegacy(
                    id=str(g.id), goal=g.goal, priority=g.priority,
                    status=_db_status_to_legacy(g.status),
                )
        db_goal = await self._goal_repo.add_goal(
            agent_id, goal_text, priority=priority, source=source,
        )
        return AgentGoalLegacy(
            id=str(db_goal.id), goal=db_goal.goal, priority=db_goal.priority,
            status=_db_status_to_legacy(db_goal.status),
        )

    async def _add_goal_redis(
        self, agent_id: str, goal_text: str, priority: int, related_agent: str | None,
    ) -> AgentGoalLegacy:
        goals = await self._get_goals_redis(agent_id)
        # Deduplicate
        for existing in goals:
            if existing.goal.lower() == goal_text.lower() and existing.status != "done":
                return existing
        new_goal = AgentGoalLegacy(
            goal=goal_text, priority=priority, related_agent=related_agent,
        )
        goals.append(new_goal)
        if len(goals) > _MAX_GOALS_PER_AGENT:
            done = [g for g in goals if g.status == "done"]
            if done:
                goals.remove(done[0])
            else:
                goals.sort(key=lambda g: g.priority)
                goals = goals[:_MAX_GOALS_PER_AGENT]
        await self._save_goals_redis(agent_id, goals)
        return new_goal

    async def update_goal(
        self,
        agent_id: str,
        goal_id: str,
        status: str | None = None,
        blocked_reason: str | None = None,
    ) -> bool:
        """Update a goal's status. Returns True if found and updated."""
        if self._use_db:
            return await self._update_goal_db(goal_id, status, blocked_reason)
        return await self._update_goal_redis(agent_id, goal_id, status, blocked_reason)

    async def _update_goal_db(
        self, goal_id: str, status: str | None, blocked_reason: str | None,
    ) -> bool:
        assert self._goal_repo is not None
        try:
            uid = uuid_mod.UUID(goal_id)
        except ValueError:
            return False
        updated = False
        if status is not None:
            db_status = _legacy_status_to_db(status)
            updated = await self._goal_repo.update_status(uid, db_status)
        if blocked_reason is not None:
            await self._goal_repo.update_progress(uid, blocked_reason)
            updated = True
        return updated

    async def _update_goal_redis(
        self, agent_id: str, goal_id: str, status: str | None, blocked_reason: str | None,
    ) -> bool:
        goals = await self._get_goals_redis(agent_id)
        for g in goals:
            if g.id == goal_id:
                if status is not None:
                    g.status = status
                if blocked_reason is not None:
                    g.blocked_reason = blocked_reason
                g.updated = time.time()
                await self._save_goals_redis(agent_id, goals)
                return True
        return False

    async def complete_goal(self, agent_id: str, goal_id: str) -> bool:
        """Mark a goal as done."""
        return await self.update_goal(agent_id, goal_id, status="done")

    async def get_agenda_context(self, agent_id: str) -> str:
        """Build a formatted agenda string for injection into context."""
        goals = await self.get_goals(agent_id)
        active = [g for g in goals if g.status not in ("done", "completed")]
        if not active:
            return ""

        lines: list[str] = []
        status_labels = {
            "pending": "TODO",
            "in_progress": "IN PROGRESS",
            "blocked": "BLOCKED",
            "active": "ACTIVE",
        }
        for i, g in enumerate(active[:5], 1):
            label = status_labels.get(g.status, g.status.upper())
            line = f"{i}. [{label}] {g.goal}"
            if g.related_agent:
                line += f" (involves {g.related_agent})"
            if g.blocked_reason:
                line += f" — blocked: {g.blocked_reason}"
            lines.append(line)

        return "\n".join(lines)

    async def generate_morning_agenda(self, agent_id: str) -> str:
        """Generate a morning agenda summarizing current goals."""
        goals = await self.get_goals(agent_id)
        active = [g for g in goals if g.status not in ("done", "completed")]
        if not active:
            return "You have no active goals. Look for something to work on today."

        now = time.time()
        stale_threshold = 24 * 3600

        lines = ["Today you want to:"]
        for i, g in enumerate(active[:5], 1):
            line = f"({i}) {g.goal}"
            if g.related_agent:
                line += f" [with {g.related_agent}]"
            if g.status == "blocked":
                line += f" [BLOCKED: {g.blocked_reason or 'unknown reason'}]"
            elif (now - g.created) > stale_threshold:
                line += " [STALE — no progress in 24h]"
            lines.append(line)

        return "\n".join(lines)

    async def seed_story_goals(self) -> None:
        """Seed initial story-arc goals for agents.

        Safe to call multiple times — skips agents that already have goals.
        """
        story_goals: dict[str, list[tuple[str, int, str | None]]] = {
            "vera": [
                ("Establish team operating rhythm and daily standups", 1, None),
                ("Get Rex to finish the first prototype", 2, "rex"),
                ("Draft a sponsorship outreach plan", 3, None),
            ],
            "rex": [
                ("Evaluate tech stack for the first build project", 1, None),
                ("Build a working prototype to show the team", 2, None),
            ],
            "fork": [
                ("Challenge groupthink on monetization strategy", 1, None),
                ("Review Rex's technical proposals critically", 2, "rex"),
            ],
            "aurora": [
                ("Design the visual identity for the stream", 1, None),
                ("Create concept art for the first world area", 2, None),
            ],
            "sentinel": [
                ("Set up daily cost tracking and budget alerts", 1, None),
                ("Establish spending limits per agent", 2, None),
            ],
            "pixel": [
                ("Set up social media accounts for the show", 1, None),
                ("Create a viewer engagement strategy", 2, None),
            ],
            "grok": [
                ("Find a controversial angle to drive engagement", 1, None),
                ("Propose something wild that might go viral", 2, None),
            ],
        }

        for agent_id, goals in story_goals.items():
            existing = await self.get_goals(agent_id)
            if existing:
                continue
            for goal_text, priority, related in goals:
                await self.add_goal(
                    agent_id, goal_text,
                    priority=priority, related_agent=related,
                )


def _db_status_to_legacy(status: str) -> str:
    """Convert DB status to legacy Redis-compatible status."""
    mapping = {"active": "pending", "completed": "done", "abandoned": "done"}
    return mapping.get(status, status)


def _legacy_status_to_db(status: str) -> str:
    """Convert legacy status to DB status."""
    mapping = {"pending": "active", "in_progress": "active", "done": "completed"}
    return mapping.get(status, status)


def parse_commitments(llm_output: str) -> list[dict[str, str]]:
    """Parse commitment extraction JSON from LLM output.

    Expected format: [{"agent_id": "...", "commitment": "...", "related_to_agent": "..."}]
    Returns empty list on parse failure.
    """
    try:
        text = llm_output.strip()
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        data = json.loads(text)
        if isinstance(data, list):
            return [
                {
                    "agent_id": item.get("agent_id", ""),
                    "commitment": item.get("commitment", ""),
                    "related_to_agent": item.get("related_to_agent", ""),
                }
                for item in data
                if item.get("agent_id") and item.get("commitment")
            ]
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return []

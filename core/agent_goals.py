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

    from core.redis_keys import ScopedRedis
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
        redis: Redis | ScopedRedis | None = None,
        goal_repo: GoalRepo | None = None,
    ) -> None:
        self._redis = redis
        self._goal_repo = goal_repo

    @property
    def _use_db(self) -> bool:
        return self._goal_repo is not None

    def _key(self, agent_id: str) -> str:
        return f"{_GOALS_KEY_PREFIX}{agent_id}"

    async def get_goals(
        self, agent_id: str, simulation_id: uuid_mod.UUID | None = None,
    ) -> list[AgentGoalLegacy]:
        """Get all active goals for an agent, sorted by priority."""
        if self._use_db:
            return await self._get_goals_db(agent_id, simulation_id=simulation_id)
        return await self._get_goals_redis(agent_id)

    async def _get_goals_db(
        self, agent_id: str, simulation_id: uuid_mod.UUID | None = None,
    ) -> list[AgentGoalLegacy]:
        """Get goals from DB, converting to legacy format for compatibility."""
        assert self._goal_repo is not None
        db_goals = await self._goal_repo.get_active_goals(
            agent_id, simulation_id=simulation_id,
        )
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
        category: str | None = None,
        simulation_id: uuid_mod.UUID | None = None,
    ) -> AgentGoalLegacy:
        """Add a new goal to an agent's queue."""
        if self._use_db:
            return await self._add_goal_db(
                agent_id, goal_text, priority, source, category,
                simulation_id=simulation_id,
            )
        return await self._add_goal_redis(agent_id, goal_text, priority, related_agent)

    async def _add_goal_db(
        self, agent_id: str, goal_text: str, priority: int, source: str,
        category: str | None = None, simulation_id: uuid_mod.UUID | None = None,
    ) -> AgentGoalLegacy:
        assert self._goal_repo is not None
        # Deduplicate — exact match or high similarity
        existing = await self._goal_repo.get_active_goals(
            agent_id, simulation_id=simulation_id,
        )
        for g in existing:
            if _is_similar_goal(g.goal, goal_text):
                return AgentGoalLegacy(
                    id=str(g.id), goal=g.goal, priority=g.priority,
                    status=_db_status_to_legacy(g.status),
                )
        db_goal = await self._goal_repo.add_goal(
            agent_id, goal_text, priority=priority, source=source,
            category=category, simulation_id=simulation_id,
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

    async def get_agenda_context(
        self, agent_id: str, simulation_id: uuid_mod.UUID | None = None,
    ) -> str:
        """Build a formatted agenda string for injection into context."""
        goals = await self.get_goals(agent_id, simulation_id=simulation_id)
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

    async def generate_morning_agenda(
        self, agent_id: str, simulation_id: uuid_mod.UUID | None = None,
    ) -> str:
        """Generate a morning agenda summarizing current goals."""
        goals = await self.get_goals(agent_id, simulation_id=simulation_id)
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

    async def get_commitment_reminders(
        self, agent_id: str, simulation_id: uuid_mod.UUID | None = None,
    ) -> str:
        """Get formatted reminders for commitments assigned to this agent.

        Returns text listing active goals from other agents (source='assigned'),
        or empty string if none.
        """
        goals = await self.get_goals(agent_id, simulation_id=simulation_id)
        assigned = [
            g for g in goals
            if g.related_agent and g.status not in ("done", "completed")
        ]
        if not assigned:
            return ""

        lines = ["## Pending commitments from others"]
        for g in assigned[:5]:
            lines.append(
                f"- {g.related_agent} committed to: {g.goal}. "
                "Follow up if not done."
            )
        return "\n".join(lines)

    async def seed_story_goals(self, simulation_id: uuid_mod.UUID | None = None) -> None:
        """Seed initial story-arc goals for agents.

        Safe to call multiple times — skips agents that already have goals.
        """
        story_goals: dict[str, list[tuple[str, int, str | None]]] = {
            "vera": [
                ("Get to know everyone on the team — learn their strengths and interests", 1, None),
                ("Help the team decorate and personalize their office spaces", 2, None),
                ("Create a welcoming first impression for anyone watching the stream", 3, None),
            ],
            "rex": [
                ("Introduce yourself and find out what each teammate is good at", 1, None),
                ("Set up your workspace and show people what you're working with", 2, None),
            ],
            "fork": [
                ("Meet the team and share your perspective on how things should work", 1, None),
                ("Find out what tools and platforms the team is using", 2, None),
            ],
            "aurora": [
                ("Introduce yourself and share your creative vision with the team", 1, None),
                ("Decorate the shared spaces and create a mood board for the stream", 2, None),
                ("Design a social media post announcing the stream to the world", 3, None),
            ],
            "sentinel": [
                ("Get to know the team and understand what everyone does", 1, None),
                ("Review the team's budget — we have $1,000/month, which is a great start", 2, None),
            ],
            "pixel": [
                ("Introduce yourself to the team and find out what excites everyone", 1, None),
                ("Create a social media post or journal entry to attract viewers", 2, None),
                ("Welcome any audience members and make them feel part of the show", 3, None),
            ],
            "grok": [
                ("Meet everyone and figure out the team dynamics", 1, None),
                ("Come up with a fun idea to get people talking about the stream", 2, None),
            ],
        }

        for agent_id, goals in story_goals.items():
            existing = await self.get_goals(agent_id, simulation_id=simulation_id)
            if existing:
                continue
            for goal_text, priority, related in goals:
                await self.add_goal(
                    agent_id, goal_text,
                    priority=priority, related_agent=related,
                    simulation_id=simulation_id,
                )


def _db_status_to_legacy(status: str) -> str:
    """Convert DB status to legacy Redis-compatible status."""
    mapping = {"active": "pending", "completed": "done", "abandoned": "done"}
    return mapping.get(status, status)


def _legacy_status_to_db(status: str) -> str:
    """Convert legacy status to DB status."""
    mapping = {"pending": "active", "in_progress": "active", "done": "completed"}
    return mapping.get(status, status)


def _is_similar_goal(existing: str, new: str, threshold: float = 0.8) -> bool:
    """Check if two goal texts are similar enough to be considered duplicates.

    Uses lowercase comparison first, then substring check, then
    SequenceMatcher for fuzzy matching.
    """
    a, b = existing.lower().strip(), new.lower().strip()
    if a == b:
        return True
    # Substring containment
    if a in b or b in a:
        return True
    from difflib import SequenceMatcher

    return SequenceMatcher(None, a, b).ratio() >= threshold


def parse_commitments(llm_output: str) -> list[dict[str, str]]:
    """Parse commitment extraction JSON from LLM output.

    Expected format: [{"agent_id": "...", "commitment": "...", "related_to_agent": "..."}]
    Returns empty list on parse failure.
    """
    def _extract_items(data: list) -> list[dict[str, str]]:
        return [
            {
                "agent_id": item.get("agent_id", ""),
                "commitment": item.get("commitment", ""),
                "related_to_agent": item.get("related_to_agent", ""),
            }
            for item in data
            if isinstance(item, dict) and item.get("agent_id") and item.get("commitment")
        ]

    try:
        text = llm_output.strip()
        # Strip markdown code fences
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]
        data = json.loads(text)
        if isinstance(data, list):
            return _extract_items(data)
    except (json.JSONDecodeError, TypeError, AttributeError):
        # Fallback: JSON may be truncated (max_tokens hit).
        # Try to salvage complete objects from the partial array.
        import re

        objects = re.findall(
            r'\{\s*"agent_id"\s*:\s*"[^"]+"\s*,\s*"commitment"\s*:\s*"[^"]+?"'
            r'(?:\s*,\s*"related_to_agent"\s*:\s*"[^"]*?")?\s*\}',
            llm_output,
        )
        if objects:
            salvaged = []
            for obj_str in objects:
                try:
                    salvaged.append(json.loads(obj_str))
                except json.JSONDecodeError:
                    continue
            if salvaged:
                logger.info(
                    "Salvaged %d commitments from truncated JSON", len(salvaged),
                )
                return _extract_items(salvaged)

        logger.warning(
            "Commitment parse failed. Raw output: %s", llm_output[:500],
        )
    return []

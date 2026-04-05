"""Per-agent goal queue management — persistent goals and morning agendas.

Each agent maintains a priority-ordered goal queue in Redis.
Goals are created from conversation commitments, updated when conversations
advance them, and injected into every conversation context as the agent's
current agenda.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_GOALS_KEY_PREFIX = "agent:goals:"
_MAX_GOALS_PER_AGENT = 10


@dataclass
class AgentGoal:
    """A single goal in an agent's goal queue."""

    id: str = field(default_factory=lambda: f"goal-{uuid.uuid4().hex[:8]}")
    goal: str = ""
    priority: int = 3  # 1 = highest
    status: str = "pending"  # pending, in_progress, blocked, done
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    related_agent: str | None = None
    blocked_reason: str | None = None


class AgentGoalManager:
    """Redis-backed per-agent goal queue manager."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, agent_id: str) -> str:
        return f"{_GOALS_KEY_PREFIX}{agent_id}"

    async def get_goals(self, agent_id: str) -> list[AgentGoal]:
        """Get all goals for an agent, sorted by priority."""
        raw = await self._redis.get(self._key(agent_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            goals = [AgentGoal(**g) for g in data]
            goals.sort(key=lambda g: g.priority)
            return goals
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse goals for %s", agent_id)
            return []

    async def _save_goals(self, agent_id: str, goals: list[AgentGoal]) -> None:
        """Persist the full goal list for an agent."""
        data = [asdict(g) for g in goals]
        await self._redis.set(self._key(agent_id), json.dumps(data))

    async def add_goal(
        self,
        agent_id: str,
        goal_text: str,
        priority: int = 3,
        related_agent: str | None = None,
    ) -> AgentGoal:
        """Add a new goal to an agent's queue."""
        goals = await self.get_goals(agent_id)

        # Deduplicate: skip if a very similar goal already exists
        for existing in goals:
            if existing.goal.lower() == goal_text.lower() and existing.status != "done":
                return existing

        new_goal = AgentGoal(
            goal=goal_text,
            priority=priority,
            related_agent=related_agent,
        )
        goals.append(new_goal)

        # Cap at max goals (drop lowest-priority completed ones first)
        if len(goals) > _MAX_GOALS_PER_AGENT:
            # Remove done goals first, then lowest priority
            done = [g for g in goals if g.status == "done"]
            if done:
                goals.remove(done[0])
            else:
                goals.sort(key=lambda g: g.priority)
                goals = goals[:_MAX_GOALS_PER_AGENT]

        await self._save_goals(agent_id, goals)
        return new_goal

    async def update_goal(
        self,
        agent_id: str,
        goal_id: str,
        status: str | None = None,
        blocked_reason: str | None = None,
    ) -> bool:
        """Update a goal's status. Returns True if found and updated."""
        goals = await self.get_goals(agent_id)
        for g in goals:
            if g.id == goal_id:
                if status:
                    g.status = status
                if blocked_reason is not None:
                    g.blocked_reason = blocked_reason
                g.updated = time.time()
                await self._save_goals(agent_id, goals)
                return True
        return False

    async def complete_goal(self, agent_id: str, goal_id: str) -> bool:
        """Mark a goal as done."""
        return await self.update_goal(agent_id, goal_id, status="done")

    async def get_agenda_context(self, agent_id: str) -> str:
        """Build a formatted agenda string for injection into context."""
        goals = await self.get_goals(agent_id)
        active = [g for g in goals if g.status != "done"]
        if not active:
            return ""

        lines: list[str] = []
        status_labels = {
            "pending": "TODO",
            "in_progress": "IN PROGRESS",
            "blocked": "BLOCKED",
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
        """Generate a morning agenda summarizing current goals.

        Flags stale goals (not updated in >24h) and formats as a
        natural-language agenda for the agent's context.
        """
        goals = await self.get_goals(agent_id)
        active = [g for g in goals if g.status != "done"]
        if not active:
            return "You have no active goals. Look for something to work on today."

        now = time.time()
        stale_threshold = 24 * 3600  # 24 hours

        lines = ["Today you want to:"]
        for i, g in enumerate(active[:5], 1):
            line = f"({i}) {g.goal}"
            if g.related_agent:
                line += f" [with {g.related_agent}]"
            if g.status == "blocked":
                line += f" [BLOCKED: {g.blocked_reason or 'unknown reason'}]"
            elif (now - g.updated) > stale_threshold:
                line += " [STALE — no progress in 24h]"
            lines.append(line)

        return " ".join(lines)

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


def parse_commitments(llm_output: str) -> list[dict[str, str]]:
    """Parse commitment extraction JSON from LLM output.

    Expected format: [{"agent_id": "...", "commitment": "...", "related_to_agent": "..."}]
    Returns empty list on parse failure.
    """
    try:
        # Try to extract JSON array from the output
        text = llm_output.strip()
        # Handle markdown code blocks
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

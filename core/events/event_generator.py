"""Random event generation for novelty injection.

Generates events based on configured probabilities and the current
world state. Events are injected into the trigger system as
high-priority conversation triggers.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.events.event_templates import (
    DEFAULT_CATEGORY_WEIGHTS,
    DEFAULT_PROBABILITIES,
    EVENT_TEMPLATES,
)

if TYPE_CHECKING:
    import uuid as _uuid

    from core.agent_state import AgentStateManager
    from core.conversation.triggers import TriggerSystem
    from core.event_bus import EventBus
    from core.repos.world_repo import WorldRepo

logger = logging.getLogger(__name__)


class WorldEvent(BaseModel):
    """A generated world event."""

    event_id: str = ""
    category: str
    title: str
    description: str
    severity: str = "minor"
    affected_agents: list[str] | None = None
    requires_response: bool = False
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class EventGeneratorConfig(BaseModel):
    """Configuration for the event generator."""

    probability_per_hour: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_PROBABILITIES)
    )
    max_events_per_day: int = 4
    min_hours_between_events: float = 2.0
    category_weights: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_CATEGORY_WEIGHTS)
    )


class EventGenerator:
    """Generates random events based on probability, cooldowns, and state."""

    def __init__(
        self,
        *,
        config: EventGeneratorConfig | None = None,
        world_repo: WorldRepo | None = None,
        trigger_system: TriggerSystem | None = None,
        event_bus: EventBus | None = None,
        agent_state_manager: AgentStateManager | None = None,
        rng: random.Random | None = None,
        simulation_id: _uuid.UUID | None = None,
    ) -> None:
        self._config = config or EventGeneratorConfig()
        self._world_repo = world_repo
        self._triggers = trigger_system
        self._event_bus = event_bus
        self._state_mgr = agent_state_manager
        self._rng = rng or random.Random()
        self.simulation_id = simulation_id

        # Tracking state
        self._events_today: int = 0
        self._last_event_time: datetime | None = None
        self._current_day: str = ""

    def _reset_daily_counter(self) -> None:
        """Reset the daily event counter if the day has changed."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_day:
            self._events_today = 0
            self._current_day = today

    def _check_cooldown(self) -> bool:
        """Check if enough time has passed since the last event."""
        if self._last_event_time is None:
            return True
        elapsed = datetime.now() - self._last_event_time
        min_gap = timedelta(hours=self._config.min_hours_between_events)
        return elapsed >= min_gap

    async def generate_event(self) -> WorldEvent | None:
        """Attempt to generate a random event.

        Returns None if probability check fails, cooldown not met, or daily cap reached.
        """
        self._reset_daily_counter()

        # Check daily cap
        if self._events_today >= self._config.max_events_per_day:
            return None

        # Check cooldown
        if not self._check_cooldown():
            return None

        # Roll for severity (check from most rare to most common)
        severity = self._roll_severity()
        if severity is None:
            return None

        # Select category
        category = self._select_category()

        # Pick a template
        templates = [t for t in EVENT_TEMPLATES.get(category, []) if t["severity"] == severity]
        if not templates:
            # Fall back to any template in the category
            templates = EVENT_TEMPLATES.get(category, [])
        if not templates:
            return None

        template = self._rng.choice(templates)

        # Build the event
        import uuid

        now = datetime.now()
        expires_at = None
        if template.get("duration_hours"):
            expires_at = now + timedelta(hours=template["duration_hours"])

        event = WorldEvent(
            event_id=str(uuid.uuid4()),
            category=category,
            title=template["title"],
            description=template["description"],
            severity=template["severity"],
            affected_agents=template.get("affected_agents"),
            requires_response=template.get("requires_response", False),
            expires_at=expires_at,
            created_at=now,
        )

        # Update tracking
        self._events_today += 1
        self._last_event_time = now

        # Persist to world_events table
        if self._world_repo is not None:
            from core.models import WorldEventCreate

            await self._world_repo.create_event(
                WorldEventCreate(
                    event_type=f"random_{category}",
                    description=f"[{event.severity.upper()}] {event.title}: {event.description}",
                    agents_involved=event.affected_agents or [],
                    audience_participation=False,
                    simulation_id=self.simulation_id,
                )
            )

        # Inject into trigger system
        if self._triggers is not None:
            event_type = "challenge_event" if category == "challenge" else "random_event"
            self._triggers.queue_event(
                event_type,
                {
                    "event_id": event.event_id,
                    "title": event.title,
                    "description": event.description,
                    "severity": event.severity,
                    "category": category,
                    "affected_agents": event.affected_agents,
                    "requires_response": event.requires_response,
                },
            )

        # Emit for stream overlay
        if self._event_bus is not None:
            from core.event_bus import EventType

            await self._event_bus.emit(
                EventType.WORLD_EXPANSION,
                {
                    "event_type": "random_event",
                    "title": event.title,
                    "description": event.description,
                    "severity": event.severity,
                    "category": category,
                },
            )

        # Update agent states for affected agents
        if self._state_mgr is not None:
            await self._apply_state_effects(event)

        logger.info(
            "Generated %s event: [%s] %s",
            event.severity,
            event.category,
            event.title,
        )
        return event

    async def check_and_generate(self) -> list[WorldEvent]:
        """Called periodically — attempts to generate events respecting limits.

        Returns list of events generated (usually 0 or 1).
        """
        event = await self.generate_event()
        return [event] if event else []

    async def generate_morning_briefing(self) -> list[dict[str, str]]:
        """Generate trending topics for the morning standup.

        Returns a list of briefing items with title and summary.
        In production this would use web search; here we use templates.
        """
        # Template-based briefing items (web search would replace this)
        topics = [
            {
                "title": "AI Regulation Update",
                "summary": "New AI safety regulations proposed in the EU. Could affect how AI shows operate.",
            },
            {
                "title": "Open Source LLM Release",
                "summary": "A major open-source LLM was released, claiming to match proprietary model performance.",
            },
            {
                "title": "Streaming Platform Changes",
                "summary": "Twitch announced new monetization features for AI-generated content streams.",
            },
            {
                "title": "AI Art Controversy",
                "summary": "Debate continues over AI-generated art in creative competitions.",
            },
            {
                "title": "Token Cost Trends",
                "summary": "API token costs continue to drop as competition between providers heats up.",
            },
        ]

        # Select 3-5 random topics
        count = self._rng.randint(3, min(5, len(topics)))
        selected = self._rng.sample(topics, count)
        return selected

    def _roll_severity(self) -> str | None:
        """Roll probability dice for each severity level.

        Returns the most severe level that passes, or None.
        """
        probs = self._config.probability_per_hour
        # Check from rarest to most common
        for severity in ("crisis", "major", "moderate", "minor"):
            prob = probs.get(severity, 0.0)
            if self._rng.random() < prob:
                return severity
        return None

    def _select_category(self) -> str:
        """Weighted random category selection."""
        weights = self._config.category_weights
        categories = list(weights.keys())
        probs = [weights[c] for c in categories]
        return self._rng.choices(categories, weights=probs, k=1)[0]

    async def _apply_state_effects(self, event: WorldEvent) -> None:
        """Apply event effects to agent internal state."""
        if self._state_mgr is None:
            return

        # Determine which agents are affected
        if event.affected_agents:
            agent_ids = event.affected_agents
        else:
            # All agents — get IDs from state manager's cache
            agent_ids = (
                list(self._state_mgr._cache.keys()) if hasattr(self._state_mgr, "_cache") else []
            )
            if not agent_ids:
                return

        for agent_id in agent_ids:
            try:
                await self._state_mgr.on_novel_event(agent_id, severity=event.severity)
            except Exception:
                logger.warning("Failed to update state for %s", agent_id)

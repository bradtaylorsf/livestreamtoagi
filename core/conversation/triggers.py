"""Conversation trigger system — determines when new conversations start.

Five trigger types:
- idle: nobody talking for idle_timeout_seconds
- scheduled: daily schedule events (standup, lunch, challenge hour, etc.)
- environmental: external events (poll result, world expansion, budget update, viewer milestone)
- memory: random agent recalls a high-importance memory (2% chance per tick)
- audience: chat highlight or donation events (Pixel gets first crack)

Priority order: pending events (environmental + audience) > scheduled > idle > memory
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.memory.recall_memory import RecallMemoryManager
    from core.models import TriggerConfig

logger = logging.getLogger(__name__)

# Daily schedule: hour -> (event_name, starter_agent_id)
DAILY_SCHEDULE: dict[int, tuple[str, str]] = {
    9: ("standup", "vera"),
    12: ("lunch_break", "vera"),
    17: ("challenge_hour", "vera"),
    18: ("daily_brief", "vera"),
    20: ("reflection", "vera"),
}

# Environmental event types that the trigger system recognises
ENVIRONMENTAL_EVENTS = frozenset({
    "poll_result",
    "world_expansion",
    "budget_update",
    "viewer_milestone",
})

# Audience event types
AUDIENCE_EVENTS = frozenset({
    "donation",
    "chat_highlight",
})

MEMORY_TRIGGER_CHANCE = 0.02  # 2% per tick


class TriggerSystem:
    """Checks each tick whether a new conversation should start."""

    def __init__(
        self,
        config: TriggerConfig,
        recall_memory: RecallMemoryManager | None = None,
        *,
        clock: Any = None,
        now_fn: Any = None,
        rng: random.Random | None = None,
    ) -> None:
        self._config = config
        self._recall_memory = recall_memory
        self._last_speech_time: float = (clock or time).monotonic()
        self._pending_events: deque[dict[str, Any]] = deque()
        self._fired_today: set[int] = set()
        self._last_fired_date: str = ""
        # Allow injecting clock/datetime/rng for deterministic testing
        self._clock = clock or time
        self._now_fn = now_fn or datetime.now
        self._rng = rng or random.Random()

    # ── Public API ────────────────────────────────────────

    def notify_speech(self) -> None:
        """Call when any agent speaks to reset the idle timer."""
        self._last_speech_time = self._clock.monotonic()

    def queue_event(self, event_type: str, event_data: dict[str, Any] | None = None) -> None:
        """Push an environmental or audience event for processing on the next tick."""
        category = "audience" if event_type in AUDIENCE_EVENTS else "environmental"
        self._pending_events.append({
            "event_type": event_type,
            "category": category,
            "data": event_data or {},
        })

    def reset(self) -> None:
        """Clear all state — useful between test runs or after config reload."""
        self._pending_events.clear()
        self._fired_today.clear()
        self._last_fired_date = ""
        self._last_speech_time = self._clock.monotonic()

    async def check(self) -> dict[str, Any] | None:
        """Check triggers in priority order. Returns trigger dict or None.

        Priority: pending events > scheduled > idle > memory
        """
        # 1. Pending events (environmental + audience)
        if self._pending_events:
            event = self._pending_events.popleft()
            return self._build_event_trigger(event)

        # 2. Scheduled
        trigger = self._check_scheduled()
        if trigger is not None:
            return trigger

        # 3. Idle
        trigger = self._check_idle()
        if trigger is not None:
            return trigger

        # 4. Memory (2% chance)
        trigger = await self._check_memory()
        if trigger is not None:
            return trigger

        return None

    # ── Private helpers ───────────────────────────────────

    def _build_event_trigger(self, event: dict[str, Any]) -> dict[str, Any]:
        """Build a trigger dict from a queued event."""
        event_type = event["event_type"]
        category = event["category"]

        if category == "audience":
            # Pixel gets first crack at audience events
            starter = "pixel"
        else:
            # Environmental: pick starter by initiative weights
            starter = self._select_by_initiative()

        return {
            "type": category,
            "starter_agent_id": starter,
            "prompt_hint": f"Respond to {event_type}: {event['data']}",
            "event_type": event_type,
            "event_data": event["data"],
        }

    def _check_scheduled(self) -> dict[str, Any] | None:
        """Check if current hour matches a daily schedule event."""
        now = self._now_fn()
        today = now.strftime("%Y-%m-%d")

        # Reset fired set on new day
        if today != self._last_fired_date:
            self._fired_today.clear()
            self._last_fired_date = today

        hour = now.hour
        if hour in DAILY_SCHEDULE and hour not in self._fired_today:
            self._fired_today.add(hour)
            event_name, starter = DAILY_SCHEDULE[hour]
            return {
                "type": "scheduled",
                "starter_agent_id": starter,
                "prompt_hint": f"It's time for {event_name}.",
                "event_name": event_name,
                "scheduled_hour": hour,
            }

        return None

    def _check_idle(self) -> dict[str, Any] | None:
        """Check if silence has exceeded idle_timeout_seconds."""
        elapsed = self._clock.monotonic() - self._last_speech_time
        if elapsed >= self._config.idle_timeout_seconds:
            starter = self._select_by_initiative()
            return {
                "type": "idle",
                "starter_agent_id": starter,
                "prompt_hint": f"It's been quiet for {int(elapsed)} seconds. Start a conversation.",
                "silence_seconds": elapsed,
            }
        return None

    async def _check_memory(self) -> dict[str, Any] | None:
        """2% chance per tick — random agent recalls a high-importance memory."""
        if self._rng.random() >= MEMORY_TRIGGER_CHANCE:
            return None

        if self._recall_memory is None:
            return None

        agents = list(self._config.agent_initiative.keys())
        if not agents:
            return None

        agent_id = self._rng.choice(agents)

        try:
            memory_text = await self._recall_memory.retrieve_recall_memories(
                agent_id=agent_id,
                query_text="important memorable event",
                limit=1,
            )
        except Exception:
            logger.exception("Memory trigger failed for agent %s", agent_id)
            return None

        if not memory_text:
            return None

        return {
            "type": "memory",
            "starter_agent_id": agent_id,
            "prompt_hint": f"You just remembered something: {memory_text}",
            "memory_summary": memory_text,
        }

    def _select_by_initiative(self) -> str:
        """Weighted random selection from agent_initiative config."""
        agents = list(self._config.agent_initiative.keys())
        weights = list(self._config.agent_initiative.values())
        return self._rng.choices(agents, weights=weights, k=1)[0]

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

# Fallback daily schedule when config has no daily_schedule field
_DEFAULT_DAILY_SCHEDULE: dict[int, tuple[str, str]] = {
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
        # Cross-conversation dedup: maps (trigger_type, event_key) -> monotonic timestamp
        self._recent_conversations: dict[tuple[str, str], float] = {}
        # Allow injecting clock/datetime/rng for deterministic testing
        self._clock = clock or time
        self._now_fn = now_fn or datetime.now
        self._rng = rng or random.Random()

    # ── Public API ────────────────────────────────────────

    def notify_speech(self) -> None:
        """Call when any agent speaks to reset the idle timer."""
        self._last_speech_time = self._clock.monotonic()

    def queue_event(self, event_type: str, event_data: dict[str, Any] | None = None) -> None:
        """Push an environmental or audience event for processing on the next tick.

        Duplicate events (same event_type) are collapsed to prevent
        identical conversations from being triggered multiple times.
        """
        category = "audience" if event_type in AUDIENCE_EVENTS else "environmental"
        # Dedup: reject if an event with the same type is already pending
        for existing in self._pending_events:
            if existing["event_type"] == event_type:
                logger.debug(
                    "Dropping duplicate pending event: %s", event_type,
                )
                return
        self._pending_events.append({
            "event_type": event_type,
            "category": category,
            "data": event_data or {},
        })

    def reset(self) -> None:
        """Reset inter-conversation state while preserving daily trigger tracking.

        Called after each conversation ends. Only clears pending events and
        resets the idle timer. ``_fired_today`` is intentionally preserved so
        that scheduled triggers don't re-fire within the same hour.
        """
        self._pending_events.clear()
        self._last_speech_time = self._clock.monotonic()

    def reset_full(self) -> None:
        """Clear *all* state — useful between test runs or after config reload."""
        self._pending_events.clear()
        self._fired_today.clear()
        self._last_fired_date = ""
        self._recent_conversations.clear()
        self._last_speech_time = self._clock.monotonic()

    def record_conversation(
        self,
        trigger_type: str,
        event_key: str,
    ) -> None:
        """Record that a conversation was started from a trigger.

        Used to prevent the same trigger from producing duplicate
        conversations within a short window (30 minutes by default).
        """
        self._recent_conversations[(trigger_type, event_key)] = self._clock.monotonic()

    async def check(self) -> dict[str, Any] | None:
        """Check triggers in priority order. Returns trigger dict or None.

        Priority: pending events > scheduled > idle > memory
        """
        # Expire old entries from recent conversations (>30 min)
        self._expire_recent_conversations()

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

    # ── Cross-conversation dedup ──────────────────────────

    # Window in seconds for cross-conversation dedup
    _DEDUP_WINDOW_SECONDS: float = 1800.0  # 30 minutes

    def _expire_recent_conversations(self) -> None:
        """Remove entries older than the dedup window."""
        now = self._clock.monotonic()
        expired = [
            key for key, ts in self._recent_conversations.items()
            if now - ts > self._DEDUP_WINDOW_SECONDS
        ]
        for key in expired:
            del self._recent_conversations[key]

    def _is_recent_duplicate(self, trigger_type: str, event_key: str) -> bool:
        """Check if a trigger with this type+key ran recently."""
        return (trigger_type, event_key) in self._recent_conversations

    # ── Private helpers ───────────────────────────────────

    def _build_event_trigger(self, event: dict[str, Any]) -> dict[str, Any]:
        """Build a trigger dict from a queued event."""
        event_type = event["event_type"]
        category = event["category"]

        # Pixel gets first crack at audience events
        starter = "pixel" if category == "audience" else self._select_by_initiative()

        # Sanitize event data for prompt — stringify and truncate to prevent
        # prompt injection from external sources (chat messages, donations)
        sanitized_data = str(event["data"])[:500]

        return {
            "type": category,
            "starter_agent_id": starter,
            "prompt_hint": f"Respond to {event_type}: {sanitized_data}",
            "event_type": event_type,
            "event_data": event["data"],
        }

    @property
    def _daily_schedule(self) -> dict[int, tuple[str, str]]:
        """Resolve daily schedule from config, falling back to defaults."""
        if self._config.daily_schedule:
            return {
                hour: (entry.event_name, entry.starter_agent_id)
                for hour, entry in self._config.daily_schedule.items()
            }
        return _DEFAULT_DAILY_SCHEDULE

    def _check_scheduled(self) -> dict[str, Any] | None:
        """Check if current hour matches a daily schedule event."""
        now = self._now_fn()
        today = now.strftime("%Y-%m-%d")

        # Reset fired set on new day
        if today != self._last_fired_date:
            self._fired_today.clear()
            self._last_fired_date = today

        schedule = self._daily_schedule
        hour = now.hour
        if hour in schedule and hour not in self._fired_today:
            event_name, starter = schedule[hour]
            # Cross-conversation dedup: skip if this event ran recently
            if self._is_recent_duplicate("scheduled", event_name):
                logger.debug(
                    "Skipping duplicate scheduled event %s (fired recently)",
                    event_name,
                )
                self._fired_today.add(hour)
                return None
            self._fired_today.add(hour)
            self.record_conversation("scheduled", event_name)
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
        """Configurable chance per tick — random agent recalls a high-importance memory."""
        if self._rng.random() >= self._config.memory_trigger_chance:
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
        if not agents:
            logger.warning("agent_initiative is empty, cannot select starter")
            return "vera"  # safe fallback
        weights = list(self._config.agent_initiative.values())
        return self._rng.choices(agents, weights=weights, k=1)[0]

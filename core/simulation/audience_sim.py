"""Audience simulation for evals and early-days scenarios.

Seeds Redis with synthetic audience data (viewer count, chat messages,
poll votes) so that audience-facing tools return meaningful results
during simulation runs instead of empty/zero values.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.redis_client import RedisClient
    from core.redis_keys import ScopedRedis

logger = logging.getLogger(__name__)

# Default viewer personas if none provided in scenario config
_DEFAULT_PERSONAS: list[dict[str, str]] = [
    {"name": "viewer1", "style": "curious newcomer"},
    {"name": "crypto_fan_99", "style": "enthusiastic, asks about crypto"},
    {"name": "dev_lurker", "style": "technical questions, lurks mostly"},
    {"name": "artsy_watcher", "style": "interested in creative aspects"},
    {"name": "first_timer", "style": "confused but engaged"},
]

# Pre-written message pools per persona style
_CHAT_POOLS: dict[str, list[str]] = {
    "curious newcomer": [
        "What are you guys working on?",
        "This is so cool, how does this work?",
        "Who's in charge here?",
        "Is this live right now?",
        "How long have you been streaming?",
    ],
    "enthusiastic, asks about crypto": [
        "Can you build a crypto tracker?",
        "Have you thought about NFTs for the pixel art?",
        "What's the budget situation looking like?",
        "You should accept crypto donations!",
        "This could be huge if you monetize right",
    ],
    "technical questions, lurks mostly": [
        "What language is the backend written in?",
        "How do you handle memory between conversations?",
        "Interesting architecture choice",
        "What model are you running on?",
        "How's the latency on the LLM calls?",
    ],
    "interested in creative aspects": [
        "The pixel art is adorable!",
        "Can you make a garden area?",
        "Aurora should design a logo!",
        "I love the character designs",
        "You should add more animations",
    ],
    "confused but engaged": [
        "Wait, these are all AIs?",
        "How do I vote on stuff?",
        "This is weird but I can't stop watching",
        "Are they actually talking to each other?",
        "LOL what just happened",
    ],
}

# Growth curve functions: maps elapsed minutes to viewer count
_GROWTH_CURVES: dict[str, Any] = {
    "slow": lambda minutes: min(20, int(minutes * 0.5)),
    "medium": lambda minutes: min(100, int(minutes * 2)),
    "fast": lambda minutes: min(500, int(minutes * 8)),
}

# Chat frequency: average seconds between messages
_CHAT_INTERVALS: dict[str, float] = {
    "quiet": 60.0,
    "occasional": 30.0,
    "active": 15.0,
    "chaotic": 5.0,
}


class AudienceSimulator:
    """Seeds Redis with synthetic audience data during simulation runs."""

    def __init__(
        self,
        redis_client: RedisClient | ScopedRedis,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._redis = redis_client
        self._config = config or {}
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._start_time = 0.0

        # Parse config
        self._initial_viewers = self._config.get("initial_viewers", 0)
        self._growth_rate = self._config.get("growth_rate", "slow")
        self._chat_frequency = self._config.get("chat_frequency", "occasional")
        self._personas = self._config.get("viewer_personas", _DEFAULT_PERSONAS)

    def start(self) -> None:
        """Launch the background simulation task."""
        if self._running:
            return
        self._running = True
        self._start_time = time.monotonic()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "AudienceSimulator started (growth=%s, chat=%s, personas=%d)",
            self._growth_rate,
            self._chat_frequency,
            len(self._personas),
        )

    async def stop(self) -> None:
        """Cancel the background task."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("AudienceSimulator stopped")

    async def _run_loop(self) -> None:
        """Main simulation loop — updates viewer count and injects chat."""
        interval = _CHAT_INTERVALS.get(self._chat_frequency, 30.0)
        # Use shorter ticks in simulation (min 5s between updates)
        tick_interval = max(5.0, interval / 2)

        try:
            while self._running:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("AudienceSimulator tick failed")
                await asyncio.sleep(tick_interval)
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> None:
        """Single simulation tick: update viewers, maybe inject chat, vote on polls."""
        elapsed_minutes = (time.monotonic() - self._start_time) / 60.0

        # Update viewer count
        growth_fn = _GROWTH_CURVES.get(self._growth_rate, _GROWTH_CURVES["slow"])
        viewer_count = self._initial_viewers + growth_fn(elapsed_minutes)
        await self._redis.set("audience:viewer_count", str(viewer_count))

        # Maybe inject a chat message
        chat_interval = _CHAT_INTERVALS.get(self._chat_frequency, 30.0)
        # Probabilistic: inject roughly once per chat_interval
        tick_interval = max(5.0, chat_interval / 2)
        if random.random() < (tick_interval / chat_interval):
            await self._inject_chat_message()

        # Vote on active polls
        await self._vote_on_active_poll()

    async def _inject_chat_message(self) -> None:
        """Pick a random persona and inject a chat message."""
        if not self._personas:
            return

        persona = random.choice(self._personas)
        style = persona.get("style", "curious newcomer")
        name = persona.get("name", "viewer")

        pool = _CHAT_POOLS.get(style, _CHAT_POOLS["curious newcomer"])
        message = random.choice(pool)

        chat_entry = json.dumps(
            {
                "user": name,
                "text": message,
                "timestamp": time.time(),
            }
        )

        await self._redis.rpush("audience:recent_chat", chat_entry)
        await self._redis.ltrim("audience:recent_chat", -50, -1)

    async def _vote_on_active_poll(self) -> None:
        """If a poll is active, add 1-3 votes to random options."""
        poll_id = await self._redis.get("poll:active")
        if not poll_id:
            return

        poll_data_raw = await self._redis.get(f"poll:{poll_id}")
        if not poll_data_raw:
            return

        try:
            poll_data = json.loads(poll_data_raw)
        except (json.JSONDecodeError, TypeError):
            return

        options = poll_data.get("options", [])
        if not options:
            return
        # Coerce options to strings (agents sometimes store dicts)
        options = [str(o) if not isinstance(o, str) else o for o in options]

        votes = poll_data.get("votes", {})
        num_votes = random.randint(1, 3)
        for _ in range(num_votes):
            chosen = random.choice(options)
            votes[chosen] = votes.get(chosen, 0) + 1

        poll_data["votes"] = votes
        await self._redis.set(f"poll:{poll_id}", json.dumps(poll_data))

    async def seed_initial_state(self) -> None:
        """Set initial audience state in Redis before phases begin."""
        await self._redis.set("audience:viewer_count", str(self._initial_viewers))
        # Clear stale chat
        await self._redis.delete("audience:recent_chat")

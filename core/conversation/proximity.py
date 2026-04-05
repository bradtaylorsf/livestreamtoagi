"""Proximity group manager for conversation participation.

Tracks agent locations and determines who can participate in conversations.
Agents must be in the same chunk to hear each other. Agents in adjacent
chunks may "walk over" (eavesdrop) based on topic relevance and personality.
"""

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING

from core.event_bus import EventType

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from core.models import AgentConfig, ConversationConfig
    from core.redis_client import RedisClient

logger = logging.getLogger(__name__)

# Redis key pattern for agent locations
_LOCATION_KEY_PREFIX = "agent:location:"
# TTL for location keys (1 hour) — prevents stale data if process crashes
_LOCATION_TTL_SECONDS = 3600

# Weighted selection constants
_TIME_BONUS_CAP = 2.0
_TIME_BONUS_INTERVAL = 300.0  # 5 minutes
_ROLE_BONUS: dict[str, float] = {
    "vera": 0.5,
    "sentinel": 0.3,
}


class ProximityManager:
    """Tracks agent locations and resolves who can hear whom."""

    def __init__(
        self,
        redis_client: RedisClient,
        config: ConversationConfig,
        event_bus: EventBus,
    ) -> None:
        self._redis = redis_client
        self._config = config
        self._event_bus = event_bus
        self._last_spoke: dict[str, float] = {}

    @property
    def config(self) -> ConversationConfig:
        return self._config

    @config.setter
    def config(self, value: ConversationConfig) -> None:
        self._config = value

    async def update_location(
        self,
        agent_id: str,
        chunk_name: str,
    ) -> str | None:
        """Update an agent's location in Redis.

        Returns the previous chunk name if the agent moved, or None if
        this is their first location update.
        """
        key = f"{_LOCATION_KEY_PREFIX}{agent_id}"
        previous = await self._redis.get(key)
        await self._redis.set(key, chunk_name, ex=_LOCATION_TTL_SECONDS)

        if previous is not None and previous != chunk_name:
            logger.debug(
                "agent %s moved from %s to %s",
                agent_id,
                previous,
                chunk_name,
            )

        return previous

    async def get_group(self, chunk_name: str) -> list[str]:
        """Return all agent IDs currently in the given chunk."""
        group: list[str] = []
        cursor: int | str = 0
        while True:
            cursor, keys = await self._redis.client.scan(
                cursor=cursor,
                match=f"{_LOCATION_KEY_PREFIX}*",
                count=50,
            )
            for key in keys:
                location = await self._redis.get(key)
                if location == chunk_name:
                    agent_id = key.removeprefix(_LOCATION_KEY_PREFIX)
                    group.append(agent_id)
            if cursor == 0:
                break
        return group

    def record_spoke(self, agent_id: str) -> None:
        """Record that an agent just spoke, updating last-spoke timestamp."""
        self._last_spoke[agent_id] = time.monotonic()

    def _weighted_select(
        self,
        agents: list[AgentConfig],
        max_size: int,
        required_ids: set[str] | None = None,
    ) -> list[AgentConfig]:
        """Select up to *max_size* agents using weighted random selection.

        Required agents are always included first; remaining slots are
        filled via ``random.choices`` with weights derived from time since
        last spoke and role bonuses.
        """
        if len(agents) <= max_size:
            return list(agents)

        required_ids = required_ids or set()
        now = time.monotonic()

        # Guarantee required agents first
        required = [a for a in agents if a.id in required_ids]
        pool = [a for a in agents if a.id not in required_ids]
        remaining_slots = max_size - len(required)

        if remaining_slots <= 0:
            return required[:max_size]

        if len(pool) <= remaining_slots:
            return required + pool

        # Compute weights
        weights: list[float] = []
        for agent in pool:
            base = 1.0
            last = self._last_spoke.get(agent.id)
            elapsed = now - last if last is not None else _TIME_BONUS_INTERVAL
            time_bonus = min(elapsed / _TIME_BONUS_INTERVAL, _TIME_BONUS_CAP)
            role_bonus = _ROLE_BONUS.get(agent.id, 0.0)
            weights.append(base + time_bonus + role_bonus)

        # Weighted sampling without replacement
        selected_pool: list[AgentConfig] = []
        pool_copy = list(pool)
        weights_copy = list(weights)
        for _ in range(remaining_slots):
            if not pool_copy:
                break
            picks = random.choices(pool_copy, weights=weights_copy, k=1)
            pick = picks[0]
            idx = pool_copy.index(pick)
            selected_pool.append(pick)
            pool_copy.pop(idx)
            weights_copy.pop(idx)

        return required + selected_pool

    async def get_eligible_speakers(
        self,
        chunk_name: str,
        all_agents: list[AgentConfig],
        required_agents: set[str] | None = None,
    ) -> list[AgentConfig]:
        """Return agents in the chunk, capped at max_conversation_size.

        Uses weighted random selection that prioritises agents who have
        not spoken recently and key roles (Vera, Sentinel).  If
        *required_agents* are specified they are always included.
        """
        local_ids = set(await self.get_group(chunk_name))
        max_size = self._config.proximity.max_conversation_size
        eligible = [a for a in all_agents if a.id in local_ids]
        return self._weighted_select(eligible, max_size, required_agents)

    async def check_eavesdroppers(
        self,
        chunk_name: str,
        topic: str,
        all_agents: list[AgentConfig],
        adjacent_chunks: list[str],
    ) -> list[str]:
        """Check if agents in adjacent chunks should walk over to join.

        Eavesdrop probability = eavesdrop_tendency * 0.6 + topic_relevance * 0.4

        Returns list of agent IDs that decide to move. Emits an
        "agent_move" event for each joiner.
        """
        current_group_size = len(await self.get_group(chunk_name))
        max_size = self._config.proximity.max_conversation_size
        eavesdrop_cfg = self._config.proximity.eavesdrop_tendency

        # Build a lookup for topic relevance from config
        topic_scores = self._config.topics.relevance_map.get(topic, {})

        joiners: list[str] = []

        for adj_chunk in adjacent_chunks:
            for agent_id in await self.get_group(adj_chunk):
                if current_group_size + len(joiners) >= max_size:
                    break

                tendency = eavesdrop_cfg.get(agent_id, 0.3)
                relevance = topic_scores.get(agent_id, 0.3)
                probability = tendency * 0.6 + relevance * 0.4

                if random.random() < probability:
                    joiners.append(agent_id)
                    await self.update_location(agent_id, chunk_name)
                    await self._event_bus.emit(
                        EventType.AGENT_MOVE.value,
                        {
                            "agent_id": agent_id,
                            "from_chunk": adj_chunk,
                            "to_chunk": chunk_name,
                            "reason": "eavesdrop",
                            "topic": topic,
                            "probability": round(probability, 3),
                        },
                    )

        return joiners

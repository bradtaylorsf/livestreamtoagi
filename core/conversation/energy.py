"""Conversation energy model.

Energy determines conversation lifespan — it starts at a random value,
decays each turn, and gets boosted by topic shifts, disagreements,
audience events, and new participants.  Conversations end when energy
hits 0 (after the minimum-turn threshold).
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import EnergyConfig

logger = logging.getLogger(__name__)


class ConversationEnergy:
    """Tracks and updates conversation energy each turn."""

    def __init__(self, config: EnergyConfig) -> None:
        self._config = config
        lo, hi = config.initial_range
        self._energy: float = random.randint(lo, hi)
        self._turn_count: int = 0
        self._topics_seen: set[str] = set()
        self._last_topic: str | None = None

    # ── public properties ──────────────────────────────────────

    @property
    def energy(self) -> float:
        return self._energy

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def should_continue(self) -> bool:
        """Whether the conversation should keep going."""
        if self._turn_count < self._config.minimum_turns:
            return True
        if self._turn_count >= self._config.maximum_turns:
            return False
        return self._energy > 0

    # ── tick ───────────────────────────────────────────────────

    def tick(
        self,
        topic: str,
        event: str | None = None,
    ) -> dict[str, float]:
        """Advance one turn, updating energy.

        Returns a breakdown dict with individual changes and the
        resulting energy level.
        """
        self._turn_count += 1

        decay = -self._config.decay_per_turn
        topic_shift = 0.0
        repetition = 0.0
        disagreement = 0.0
        audience = 0.0
        new_participant = 0.0

        # ── topic analysis ─────────────────────────────────────
        if topic not in self._topics_seen:
            topic_shift = self._config.boost_on_topic_shift
        else:
            repetition = -self._config.drain_on_repetition

        self._topics_seen.add(topic)
        self._last_topic = topic

        # ── event boosts ───────────────────────────────────────
        if event == "disagreement":
            disagreement = self._config.boost_on_disagreement
        elif event == "audience":
            audience = self._config.boost_on_audience_event
        elif event == "new_participant":
            new_participant = self._config.boost_on_new_participant

        net = decay + topic_shift + repetition + disagreement + audience + new_participant
        self._energy += net

        breakdown = {
            "decay": decay,
            "topic_shift": topic_shift,
            "repetition": repetition,
            "disagreement": disagreement,
            "audience": audience,
            "new_participant": new_participant,
            "net": net,
            "remaining": self._energy,
        }

        logger.debug(
            "energy tick turn=%d net=%.1f remaining=%.1f",
            self._turn_count, net, self._energy,
        )

        return breakdown

    # ── closer selection ───────────────────────────────────────

    def select_closer(self, eligible_agents: list[str]) -> str:
        """Pick a conversation closer via weighted random selection."""
        weights = self._config.closer_weights
        filtered = {
            agent: weights.get(agent, 0.0)
            for agent in eligible_agents
            if weights.get(agent, 0.0) > 0
        }

        if not filtered:
            return random.choice(eligible_agents)

        agents = list(filtered.keys())
        agent_weights = list(filtered.values())
        return random.choices(agents, weights=agent_weights, k=1)[0]

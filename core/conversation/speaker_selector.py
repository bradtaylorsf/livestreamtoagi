"""5-factor weighted speaker selection algorithm.

Selects the next speaker using a weighted combination of:
  1. time_since_spoke  — longer silence → more likely to speak
  2. topic_relevance   — agent expertise match to current topic
  3. chattiness        — personality trait from agent config
  4. adjacency_fit     — natural response pairing with previous speaker
  5. random_jitter     — pure randomness for unpredictability

Final selection uses weighted random (not argmax) so the highest scorer
doesn't always win.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import Any

from core.models import AgentConfig, ConversationConfig, SelectionResult

logger = logging.getLogger(__name__)

# If an agent has never spoken, assume they last spoke 120s ago.
_DEFAULT_SILENCE_SECONDS = 120.0
# time_since_spoke is capped at 300s (5 minutes).
_MAX_SILENCE_SECONDS = 300.0


class SpeakerSelector:
    """Selects the next speaker using the 5-factor weighted algorithm."""

    def __init__(self, config: ConversationConfig) -> None:
        self._config = config

    @property
    def config(self) -> ConversationConfig:
        return self._config

    @config.setter
    def config(self, value: ConversationConfig) -> None:
        self._config = value

    def select(
        self,
        conversation_history: list[dict[str, Any]],
        eligible_agents: list[AgentConfig],
        energy: float,
        detected_topic: str | None = None,
    ) -> SelectionResult:
        """Pick the next speaker from *eligible_agents*.

        Parameters
        ----------
        conversation_history:
            List of message dicts, each with at least ``speaker`` (str)
            and ``timestamp`` (ISO-8601 str or datetime).
        eligible_agents:
            Agents that may speak this turn.
        energy:
            Current conversation energy (unused by selection but passed
            through for context).
        detected_topic:
            The topic detected for the current turn, or None.

        Returns
        -------
        SelectionResult with full score breakdown for logging.
        """
        previous_speaker_id = self._get_previous_speaker(conversation_history)

        # Filter out previous speaker
        candidates = [
            a for a in eligible_agents if a.id != previous_speaker_id
        ]

        # Edge case: only 1 eligible agent (or all filtered out)
        if len(candidates) == 0:
            # Fall back to original list (previous speaker is only option)
            candidates = list(eligible_agents)
        if len(candidates) == 1:
            agent = candidates[0]
            return SelectionResult(
                selected_agent_id=agent.id,
                scores={agent.id: 1.0},
                score_breakdown={
                    agent.id: {
                        "time_since_spoke": 1.0,
                        "topic_relevance": 1.0,
                        "chattiness": agent.chattiness,
                        "adjacency_fit": 1.0,
                        "random_jitter": 1.0,
                    }
                },
                eligible_agents=[a.id for a in eligible_agents],
                previous_speaker_id=previous_speaker_id,
                detected_topic=detected_topic,
            )

        now = datetime.now(timezone.utc)
        weights = self._config.selection_weights
        scores: dict[str, float] = {}
        breakdown: dict[str, dict[str, float]] = {}

        for agent in candidates:
            factors = self._score_agent(
                agent, previous_speaker_id, detected_topic,
                conversation_history, now,
            )
            total = self._weighted_sum(factors, weights)
            scores[agent.id] = total
            breakdown[agent.id] = factors

        selected_id = self._weighted_random_select(scores)

        return SelectionResult(
            selected_agent_id=selected_id,
            scores=scores,
            score_breakdown=breakdown,
            eligible_agents=[a.id for a in eligible_agents],
            previous_speaker_id=previous_speaker_id,
            detected_topic=detected_topic,
        )

    # ── internal helpers ────────────────────────────────────────

    @staticmethod
    def _get_previous_speaker(
        conversation_history: list[dict[str, Any]],
    ) -> str | None:
        """Return the speaker ID of the last message, or None."""
        if not conversation_history:
            return None
        return conversation_history[-1].get("speaker")

    def _score_agent(
        self,
        agent: AgentConfig,
        previous_speaker_id: str | None,
        detected_topic: str | None,
        conversation_history: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, float]:
        """Compute the 5 raw factor scores for a single agent."""
        return {
            "time_since_spoke": self._calc_time_since_spoke(
                agent.id, conversation_history, now,
            ),
            "topic_relevance": self._calc_topic_relevance(
                agent.id, detected_topic,
            ),
            "chattiness": agent.chattiness,
            "adjacency_fit": self._calc_adjacency_fit(
                agent.id, previous_speaker_id,
            ),
            "random_jitter": random.random(),
        }

    def _calc_time_since_spoke(
        self,
        agent_id: str,
        conversation_history: list[dict[str, Any]],
        now: datetime,
    ) -> float:
        """Normalized 0-1, capped at 5 minutes (300s)."""
        last_ts: datetime | None = None
        for msg in reversed(conversation_history):
            if msg.get("speaker") == agent_id:
                ts = msg.get("timestamp")
                if isinstance(ts, datetime):
                    last_ts = ts
                elif isinstance(ts, str):
                    last_ts = datetime.fromisoformat(ts)
                break

        if last_ts is None:
            elapsed = _DEFAULT_SILENCE_SECONDS
        else:
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            elapsed = (now - last_ts).total_seconds()

        return min(elapsed / _MAX_SILENCE_SECONDS, 1.0)

    def _calc_topic_relevance(
        self, agent_id: str, detected_topic: str | None,
    ) -> float:
        """Lookup from relevance_map, default 0.3."""
        if detected_topic is None:
            return 0.3
        topic_scores = self._config.topics.relevance_map.get(detected_topic, {})
        return topic_scores.get(agent_id, 0.3)

    def _calc_adjacency_fit(
        self, agent_id: str, previous_speaker_id: str | None,
    ) -> float:
        """Lookup from adjacency config, default 0.3. No previous → 0.5."""
        if previous_speaker_id is None:
            return 0.5
        prev_map = self._config.adjacency.get(previous_speaker_id, {})
        return prev_map.get(agent_id, 0.3)

    @staticmethod
    def _weighted_sum(
        factors: dict[str, float],
        weights: Any,  # SelectionWeights
    ) -> float:
        """Combine factor scores using configured weights."""
        return (
            factors["time_since_spoke"] * weights.time_since_spoke
            + factors["topic_relevance"] * weights.topic_relevance
            + factors["chattiness"] * weights.chattiness
            + factors["adjacency_fit"] * weights.adjacency_fit
            + factors["random_jitter"] * weights.random_jitter
        )

    @staticmethod
    def _weighted_random_select(scores: dict[str, float]) -> str:
        """Weighted random pick (not argmax) from score dict."""
        agent_ids = list(scores.keys())
        weights = [max(scores[aid], 0.0) for aid in agent_ids]

        # If all weights are zero, fall back to uniform random
        if sum(weights) == 0:
            return random.choice(agent_ids)

        return random.choices(agent_ids, weights=weights, k=1)[0]

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
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from core.models import (
    AgentConfig,
    ConversationConfig,
    InterruptAttempt,
    SelectionResult,
    SelectionWeights,
)

logger = logging.getLogger(__name__)

# If an agent has never spoken, assume they last spoke 120s ago.
_DEFAULT_SILENCE_SECONDS = 120.0
# time_since_spoke is capped at 300s (5 minutes).
_MAX_SILENCE_SECONDS = 300.0


@dataclass
class InterruptState:
    """Mutable per-conversation interrupt tracking state."""

    interrupt_count: int = 0
    last_interrupt_time: dict[str, float] = field(default_factory=dict)


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
        interrupt_state: InterruptState | None = None,
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
        interrupt_state:
            Mutable per-conversation interrupt tracking. If provided and
            interrupts are enabled, interrupt checking runs after normal
            selection.

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

        now = datetime.now(UTC)
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

        # ── Interrupt check ────────────────────────────────────
        was_interrupt = False
        interrupted_agent_id: str | None = None
        interrupt_attempts: list[InterruptAttempt] = []

        if (
            interrupt_state is not None
            and self._config.interrupts.enabled
        ):
            interrupt_attempts = self._check_interrupts(
                eligible_agents, selected_id, detected_topic, interrupt_state,
            )
            # Find successful interrupt (highest score wins)
            for attempt in interrupt_attempts:
                if attempt.succeeded:
                    was_interrupt = True
                    interrupted_agent_id = selected_id
                    selected_id = attempt.attempting_agent_id
                    break  # Only one winner

        return SelectionResult(
            selected_agent_id=selected_id,
            scores=scores,
            score_breakdown=breakdown,
            eligible_agents=[a.id for a in eligible_agents],
            previous_speaker_id=previous_speaker_id,
            detected_topic=detected_topic,
            was_interrupt=was_interrupt,
            interrupted_agent_id=interrupted_agent_id,
            interrupt_attempts=interrupt_attempts,
        )

    # ── interrupt logic ─────────────────────────────────────────

    def _check_interrupts(
        self,
        eligible_agents: list[AgentConfig],
        selected_agent_id: str,
        detected_topic: str | None,
        state: InterruptState,
    ) -> list[InterruptAttempt]:
        """Evaluate all agents for interrupt eligibility.

        Returns a list of InterruptAttempt records (successful + failed)
        sorted by interrupt_score descending. At most one attempt will
        have ``succeeded=True``. The caller logs all attempts.
        """
        cfg = self._config.interrupts
        threshold = cfg.relevance_threshold
        now = time.monotonic()
        attempts: list[InterruptAttempt] = []
        winner_found = False

        # Build scored candidates (exclude the already-selected agent)
        scored: list[tuple[AgentConfig, float, float]] = []
        for agent in eligible_agents:
            if agent.id == selected_agent_id:
                continue
            topic_rel = self._calc_topic_relevance(agent.id, detected_topic)
            tendency = cfg.agent_interrupt_tendency.get(
                agent.id, agent.interrupt_tendency,
            )
            # Additive weighted score: tendency drives willingness,
            # topic relevance gates appropriateness
            score = tendency * 0.6 + topic_rel * 0.4
            scored.append((agent, score, tendency))

        # Sort by score descending so highest scorer gets first chance
        scored.sort(key=lambda t: t[1], reverse=True)

        for agent, score, _tendency in scored:

            # Gate 1: score >= threshold
            if score < threshold:
                attempts.append(InterruptAttempt(
                    attempting_agent_id=agent.id,
                    would_have_spoken_id=selected_agent_id,
                    interrupt_score=score,
                    threshold=threshold,
                    succeeded=False,
                    reason="below_threshold",
                ))
                continue

            # Gate 2: conversation cap
            if state.interrupt_count >= cfg.max_interrupts_per_conversation:
                attempts.append(InterruptAttempt(
                    attempting_agent_id=agent.id,
                    would_have_spoken_id=selected_agent_id,
                    interrupt_score=score,
                    threshold=threshold,
                    succeeded=False,
                    reason="conversation_cap_reached",
                ))
                continue

            # Gate 3: per-agent cooldown
            last = state.last_interrupt_time.get(agent.id)
            if last is not None and (now - last) < cfg.cooldown_seconds:
                attempts.append(InterruptAttempt(
                    attempting_agent_id=agent.id,
                    would_have_spoken_id=selected_agent_id,
                    interrupt_score=score,
                    threshold=threshold,
                    succeeded=False,
                    reason="cooldown",
                ))
                continue

            # All gates passed — first qualifying agent wins
            if not winner_found:
                winner_found = True
                state.interrupt_count += 1
                state.last_interrupt_time[agent.id] = now
                attempts.append(InterruptAttempt(
                    attempting_agent_id=agent.id,
                    would_have_spoken_id=selected_agent_id,
                    interrupt_score=score,
                    threshold=threshold,
                    succeeded=True,
                ))
            else:
                # Another agent already won this turn
                attempts.append(InterruptAttempt(
                    attempting_agent_id=agent.id,
                    would_have_spoken_id=selected_agent_id,
                    interrupt_score=score,
                    threshold=threshold,
                    succeeded=False,
                    reason="another_agent_interrupted",
                ))

        return attempts

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
                last_ts = last_ts.replace(tzinfo=UTC)
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
        weights: SelectionWeights,
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
        if sum(weights) < 1e-9:
            return random.choice(agent_ids)

        return random.choices(agent_ids, weights=weights, k=1)[0]

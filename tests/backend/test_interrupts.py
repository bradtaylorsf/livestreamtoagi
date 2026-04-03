"""Unit tests for interrupt mechanics in speaker selection."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import patch

from core.conversation.speaker_selector import InterruptState, SpeakerSelector
from core.models import AgentConfig, ConversationConfig
from tests.backend.conversation_helpers import make_agent_config, make_conversation_config

# ── Fixtures ────────────────────────────────────────────────


def _make_agent(
    agent_id: str,
    chattiness: float = 0.5,
    interrupt_tendency: float = 0.3,
) -> AgentConfig:
    return make_agent_config(
        agent_id,
        chattiness=chattiness,
        interrupt_tendency=interrupt_tendency,
    )


def _make_config(**overrides) -> ConversationConfig:
    """Build a ConversationConfig with interrupt-test-specific defaults."""
    interrupt_defaults = {
        "interrupts": {
            "enabled": True,
            "relevance_threshold": 0.85,
            "max_interrupts_per_conversation": 3,
            "cooldown_seconds": 30,
            "agent_interrupt_tendency": {
                "grok": 0.8,
                "sentinel": 0.7,
                "overseer": 1.0,
                "rex": 0.3,
                "vera": 0.2,
            },
        },
        "topics": {
            "relevance_map": {
                "code": {"rex": 0.9, "fork": 0.7, "grok": 0.95, "vera": 0.4},
                "safety": {"overseer": 1.0, "sentinel": 0.9, "vera": 0.5},
            },
            "fallback_to_llm": False,
            "classifier_model": "claude-haiku-4-5",
        },
    }
    interrupt_defaults.update(overrides)
    return make_conversation_config(**interrupt_defaults)


# ── Tests ───────────────────────────────────────────────────


class TestHighRelevanceInterrupt:
    def test_high_relevance_agent_interrupts(self):
        """Agent with topic_relevance × interrupt_tendency >= 0.85 overrides selection."""
        config = _make_config()
        selector = SpeakerSelector(config)
        state = InterruptState()

        # grok: code relevance=0.95, tendency=0.8 → score=0.76 (below 0.85)
        # But let's set up a scenario where score >= 0.85:
        # overseer: safety relevance=1.0, tendency=1.0 → score=1.0
        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("rex", interrupt_tendency=0.3),
            _make_agent("overseer", interrupt_tendency=1.0),
        ]

        # Force vera to be the normal selection by seeding,
        # then overseer should interrupt on "safety" topic
        history = [
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
        ]

        # We need to ensure vera gets selected normally (not overseer).
        # Use a patched _weighted_random_select to guarantee vera is picked first.
        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="safety",
                interrupt_state=state,
            )

        assert result.was_interrupt is True
        assert result.selected_agent_id == "overseer"
        assert result.interrupted_agent_id == "vera"
        assert state.interrupt_count == 1


class TestLowRelevanceNoInterrupt:
    def test_low_relevance_no_interrupt(self):
        """Agent below threshold does not interrupt."""
        config = _make_config()
        selector = SpeakerSelector(config)
        state = InterruptState()

        # rex: code relevance=0.9, tendency=0.3 → score=0.27 (well below 0.85)
        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("rex", interrupt_tendency=0.3),
        ]

        history = [
            {"speaker": "fork", "timestamp": datetime.now(UTC).isoformat()},
        ]

        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="code",
                interrupt_state=state,
            )

        assert result.was_interrupt is False
        assert result.selected_agent_id == "vera"
        assert result.interrupted_agent_id is None
        assert state.interrupt_count == 0


class TestInterruptCapEnforced:
    def test_interrupt_cap_enforced(self):
        """After max_interrupts_per_conversation (3), no more interrupts allowed."""
        config = _make_config()
        selector = SpeakerSelector(config)

        # Pre-fill state to max capacity
        state = InterruptState(interrupt_count=3)

        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("overseer", interrupt_tendency=1.0),
        ]

        history = [
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
        ]

        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="safety",
                interrupt_state=state,
            )

        assert result.was_interrupt is False
        assert result.selected_agent_id == "vera"
        # Overseer's attempt should be logged as failed
        failed = [a for a in result.interrupt_attempts if not a.succeeded]
        assert any(a.reason == "conversation_cap_reached" for a in failed)
        assert state.interrupt_count == 3  # unchanged


class TestCooldownPreventsReinterrupt:
    def test_cooldown_prevents_reinterrupt(self):
        """Same agent can't interrupt twice within cooldown_seconds."""
        config = _make_config()
        selector = SpeakerSelector(config)

        # overseer interrupted 5 seconds ago (well within 30s cooldown)
        state = InterruptState(
            interrupt_count=1,
            last_interrupt_time={"overseer": time.monotonic() - 5},
        )

        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("overseer", interrupt_tendency=1.0),
        ]

        history = [
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
        ]

        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="safety",
                interrupt_state=state,
            )

        assert result.was_interrupt is False
        assert result.selected_agent_id == "vera"
        failed = [a for a in result.interrupt_attempts if not a.succeeded]
        assert any(a.reason == "cooldown" for a in failed)
        assert state.interrupt_count == 1  # unchanged


class TestOverseerAlwaysInterrupts:
    def test_overseer_always_interrupts_on_safety(self):
        """Overseer with tendency=1.0 interrupts when topic relevance is high enough."""
        config = _make_config()
        selector = SpeakerSelector(config)
        state = InterruptState()

        # overseer: safety relevance=1.0, tendency=1.0 → score=1.0 >= 0.85
        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("rex", interrupt_tendency=0.3),
            _make_agent("overseer", interrupt_tendency=1.0),
        ]

        history = [
            {"speaker": "fork", "timestamp": datetime.now(UTC).isoformat()},
        ]

        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="safety",
                interrupt_state=state,
            )

        assert result.was_interrupt is True
        assert result.selected_agent_id == "overseer"
        assert state.interrupt_count == 1


class TestInterruptLogRecordsAttempts:
    def test_interrupt_log_records_attempts(self):
        """Both successful and failed attempts are returned for logging."""
        config = _make_config()
        selector = SpeakerSelector(config)
        state = InterruptState()

        # overseer will succeed (score=1.0), rex will fail (score=0.27)
        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("rex", interrupt_tendency=0.3),
            _make_agent("overseer", interrupt_tendency=1.0),
        ]

        history = [
            {"speaker": "fork", "timestamp": datetime.now(UTC).isoformat()},
        ]

        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="safety",
                interrupt_state=state,
            )

        # Should have attempts for both overseer and rex (vera is selected, excluded)
        assert len(result.interrupt_attempts) >= 2
        succeeded = [a for a in result.interrupt_attempts if a.succeeded]
        failed = [a for a in result.interrupt_attempts if not a.succeeded]
        assert len(succeeded) == 1
        assert succeeded[0].attempting_agent_id == "overseer"
        assert len(failed) >= 1
        # rex should fail with below_threshold
        rex_attempts = [a for a in failed if a.attempting_agent_id == "rex"]
        assert len(rex_attempts) == 1
        assert rex_attempts[0].reason == "below_threshold"


class TestInterruptedAgentRecorded:
    def test_interrupted_agent_recorded(self):
        """SelectionResult.interrupted_agent_id matches the would-have-spoken agent."""
        config = _make_config()
        selector = SpeakerSelector(config)
        state = InterruptState()

        agents = [
            _make_agent("vera", interrupt_tendency=0.2),
            _make_agent("overseer", interrupt_tendency=1.0),
        ]

        history = [
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
        ]

        with patch.object(
            SpeakerSelector, "_weighted_random_select", return_value="vera",
        ):
            result = selector.select(
                history, agents, energy=10.0,
                detected_topic="safety",
                interrupt_state=state,
            )

        assert result.interrupted_agent_id == "vera"
        assert result.selected_agent_id == "overseer"
        # The successful attempt should also record would_have_spoken_id
        succeeded = [a for a in result.interrupt_attempts if a.succeeded]
        assert succeeded[0].would_have_spoken_id == "vera"

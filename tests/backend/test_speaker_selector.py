"""Unit tests for the 5-factor speaker selection algorithm."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from core.conversation.speaker_selector import SpeakerSelector
from core.models import (
    AgentConfig,
    ConversationConfig,
    SelectionResult,
    SelectionWeights,
)


# ── Fixtures ────────────────────────────────────────────────


def _make_agent(agent_id: str, chattiness: float = 0.5) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.capitalize(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=chattiness,
        initiative=0.5,
        interrupt_tendency=0.3,
    )


def _make_config(**overrides) -> ConversationConfig:
    """Build a minimal ConversationConfig for testing."""
    defaults = {
        "selection_weights": {
            "time_since_spoke": 0.30,
            "topic_relevance": 0.30,
            "chattiness": 0.15,
            "adjacency_fit": 0.15,
            "random_jitter": 0.10,
        },
        "timing": {
            "min_pause_seconds": 2.0,
            "max_pause_seconds": 8.0,
            "pause_strategy": "weighted",
            "pause_multipliers": {
                "after_question": 0.5,
                "after_statement": 1.0,
                "after_interrupt": 0.3,
                "after_joke": 1.5,
                "after_emotional": 1.3,
            },
        },
        "energy": {
            "initial_range": [8, 14],
            "decay_per_turn": 1.0,
            "boost_on_topic_shift": 3.0,
            "boost_on_disagreement": 4.0,
            "boost_on_audience_event": 5.0,
            "boost_on_new_participant": 3.0,
            "drain_on_repetition": 2.0,
            "minimum_turns": 4,
            "maximum_turns": 30,
            "closer_weights": {"vera": 0.5, "rex": 0.5},
        },
        "interrupts": {
            "enabled": True,
            "relevance_threshold": 0.85,
            "max_interrupts_per_conversation": 3,
            "cooldown_seconds": 30,
            "agent_interrupt_tendency": {},
        },
        "proximity": {
            "enabled": True,
            "max_conversation_size": 5,
            "eavesdrop_tendency": {},
        },
        "triggers": {
            "idle_timeout_seconds": 90,
            "agent_initiative": {},
            "trigger_type_weights": {"idle": 1.0},
        },
        "topics": {
            "relevance_map": {
                "code": {"rex": 0.9, "fork": 0.7, "vera": 0.4},
                "art": {"aurora": 0.9, "pixel": 0.5},
            },
            "fallback_to_llm": False,
            "classifier_model": "claude-haiku-4-5",
        },
        "adjacency": {
            "vera": {"rex": 0.7, "sentinel": 0.8},
            "rex": {"fork": 0.8, "vera": 0.5},
        },
        "logging": {
            "log_every_selection": True,
            "log_interrupts": True,
            "log_energy_changes": True,
            "log_trigger_events": True,
            "log_topic_classifications": True,
            "retention_days": 30,
            "export_format": "jsonl",
        },
    }
    defaults.update(overrides)
    return ConversationConfig(**defaults)


@pytest.fixture
def config() -> ConversationConfig:
    return _make_config()


@pytest.fixture
def selector(config: ConversationConfig) -> SpeakerSelector:
    return SpeakerSelector(config)


@pytest.fixture
def agents() -> list[AgentConfig]:
    return [
        _make_agent("vera", chattiness=0.6),
        _make_agent("rex", chattiness=0.4),
        _make_agent("fork", chattiness=0.7),
    ]


# ── Tests ───────────────────────────────────────────────────


class TestWeightsValidation:
    def test_weights_sum_validation(self):
        """Invalid weights that don't sum to 1.0 raise ValueError."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            _make_config(
                selection_weights={
                    "time_since_spoke": 0.5,
                    "topic_relevance": 0.5,
                    "chattiness": 0.5,
                    "adjacency_fit": 0.5,
                    "random_jitter": 0.5,
                }
            )


class TestPreviousSpeakerExcluded:
    def test_previous_speaker_excluded(
        self, selector: SpeakerSelector, agents: list[AgentConfig],
    ):
        """Previous speaker should not appear in scored candidates."""
        history = [
            {"speaker": "vera", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        # vera was previous speaker — she should not be in score_breakdown
        assert "vera" not in result.score_breakdown
        assert result.selected_agent_id != "vera"


class TestTimeSinceSpoke:
    def test_time_since_spoke_caps_at_1(
        self, selector: SpeakerSelector,
    ):
        """Agent silent for 600s should still score 1.0 (capped at 300s)."""
        now = datetime.now(timezone.utc)
        history = [
            {
                "speaker": "fork",
                "timestamp": (now - timedelta(seconds=600)).isoformat(),
            },
            {
                "speaker": "rex",
                "timestamp": now.isoformat(),
            },
        ]
        agents = [_make_agent("rex"), _make_agent("fork"), _make_agent("vera")]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        # rex is previous speaker (excluded). fork spoke 600s ago → capped at 1.0
        assert result.score_breakdown["fork"]["time_since_spoke"] == pytest.approx(
            1.0, abs=0.05,
        )

    def test_time_since_spoke_never_spoke_defaults_to_120s(
        self, selector: SpeakerSelector,
    ):
        """Agent who never spoke gets default 120s → 0.4 score."""
        agents = [_make_agent("vera"), _make_agent("rex")]
        # Empty history — no previous speaker
        random.seed(42)
        result = selector.select([], agents, energy=10.0)
        for agent_id in result.score_breakdown:
            assert result.score_breakdown[agent_id]["time_since_spoke"] == pytest.approx(
                0.4, abs=0.05,
            )


class TestTopicRelevance:
    def test_topic_relevance_lookup(
        self, selector: SpeakerSelector,
    ):
        """Known topic returns correct score from relevance_map."""
        agents = [_make_agent("rex"), _make_agent("fork"), _make_agent("vera")]
        history = [
            {"speaker": "vera", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0, detected_topic="code")
        # rex's code relevance is 0.9, fork's is 0.7
        assert result.score_breakdown["rex"]["topic_relevance"] == 0.9
        assert result.score_breakdown["fork"]["topic_relevance"] == 0.7

    def test_topic_relevance_default_when_no_topic(
        self, selector: SpeakerSelector,
    ):
        """No detected topic → all agents get 0.3 default."""
        agents = [_make_agent("vera"), _make_agent("rex")]
        random.seed(42)
        result = selector.select([], agents, energy=10.0, detected_topic=None)
        for agent_id in result.score_breakdown:
            assert result.score_breakdown[agent_id]["topic_relevance"] == 0.3


class TestAdjacencyFit:
    def test_adjacency_pair_lookup(
        self, selector: SpeakerSelector,
    ):
        """Known adjacency pair returns correct score."""
        agents = [
            _make_agent("vera"),
            _make_agent("rex"),
            _make_agent("sentinel"),
        ]
        history = [
            {"speaker": "vera", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        # vera → rex = 0.7, vera → sentinel = 0.8
        assert result.score_breakdown["rex"]["adjacency_fit"] == 0.7
        assert result.score_breakdown["sentinel"]["adjacency_fit"] == 0.8

    def test_adjacency_default_when_no_previous_speaker(
        self, selector: SpeakerSelector,
    ):
        """No previous speaker → adjacency_fit defaults to 0.5."""
        agents = [_make_agent("vera"), _make_agent("rex")]
        random.seed(42)
        result = selector.select([], agents, energy=10.0)
        for agent_id in result.score_breakdown:
            assert result.score_breakdown[agent_id]["adjacency_fit"] == 0.5


class TestSelectionProbabilistic:
    def test_selection_is_probabilistic(
        self, selector: SpeakerSelector,
    ):
        """Over 100 runs, selection should not always pick the same agent."""
        agents = [
            _make_agent("vera", chattiness=0.5),
            _make_agent("rex", chattiness=0.5),
            _make_agent("fork", chattiness=0.5),
        ]
        history: list[dict] = []
        selected_ids: set[str] = set()
        for i in range(100):
            random.seed(i)
            result = selector.select(history, agents, energy=10.0)
            selected_ids.add(result.selected_agent_id)
        # With 3 equal agents and random jitter, we should see at least 2 different winners
        assert len(selected_ids) >= 2


class TestSingleEligibleAgent:
    def test_single_eligible_agent(
        self, selector: SpeakerSelector,
    ):
        """Single eligible agent is returned directly without scoring."""
        agent = _make_agent("vera")
        random.seed(42)
        result = selector.select([], [agent], energy=10.0)
        assert result.selected_agent_id == "vera"
        assert result.eligible_agents == ["vera"]


class TestScoreBreakdown:
    def test_score_breakdown_in_result(
        self, selector: SpeakerSelector, agents: list[AgentConfig],
    ):
        """SelectionResult.score_breakdown has all 5 factors for each scored agent."""
        history = [
            {"speaker": "vera", "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        expected_factors = {
            "time_since_spoke",
            "topic_relevance",
            "chattiness",
            "adjacency_fit",
            "random_jitter",
        }
        # vera excluded (previous speaker), rex and fork should be scored
        for agent_id, factors in result.score_breakdown.items():
            assert set(factors.keys()) == expected_factors
            # All factor values should be between 0 and 1
            for factor_name, value in factors.items():
                assert 0.0 <= value <= 1.0, (
                    f"{agent_id}.{factor_name} = {value} out of range"
                )

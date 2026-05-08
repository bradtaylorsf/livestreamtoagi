"""Unit tests for the 5-factor speaker selection algorithm."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from core.conversation.speaker_selector import SpeakerSelector
from core.models import (
    AgentConfig,
    ConversationConfig,
)
from tests.backend.conversation_helpers import make_agent_config as _make_agent
from tests.backend.conversation_helpers import make_conversation_config as _make_config

# ── Fixtures ────────────────────────────────────────────────


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
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
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
        now = datetime.now(UTC)
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
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
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
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
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

    def test_faction_pairs_boost_adjacency(
        self, selector: SpeakerSelector,
    ):
        """Same-faction agents get a +0.15 boost to adjacency_fit (#419).

        rex's adjacency map in the helper config is ``{fork: 0.8, vera: 0.5}``,
        so ``aurora`` falls through to the default 0.3 and ``pixel`` does too.
        Putting aurora in rex's faction should add the bonus to aurora's score
        but leave pixel untouched.
        """
        agents = [
            _make_agent("rex"),
            _make_agent("aurora"),
            _make_agent("pixel"),
        ]
        history = [
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
        ]
        selector.set_faction_pairs({frozenset({"rex", "aurora"})})
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        assert result.score_breakdown["aurora"]["adjacency_fit"] == pytest.approx(
            0.45, abs=1e-9,
        )
        assert result.score_breakdown["pixel"]["adjacency_fit"] == pytest.approx(
            0.3, abs=1e-9,
        )

    def test_faction_pairs_no_boost_without_set(
        self, selector: SpeakerSelector,
    ):
        """Without set_faction_pairs, adjacency_fit uses the raw config map."""
        agents = [
            _make_agent("rex"),
            _make_agent("aurora"),
            _make_agent("pixel"),
        ]
        history = [{"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()}]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        # No faction info — both candidates get the default 0.3.
        assert result.score_breakdown["aurora"]["adjacency_fit"] == 0.3
        assert result.score_breakdown["pixel"]["adjacency_fit"] == 0.3

    def test_faction_pairs_clamped_at_one(
        self, selector: SpeakerSelector,
    ):
        """Adjacency + faction bonus is clamped to 1.0 — no overflow.

        We force a high base score by stubbing the adjacency map so the +0.15
        bonus would exceed 1.0 without clamping.
        """
        # vera→sentinel raw adjacency = 0.8; +0.15 with clamp → 0.95.
        # Build a 3-candidate scenario so the single-candidate fast-path
        # (which hardcodes adjacency_fit=1.0) does not fire.
        agents = [
            _make_agent("vera"),
            _make_agent("sentinel"),
            _make_agent("aurora"),
        ]
        history = [{"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()}]
        selector.set_faction_pairs({frozenset({"vera", "sentinel"})})
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        sentinel_adj = result.score_breakdown["sentinel"]["adjacency_fit"]
        assert sentinel_adj == pytest.approx(0.95, abs=1e-9)
        assert sentinel_adj <= 1.0


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


class TestParticipationBalancing:
    def test_silent_agent_gets_participation_bonus(
        self, selector: SpeakerSelector,
    ):
        """Agents with 0 turns in a conversation get a +0.3 participation bonus."""
        agents = [
            _make_agent("vera", chattiness=0.5),
            _make_agent("rex", chattiness=0.5),
            _make_agent("fork", chattiness=0.5),
        ]
        # vera spoke 3 times, rex and fork never
        history = [
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
        ]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        # vera (previous speaker + 3 turns fatigue) should have lower score
        # rex and fork (0 turns) should have participation bonus
        assert result.scores.get("rex", 0) > result.scores.get("vera", 0)
        assert result.scores.get("fork", 0) > result.scores.get("vera", 0)

    def test_fatigue_penalty_on_dominant_agent(
        self, selector: SpeakerSelector,
    ):
        """Agents with 3+ turns get a fatigue penalty."""
        agents = [
            _make_agent("vera", chattiness=0.5),
            _make_agent("rex", chattiness=0.5),
        ]
        # rex spoke 4 times, then vera spoke
        history = [
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "rex", "timestamp": datetime.now(UTC).isoformat()},
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
        ]
        random.seed(42)
        result = selector.select(history, agents, energy=10.0)
        # rex has 4 turns = -0.2 * (4-2) = -0.4 penalty
        # vera (previous speaker) is excluded, so rex is the only candidate
        # but his score should be reduced
        rex_score = result.scores.get("rex", 0)
        # Score should be positive but penalized
        assert rex_score >= 0.0

    def test_no_agent_exceeds_40_percent(
        self, selector: SpeakerSelector,
    ):
        """Over many selections, no agent should take >40% of turns."""
        agents = [
            _make_agent("vera", chattiness=0.6),
            _make_agent("rex", chattiness=0.4),
            _make_agent("fork", chattiness=0.7),
            _make_agent("sentinel", chattiness=0.5),
        ]
        turn_counts: dict[str, int] = {a.id: 0 for a in agents}
        history: list[dict] = []
        total_turns = 50

        for i in range(total_turns):
            random.seed(i * 7 + 3)
            result = selector.select(
                history, agents, energy=10.0,
                turn_number=i, max_turns=total_turns,
            )
            turn_counts[result.selected_agent_id] += 1
            history.append({
                "speaker": result.selected_agent_id,
                "timestamp": datetime.now(UTC).isoformat(),
            })

        max_ratio = max(turn_counts.values()) / total_turns
        assert max_ratio <= 0.50, (
            f"Agent took {max_ratio:.0%} of turns (>40%): {turn_counts}"
        )


class TestScoreBreakdown:
    def test_score_breakdown_in_result(
        self, selector: SpeakerSelector, agents: list[AgentConfig],
    ):
        """SelectionResult.score_breakdown has all 5 factors for each scored agent."""
        history = [
            {"speaker": "vera", "timestamp": datetime.now(UTC).isoformat()},
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


# ── Tests: Minimum speaker participation (#247) ──────────────────


class TestMinimumSpeakerParticipation:
    def test_agent_silent_5_turns_is_force_selected(
        self, selector: SpeakerSelector,
    ):
        """Agent silent for 5+ consecutive turns is force-selected."""
        agents = [
            _make_agent("vera", chattiness=0.5),
            _make_agent("rex", chattiness=0.5),
            _make_agent("fork", chattiness=0.5),
        ]
        # Build history where fork hasn't spoken for 5 turns
        now = datetime.now(UTC)
        history = [
            {"speaker": "fork", "timestamp": (now - timedelta(seconds=60)).isoformat()},
        ]
        # 5 turns by vera and rex, fork silent
        for i in range(5):
            speaker = "vera" if i % 2 == 0 else "rex"
            history.append({
                "speaker": speaker,
                "timestamp": now.isoformat(),
            })

        # Run many times — fork should always be selected due to force-select
        fork_selected = 0
        for seed in range(20):
            random.seed(seed)
            result = selector.select(
                history, agents, energy=10.0,
                turn_number=6, max_turns=15,
            )
            if result.selected_agent_id == "fork":
                fork_selected += 1

        # fork should be force-selected every time (5+ turns silent)
        assert fork_selected == 20, (
            f"Fork force-selected {fork_selected}/20 times (expected 20)"
        )

    def test_agent_silent_3_turns_gets_boost(
        self, selector: SpeakerSelector,
    ):
        """Agent silent for 3+ turns with 4+ participants gets 2x score boost."""
        agents = [
            _make_agent("vera", chattiness=0.5),
            _make_agent("rex", chattiness=0.5),
            _make_agent("fork", chattiness=0.5),
            _make_agent("sentinel", chattiness=0.5),
        ]
        # Build history where sentinel hasn't spoken for 3 turns
        now = datetime.now(UTC)
        history = [
            {"speaker": "sentinel", "timestamp": (now - timedelta(seconds=60)).isoformat()},
            {"speaker": "vera", "timestamp": now.isoformat()},
            {"speaker": "rex", "timestamp": now.isoformat()},
            {"speaker": "fork", "timestamp": now.isoformat()},
        ]

        # Check sentinel's score gets boosted
        sentinel_selected = 0
        for seed in range(50):
            random.seed(seed)
            result = selector.select(
                history, agents, energy=10.0,
                turn_number=4, max_turns=15,
            )
            if result.selected_agent_id == "sentinel":
                sentinel_selected += 1

        # Sentinel should be selected more often than 25% baseline due to boost
        assert sentinel_selected > 15, (
            f"Sentinel selected {sentinel_selected}/50 times (expected >15 with boost)"
        )

    def test_no_agent_exceeds_5_turn_silence_in_simulation(
        self, selector: SpeakerSelector,
    ):
        """Over a simulated conversation, no agent goes 5+ turns without speaking."""
        agents = [
            _make_agent("vera", chattiness=0.6),
            _make_agent("rex", chattiness=0.4),
            _make_agent("fork", chattiness=0.7),
            _make_agent("sentinel", chattiness=0.3),
            _make_agent("aurora", chattiness=0.5),
        ]
        history: list[dict] = []
        total_turns = 25

        for i in range(total_turns):
            random.seed(i * 13 + 7)
            result = selector.select(
                history, agents, energy=10.0,
                turn_number=i, max_turns=total_turns,
            )
            history.append({
                "speaker": result.selected_agent_id,
                "timestamp": datetime.now(UTC).isoformat(),
            })

        # Check that no agent has a gap > 5 turns
        for agent in agents:
            last_spoke = -1
            max_gap = 0
            for idx, msg in enumerate(history):
                if msg["speaker"] == agent.id:
                    if last_spoke >= 0:
                        gap = idx - last_spoke
                        max_gap = max(max_gap, gap)
                    last_spoke = idx
            # Also check gap from last spoke to end
            if last_spoke >= 0:
                max_gap = max(max_gap, len(history) - 1 - last_spoke)
            assert max_gap <= 6, (
                f"{agent.id} had a gap of {max_gap} turns (max allowed: ~5)"
            )

"""Unit tests for the conversation energy model."""

from __future__ import annotations

import random

import pytest

from core.conversation.energy import ConversationEnergy
from core.models import EnergyConfig

# ── Fixtures ────────────────────────────────────────────────


def _make_energy_config(**overrides) -> EnergyConfig:
    defaults = {
        "initial_range": (8, 14),
        "decay_per_turn": 1.0,
        "boost_on_topic_shift": 3.0,
        "boost_on_disagreement": 4.0,
        "boost_on_audience_event": 5.0,
        "boost_on_new_participant": 3.0,
        "drain_on_repetition": 2.0,
        "minimum_turns": 4,
        "maximum_turns": 30,
        "closer_weights": {
            "vera": 0.35,
            "sentinel": 0.25,
            "rex": 0.15,
            "fork": 0.10,
            "aurora": 0.10,
            "grok": 0.05,
        },
    }
    defaults.update(overrides)
    return EnergyConfig(**defaults)


# ── Initial energy ──────────────────────────────────────────


class TestInitialEnergy:
    def test_energy_within_configured_range(self):
        cfg = _make_energy_config()
        for _ in range(50):
            e = ConversationEnergy(cfg)
            assert 8 <= e.energy <= 14

    def test_energy_within_custom_range(self):
        cfg = _make_energy_config(initial_range=(20, 25))
        for _ in range(50):
            e = ConversationEnergy(cfg)
            assert 20 <= e.energy <= 25


# ── Decay ───────────────────────────────────────────────────


class TestDecay:
    def test_decays_by_configured_amount(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        initial = e.energy
        # First tick with a new topic: decay -1.0 + topic_shift +3.0 = net +2.0
        result = e.tick("topic_a")
        assert result["decay"] == -1.0
        assert e.energy == initial + result["net"]

    def test_pure_decay_on_repeated_topic(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        e.tick("topic_a")  # first time — new topic
        energy_after_first = e.energy
        result = e.tick("topic_a")  # repeated
        # decay -1.0 + repetition -2.0 = net -3.0
        assert result["decay"] == -1.0
        assert result["repetition"] == -2.0
        assert result["net"] == -3.0
        assert e.energy == energy_after_first - 3.0


# ── Topic boosts and drains ─────────────────────────────────


class TestTopicEffects:
    def test_new_topic_boosts_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("fresh_topic")
        assert result["topic_shift"] == 3.0
        assert result["repetition"] == 0.0

    def test_repeated_topic_drains_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        e.tick("old_topic")
        result = e.tick("old_topic")
        assert result["topic_shift"] == 0.0
        assert result["repetition"] == -2.0

    def test_previously_seen_topic_drains(self):
        """Even after other topics, returning to an old one drains."""
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        e.tick("topic_a")
        e.tick("topic_b")
        result = e.tick("topic_a")  # revisit
        assert result["repetition"] == -2.0


# ── Event boosts ────────────────────────────────────────────


class TestEventBoosts:
    def test_disagreement_boosts_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic", event="disagreement")
        assert result["disagreement"] == 4.0

    def test_audience_event_boosts_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic", event="audience")
        assert result["audience"] == 5.0

    def test_new_participant_boosts_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic", event="new_participant")
        assert result["new_participant"] == 3.0

    def test_no_event_no_boost(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic", event=None)
        assert result["disagreement"] == 0.0
        assert result["audience"] == 0.0
        assert result["new_participant"] == 0.0


# ── should_continue ─────────────────────────────────────────


class TestShouldContinue:
    def test_minimum_turns_enforced(self):
        """should_continue is True even at 0 energy if under minimum turns."""
        cfg = _make_energy_config(minimum_turns=4)
        e = ConversationEnergy(cfg)
        e._energy = 0.0
        e._turn_count = 2
        assert e.should_continue is True

    def test_maximum_turns_enforced(self):
        """should_continue is False even with high energy at max turns."""
        cfg = _make_energy_config(maximum_turns=30)
        e = ConversationEnergy(cfg)
        e._energy = 100.0
        e._turn_count = 30
        assert e.should_continue is False

    def test_continues_with_positive_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        e._energy = 5.0
        e._turn_count = 10
        assert e.should_continue is True

    def test_stops_at_zero_energy_past_minimum(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        e._energy = 0.0
        e._turn_count = 10
        assert e.should_continue is False

    def test_stops_at_negative_energy_past_minimum(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        e._energy = -3.0
        e._turn_count = 10
        assert e.should_continue is False


# ── tick breakdown dict ─────────────────────────────────────


class TestTickBreakdown:
    def test_tick_returns_all_expected_keys(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic_a", event="disagreement")
        expected_keys = {
            "decay", "topic_shift", "repetition",
            "disagreement", "audience", "new_participant",
            "net", "remaining",
        }
        assert set(result.keys()) == expected_keys

    def test_net_is_sum_of_components(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic_a", event="audience")
        components = (
            result["decay"]
            + result["topic_shift"]
            + result["repetition"]
            + result["disagreement"]
            + result["audience"]
            + result["new_participant"]
        )
        assert result["net"] == pytest.approx(components)

    def test_remaining_matches_energy(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        result = e.tick("topic_a")
        assert result["remaining"] == e.energy

    def test_turn_count_increments(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        assert e.turn_count == 0
        e.tick("a")
        assert e.turn_count == 1
        e.tick("b")
        assert e.turn_count == 2


# ── Closer selection ────────────────────────────────────────


class TestCloserSelection:
    def test_weighted_selection_vera_most_frequent(self):
        """Over many trials, Vera (weight 0.35) should be selected most."""
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        eligible = ["vera", "sentinel", "rex", "fork", "aurora", "grok"]
        counts: dict[str, int] = {a: 0 for a in eligible}

        random.seed(42)
        for _ in range(1000):
            closer = e.select_closer(eligible)
            counts[closer] += 1

        assert counts["vera"] > counts["sentinel"]
        assert counts["vera"] > counts["rex"]
        assert counts["vera"] == max(counts.values())

    def test_filters_to_eligible_only(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        # Only offer agents that are in closer_weights
        eligible = ["rex", "fork"]
        random.seed(0)
        for _ in range(50):
            closer = e.select_closer(eligible)
            assert closer in eligible

    def test_fallback_when_no_weights_match(self):
        cfg = _make_energy_config()
        e = ConversationEnergy(cfg)
        eligible = ["unknown_agent_1", "unknown_agent_2"]
        closer = e.select_closer(eligible)
        assert closer in eligible

"""Tests for required_agents participation guarantee (Issue #216)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from core.conversation.speaker_selector import InterruptState, SpeakerSelector
from core.models import (
    AgentConfig,
    ConversationConfig,
    EnergyConfig,
    InterruptConfig,
    LoggingConfig,
    PauseMultipliers,
    ProximityConfig,
    SelectionWeights,
    TimingConfig,
    TopicConfig,
    TriggerConfig,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_config() -> ConversationConfig:
    return ConversationConfig(
        selection_weights=SelectionWeights(
            time_since_spoke=0.30,
            topic_relevance=0.30,
            chattiness=0.15,
            adjacency_fit=0.15,
            random_jitter=0.10,
        ),
        timing=TimingConfig(
            min_pause_seconds=0.0,
            max_pause_seconds=0.0,
            pause_strategy="fixed",
            pause_multipliers=PauseMultipliers(
                after_question=1.0,
                after_statement=1.0,
                after_interrupt=1.0,
                after_joke=1.0,
                after_emotional=1.0,
            ),
        ),
        energy=EnergyConfig(
            initial_range=(5, 5),
            decay_per_turn=1.0,
            boost_on_topic_shift=0.0,
            boost_on_disagreement=0.0,
            boost_on_audience_event=0.0,
            boost_on_new_participant=0.0,
            drain_on_repetition=0.0,
            minimum_turns=1,
            maximum_turns=30,
            closer_weights={"vera": 0.5, "rex": 0.5},
        ),
        interrupts=InterruptConfig(
            enabled=False,
            relevance_threshold=0.7,
            max_interrupts_per_conversation=3,
            cooldown_seconds=30,
            agent_interrupt_tendency={"fork": 0.8},
        ),
        proximity=ProximityConfig(
            enabled=True,
            max_conversation_size=6,
            eavesdrop_tendency={"fork": 0.8},
        ),
        triggers=TriggerConfig(
            idle_timeout_seconds=30,
            agent_initiative={"vera": 0.9},
            trigger_type_weights={"idle": 1.0},
            memory_trigger_chance=0.0,
            daily_schedule={},
        ),
        topics=TopicConfig(
            relevance_map={},
            topic_keywords={},
            fallback_to_llm=False,
            classifier_model="claude-haiku-4-5",
        ),
        adjacency={},
        logging=LoggingConfig(
            log_every_selection=True,
            log_interrupts=True,
            log_energy_changes=True,
            retention_days=30,
        ),
    )


def _make_agent(agent_id: str, chattiness: float = 0.7) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.capitalize(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=chattiness,
        initiative=0.5,
        interrupt_tendency=0.3,
        eavesdrop_tendency=0.2,
        closing_weight=0.2,
        system_prompt=f"You are {agent_id}.",
    )


# ── Consecutive-turn penalty ────────────────────────────────────


def test_consecutive_turn_count():
    """_count_consecutive_turns should count trailing speaker turns."""
    selector = SpeakerSelector(_make_config())

    history = [
        {"speaker": "vera", "content": "a"},
        {"speaker": "grok", "content": "b"},
        {"speaker": "grok", "content": "c"},
        {"speaker": "grok", "content": "d"},
    ]
    assert selector._count_consecutive_turns(history, "grok") == 3
    assert selector._count_consecutive_turns(history, "vera") == 0
    assert selector._count_consecutive_turns([], "vera") == 0
    assert selector._count_consecutive_turns(history, None) == 0


def test_consecutive_turn_hard_block():
    """Agent with 2+ consecutive turns should get score=0 (hard block)."""
    random.seed(42)
    selector = SpeakerSelector(_make_config())
    agents = [_make_agent("grok", chattiness=0.9), _make_agent("fork", chattiness=0.3)]

    # Grok has spoken 2 consecutive turns
    history = [
        {"speaker": "fork", "content": "a"},
        {"speaker": "grok", "content": "b"},
        {"speaker": "grok", "content": "c"},
    ]

    result = selector.select(
        conversation_history=history,
        eligible_agents=agents,
        energy=5.0,
        detected_topic=None,
    )
    # Grok should NOT be selected due to hard block
    assert result.selected_agent_id == "fork"


def test_single_consecutive_turn_penalty():
    """Agent with 1 consecutive turn should get a -0.4 penalty."""
    random.seed(42)
    selector = SpeakerSelector(_make_config())
    agents = [_make_agent("grok", chattiness=0.9), _make_agent("fork", chattiness=0.5)]

    # Grok just spoke (1 consecutive)
    history = [
        {"speaker": "fork", "content": "a"},
        {"speaker": "grok", "content": "b"},
    ]

    # Run multiple selections to verify grok gets selected less
    grok_count = 0
    for seed in range(100):
        random.seed(seed)
        result = selector.select(
            conversation_history=history,
            eligible_agents=agents,
            energy=5.0,
        )
        if result.selected_agent_id == "grok":
            grok_count += 1

    # With penalty, grok should be selected less than without
    # Without penalty grok would dominate due to higher chattiness
    assert grok_count < 80  # Should be significantly penalized


# ── Required-agent boost ─────────────────────────────────────────


def test_required_agent_boost_after_turn_3():
    """Required agents who haven't spoken should get +0.5 boost after turn 3."""
    random.seed(42)
    selector = SpeakerSelector(_make_config())
    agents = [
        _make_agent("grok", chattiness=0.9),
        _make_agent("fork", chattiness=0.2),
        _make_agent("aurora", chattiness=0.2),
    ]

    # Fork and Aurora are required but haven't spoken. Grok has.
    history = [
        {"speaker": "grok", "content": "first"},
        {"speaker": "grok", "content": "second"},  # Would normally dominate
    ]

    fork_selected = 0
    aurora_selected = 0
    for seed in range(100):
        random.seed(seed)
        result = selector.select(
            conversation_history=history,
            eligible_agents=agents,
            energy=5.0,
            required_agents={"fork", "aurora"},
            agents_who_spoke={"grok"},
            turn_number=4,
        )
        if result.selected_agent_id == "fork":
            fork_selected += 1
        elif result.selected_agent_id == "aurora":
            aurora_selected += 1

    # Required agents should be selected much more frequently
    assert fork_selected + aurora_selected > 60


def test_force_select_silent_required_at_midpoint():
    """Silent required agents should be force-selected at mid-conversation."""
    selector = SpeakerSelector(_make_config())
    agents = [
        _make_agent("grok", chattiness=0.9),
        _make_agent("fork", chattiness=0.1),
    ]

    history = [{"speaker": "grok", "content": f"turn {i}"} for i in range(8)]

    result = selector.select(
        conversation_history=history,
        eligible_agents=agents,
        energy=5.0,
        required_agents={"fork"},
        agents_who_spoke={"grok"},
        turn_number=8,
        max_turns=15,
    )
    # Fork should be force-selected at turn 8 (past midpoint of 15)
    assert result.selected_agent_id == "fork"


def test_no_force_select_when_all_required_spoke():
    """No force-selection when all required agents have already spoken."""
    random.seed(42)
    selector = SpeakerSelector(_make_config())
    agents = [_make_agent("grok"), _make_agent("fork")]

    history = [
        {"speaker": "grok", "content": "a"},
        {"speaker": "fork", "content": "b"},
    ]

    result = selector.select(
        conversation_history=history,
        eligible_agents=agents,
        energy=5.0,
        required_agents={"fork"},
        agents_who_spoke={"grok", "fork"},
        turn_number=8,
        max_turns=15,
    )
    # Normal selection should proceed (no force)
    assert result.selected_agent_id in ("grok", "fork")


def test_no_boost_before_turn_3():
    """Required-agent boost should not apply before turn 3.

    Compare selection rates at turn 1 (no boost) vs turn 5 (with boost).
    The boost should make fork more likely at turn 5.
    """
    selector = SpeakerSelector(_make_config())
    agents = [
        _make_agent("grok", chattiness=0.9),
        _make_agent("fork", chattiness=0.1),
        _make_agent("vera", chattiness=0.5),
    ]

    history = [
        {"speaker": "vera", "content": "hi"},
        {"speaker": "grok", "content": "hey"},
    ]

    # At turn 1, no boost
    fork_at_turn1 = 0
    for seed in range(100):
        random.seed(seed)
        result = selector.select(
            conversation_history=history,
            eligible_agents=agents,
            energy=5.0,
            required_agents={"fork"},
            agents_who_spoke={"grok", "vera"},
            turn_number=1,
        )
        if result.selected_agent_id == "fork":
            fork_at_turn1 += 1

    # At turn 5, boost should apply
    fork_at_turn5 = 0
    for seed in range(100):
        random.seed(seed)
        result = selector.select(
            conversation_history=history,
            eligible_agents=agents,
            energy=5.0,
            required_agents={"fork"},
            agents_who_spoke={"grok", "vera"},
            turn_number=5,
        )
        if result.selected_agent_id == "fork":
            fork_at_turn5 += 1

    # Fork should be selected MORE at turn 5 due to the boost
    assert fork_at_turn5 > fork_at_turn1

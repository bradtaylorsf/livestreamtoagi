"""Shared test helpers for backend conversation engine tests.

These are plain functions (not pytest fixtures) because they accept arguments.
Import them explicitly in each test file:

    from tests.backend.conversation_helpers import make_conversation_config
    from tests.backend.conversation_helpers import make_agent_config
    from tests.backend.conversation_helpers import make_trigger_config
"""

from __future__ import annotations

from core.models import AgentConfig, ConversationConfig, TriggerConfig


def make_conversation_config(**overrides) -> ConversationConfig:
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


def make_agent_config(
    agent_id: str,
    *,
    chattiness: float = 0.5,
    initiative: float = 0.5,
    interrupt_tendency: float = 0.3,
    eavesdrop_tendency: float = 0.0,
) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.capitalize(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=chattiness,
        initiative=initiative,
        interrupt_tendency=interrupt_tendency,
        eavesdrop_tendency=eavesdrop_tendency,
    )


def make_trigger_config(**overrides) -> TriggerConfig:
    defaults = {
        "idle_timeout_seconds": 90,
        "agent_initiative": {
            "vera": 0.8,
            "pixel": 0.7,
            "grok": 0.6,
            "aurora": 0.5,
            "fork": 0.3,
            "rex": 0.2,
            "sentinel": 0.4,
        },
        "trigger_type_weights": {
            "idle": 0.25,
            "scheduled": 0.30,
            "environmental": 0.25,
            "memory": 0.10,
            "audience": 0.10,
        },
    }
    defaults.update(overrides)
    return TriggerConfig(**defaults)

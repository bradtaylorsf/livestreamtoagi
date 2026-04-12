"""Tests for cross-phase conversation repetition prevention (Issue #213)."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bootstrap import ConversationOptions, InfraServices, MemoryServices
from core.context_assembly import ContextAssembler
from core.conversation_engine import ConversationEngine
from core.models import AgentConfig


# ── Helpers ──────────────────────────────────────────────────────


def _make_agent(agent_id: str = "rex", system_prompt: str = "You are Rex.") -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        display_name=agent_id.capitalize(),
        model_conversation="claude-haiku-4-5",
        model_building="claude-sonnet-4-6",
        chattiness=0.7,
        initiative=0.7,
        interrupt_tendency=0.3,
        eavesdrop_tendency=0.3,
        closing_weight=0.2,
        system_prompt=system_prompt,
    )


def _make_assembler() -> ContextAssembler:
    registry = MagicMock()
    # Return agent with correct display name for any agent_id lookup
    registry.get_agent.side_effect = lambda aid: _make_agent(agent_id=aid)
    core_memory = AsyncMock()
    core_memory.get_core_memory = AsyncMock(return_value="")
    recall_memory = AsyncMock()
    recall_memory.retrieve_recall_memories = AsyncMock(return_value="")
    archival_memory = AsyncMock()
    token_counter = MagicMock()
    token_counter.count_tokens.return_value = 100
    return ContextAssembler(
        agent_registry=registry,
        core_memory=core_memory,
        recall_memory=recall_memory,
        archival_memory=archival_memory,
        token_counter=token_counter,
    )


# ── ContextAssembler: recent summaries injection ────────────────


@pytest.mark.asyncio
async def test_context_assembler_includes_recent_summaries():
    """Recent conversation summaries should appear in the system message."""
    assembler = _make_assembler()
    summaries = [
        "Conversation between vera, rex about project planning (5 turns).",
        "Conversation between grok, fork about code review (3 turns).",
    ]
    result = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=[],
        recent_conversation_summaries=summaries,
    )
    system_msg = result.messages[0]["content"]
    assert "What happened earlier today" in system_msg
    assert "project planning" in system_msg
    assert "code review" in system_msg


@pytest.mark.asyncio
async def test_context_assembler_no_summaries_when_none():
    """No recent summaries section when list is empty or None."""
    assembler = _make_assembler()
    result_none = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=[],
        recent_conversation_summaries=None,
    )
    result_empty = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=[],
        recent_conversation_summaries=[],
    )
    for result in (result_none, result_empty):
        assert "Recent Conversations" not in result.messages[0]["content"]


# ── ConversationEngine: repetition detection ────────────────────


def _make_engine_for_repetition(recent_outputs: list[str] | None = None) -> ConversationEngine:
    """Create a ConversationEngine with minimal mocks for repetition testing."""
    config_loader = MagicMock()
    config_loader.config = MagicMock()
    config_loader.config.topics = MagicMock()
    config_loader.config_hash = "test"
    agent_registry = MagicMock()
    event_bus = AsyncMock()
    llm_client = AsyncMock()
    management = AsyncMock()
    context_assembler = AsyncMock()
    conversation_repo = AsyncMock()
    archival_memory = AsyncMock()
    proximity = AsyncMock()
    trigger_system = MagicMock()
    selection_logger = AsyncMock()

    return ConversationEngine(
        infra=InfraServices(
            config_loader=config_loader,
            agent_registry=agent_registry,
            event_bus=event_bus,
            llm_client=llm_client,
            proximity=proximity,
            trigger_system=trigger_system,
            selection_logger=selection_logger,
        ),
        memory=MemoryServices(archival_memory=archival_memory),
        options=ConversationOptions(recent_outputs=recent_outputs),
        management=management,
        context_assembler=context_assembler,
        conversation_repo=conversation_repo,
    )


def test_is_repetitive_detects_similar_content():
    """Content >80% similar to recent output should be flagged."""
    engine = _make_engine_for_repetition(
        recent_outputs=["Hello everyone, welcome to the show! Let's get started."]
    )
    # Nearly identical
    assert engine._is_repetitive("Hello everyone, welcome to the show! Let's get started.")
    # Slightly different but still >80% similar
    assert engine._is_repetitive("Hello everyone, welcome to the show! Let's begin.")


def test_is_repetitive_allows_different_content():
    """Content that is sufficiently different should not be flagged."""
    engine = _make_engine_for_repetition(
        recent_outputs=["Hello everyone, welcome to the show! Let's get started."]
    )
    assert not engine._is_repetitive("Rex, did you finish the tilemap for the library?")


def test_is_repetitive_empty_history():
    """No recent outputs means nothing is repetitive."""
    engine = _make_engine_for_repetition(recent_outputs=[])
    assert not engine._is_repetitive("Anything goes here.")


def test_recent_outputs_tracked():
    """Recent outputs should be added to the deque."""
    engine = _make_engine_for_repetition()
    engine._recent_outputs.append("First output")
    engine._recent_outputs.append("Second output")
    assert len(engine._recent_outputs) == 2
    assert "First output" in engine._recent_outputs


def test_recent_outputs_maxlen():
    """Deque should cap at 50 items to cover full simulation length."""
    engine = _make_engine_for_repetition(
        recent_outputs=[f"output {i}" for i in range(50)]
    )
    engine._recent_outputs.append("output 50")
    assert len(engine._recent_outputs) == 50
    assert "output 0" not in engine._recent_outputs
    assert "output 50" in engine._recent_outputs


# ── PhaseRunner: conversation summaries buffer ──────────────────


def test_phase_runner_summaries_buffer():
    """PhaseRunner should maintain a rolling buffer of conversation summaries."""
    from core.simulation.phases import PhaseRunner

    runner = PhaseRunner(
        config_loader=MagicMock(),
        agent_registry=MagicMock(),
        event_bus=AsyncMock(),
        llm_client=AsyncMock(),
        management=AsyncMock(),
        context_assembler=AsyncMock(),
        conversation_repo=AsyncMock(),
        archival_memory=AsyncMock(),
        proximity=AsyncMock(),
        trigger_system=MagicMock(),
        selection_logger=AsyncMock(),
        reflection_manager=AsyncMock(),
        simulation_id=MagicMock(),
        agents=["vera", "rex"],
    )

    assert len(runner._conversation_summaries) == 0
    assert isinstance(runner._conversation_summaries, deque)
    assert runner._conversation_summaries.maxlen == 25
    assert isinstance(runner._recent_outputs, deque)
    assert runner._recent_outputs.maxlen == 50

    # Simulate adding summaries — deque(maxlen=25) handles trimming automatically
    for i in range(30):
        runner._conversation_summaries.append(f"Summary {i}")

    assert len(runner._conversation_summaries) == 25
    assert runner._conversation_summaries[0] == "Summary 5"


def test_is_repetitive_blocks_after_retry():
    """If content is repetitive after retry, _is_repetitive still returns True."""
    engine = _make_engine_for_repetition(
        recent_outputs=["We need to check the budget status and make sure everything is fine."]
    )
    # Simulates the retry also producing similar content
    retry_content = "We need to check the budget status and make sure everything is okay."
    assert engine._is_repetitive(retry_content)


# ── ContextAssembler: speaker labeling (identity bleed fix) ──────


@pytest.mark.asyncio
async def test_context_assembler_labels_buffer_messages():
    """Assistant messages in buffer should have [AgentName]: prefix."""
    assembler = _make_assembler()
    history = [
        {"role": "assistant", "speaker": "vera", "content": "We need to manage our budget."},
        {"role": "assistant", "speaker": "fork", "content": "I disagree with that approach."},
    ]
    result = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=history,
    )
    # Find assistant messages in the output
    assistant_msgs = [m for m in result.messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 2
    assert assistant_msgs[0]["content"].startswith("[Vera]:")
    assert assistant_msgs[1]["content"].startswith("[Fork]:")
    # name field should be set
    assert assistant_msgs[0]["name"] == "vera"
    assert assistant_msgs[1]["name"] == "fork"
    # speaker field should be removed
    assert "speaker" not in assistant_msgs[0]
    assert "speaker" not in assistant_msgs[1]


@pytest.mark.asyncio
async def test_context_assembler_identity_reinforcement():
    """An identity reinforcement message should appear before the hint."""
    assembler = _make_assembler()
    result = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=[],
        prompt_hint="idle",
    )
    # Find identity reinforcement message
    identity_msgs = [
        m for m in result.messages
        if m.get("role") == "user" and "You are Rex" in m.get("content", "")
    ]
    assert len(identity_msgs) == 1
    assert "Respond only as Rex" in identity_msgs[0]["content"]


@pytest.mark.asyncio
async def test_context_assembler_no_double_label():
    """Messages already labeled should not get double-labeled."""
    assembler = _make_assembler()
    history = [
        {"role": "assistant", "speaker": "vera", "content": "[Vera]: Already labeled."},
    ]
    result = await assembler.assemble_context(
        agent_id="rex",
        conversation_history=history,
    )
    assistant_msgs = [m for m in result.messages if m.get("role") == "assistant"]
    assert assistant_msgs[0]["content"] == "[Vera]: Already labeled."


def test_engine_conversation_summary_property():
    """Engine should expose last_conversation_summary and recent_outputs."""
    engine = _make_engine_for_repetition(recent_outputs=["a", "b"])
    assert engine.last_conversation_summary is None
    assert engine.recent_outputs == ["a", "b"]

    engine._last_conversation_summary = "Test summary"
    assert engine.last_conversation_summary == "Test summary"

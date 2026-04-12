"""Tests for the main ConversationEngine orchestrator."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.conversation_engine import ConversationEngine
from core.event_bus import EventType
from core.models import (
    AgentConfig,
    AgentStatus,
    ContentReviewResult,
    Conversation,
    ConversationConfig,
    EnergyConfig,
    InterruptConfig,
    JournalEntry,
    JournalEntryCreate,
    LLMResponse,
    LoggingConfig,
    PauseMultipliers,
    ProximityConfig,
    SelectionResult,
    SelectionWeights,
    TimingConfig,
    ToolCall,
    TopicConfig,
    Transcript,
    TriggerConfig,
)

# ── Test config factories ──────────────────────────────────────


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
            relevance_map={"rex": {"code": 0.9}},
            topic_keywords={"code": ["code", "bug"]},
            fallback_to_llm=False,
            classifier_model="claude-haiku-4-5",
        ),
        adjacency={"vera": {"rex": 0.8}},
        logging=LoggingConfig(
            log_every_selection=True,
            log_interrupts=True,
            log_energy_changes=True,
            retention_days=30,
        ),
    )


def _make_agent(
    agent_id: str = "rex",
    status: AgentStatus = AgentStatus.active,
    **overrides: object,
) -> AgentConfig:
    defaults = {
        "id": agent_id,
        "display_name": agent_id.capitalize(),
        "model_conversation": "claude-haiku-4-5",
        "model_building": "claude-sonnet-4-6",
        "chattiness": 0.7,
        "initiative": 0.5,
        "interrupt_tendency": 0.3,
        "eavesdrop_tendency": 0.2,
        "closing_weight": 0.3,
        "status": status,
        "system_prompt": f"You are {agent_id}.",
        "behaviors": {},
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _make_llm_response(content: str = "Hello, everyone!") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
    )


def _make_selection_result(agent_id: str = "rex", **overrides: object) -> SelectionResult:
    defaults = {
        "selected_agent_id": agent_id,
        "scores": {agent_id: 0.8},
        "score_breakdown": {agent_id: {"time_since_spoke": 0.3, "topic_relevance": 0.3}},
        "eligible_agents": [agent_id],
        "was_interrupt": False,
        "interrupt_attempts": [],
    }
    defaults.update(overrides)
    return SelectionResult(**defaults)


def _make_conversation_db_record(**overrides: object) -> Conversation:
    defaults = {
        "id": uuid.uuid4(),
        "trigger_type": "idle",
        "trigger_details": {"type": "idle"},
        "initial_energy": 0.8,
        "participating_agents": ["rex", "vera"],
        "location": "town_square",
        "config_hash": "abc123",
    }
    defaults.update(overrides)
    return Conversation(**defaults)


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture()
def config() -> ConversationConfig:
    return _make_config()


@pytest.fixture()
def agents() -> list[AgentConfig]:
    return [
        _make_agent("rex"),
        _make_agent("vera"),
        _make_agent("fork"),
    ]


@pytest.fixture()
def mock_config_loader(config: ConversationConfig) -> MagicMock:
    loader = MagicMock()
    loader.config = config
    loader.config_hash = "test-hash-123"
    return loader


@pytest.fixture()
def mock_agent_registry(agents: list[AgentConfig]) -> MagicMock:
    registry = MagicMock()
    registry.get_all_agents.return_value = agents
    registry.get_active_agents.return_value = agents
    registry.get_agent.side_effect = lambda aid: next((a for a in agents if a.id == aid), None)
    return registry


@pytest.fixture()
def mock_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.emit = AsyncMock(return_value={"event_id": "test", "event_type": "test"})
    bus.on = MagicMock()
    return bus


@pytest.fixture()
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=_make_llm_response())
    llm.close = AsyncMock()
    return llm


@pytest.fixture()
def mock_management() -> MagicMock:
    management = MagicMock()
    management.review = AsyncMock(
        return_value=ContentReviewResult(approved=True, reason="OK", severity=1)
    )
    management.intervene = AsyncMock()
    management.is_muted = AsyncMock(return_value=False)
    return management


@pytest.fixture()
def mock_context_assembler() -> MagicMock:
    from core.context_assembly import ContextResult

    assembler = MagicMock()
    assembler.assemble_context = AsyncMock(
        return_value=ContextResult(
            messages=[{"role": "system", "content": "You are an agent."}],
            sections_included={},
            total_tokens=10,
        )
    )
    return assembler


@pytest.fixture()
def mock_conversation_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock(return_value=_make_conversation_db_record())
    repo.close = AsyncMock(return_value=_make_conversation_db_record())
    repo.log_selection = AsyncMock()
    repo.log_interrupt = AsyncMock()
    repo.log_energy = AsyncMock()
    return repo


@pytest.fixture()
def mock_archival_memory() -> MagicMock:
    archival = MagicMock()
    archival.store_transcript = AsyncMock(
        return_value=Transcript(
            id=1, event_type="idle", participants=["rex"], content="test", token_count=10
        )
    )
    return archival


@pytest.fixture()
def mock_proximity() -> MagicMock:
    proximity = MagicMock()
    proximity.get_group = AsyncMock(return_value=["rex", "vera", "fork"])
    proximity.get_eligible_speakers = AsyncMock()
    proximity.check_eavesdroppers = AsyncMock(return_value=[])
    proximity.update_location = AsyncMock(return_value=None)
    # config setter
    proximity.config = MagicMock()
    return proximity


@pytest.fixture()
def mock_trigger_system() -> MagicMock:
    triggers = MagicMock()
    triggers.check = AsyncMock(return_value=None)
    triggers.notify_speech = MagicMock()
    triggers.reset = MagicMock()
    return triggers


@pytest.fixture()
def mock_selection_logger() -> MagicMock:
    logger = MagicMock()
    logger.log_selection = AsyncMock()
    logger.log_interrupt = AsyncMock()
    logger.log_energy = AsyncMock()
    logger.config = MagicMock()
    return logger


@pytest.fixture()
def mock_compactor() -> MagicMock:
    compactor = MagicMock()
    result = MagicMock()
    result.transcript.id = 1
    compactor.compact_interaction = AsyncMock(return_value=result)
    compactor.compact_recall_only = AsyncMock(return_value=MagicMock())
    return compactor


@pytest.fixture()
def mock_memory_repo() -> MagicMock:
    repo = MagicMock()
    repo.create_journal_entry = AsyncMock(
        return_value=JournalEntry(
            id=1,
            agent_id="rex",
            reflection_type="conversation",
            content="test",
            token_count=5,
        )
    )
    return repo


@pytest.fixture()
def engine(
    mock_config_loader: MagicMock,
    mock_agent_registry: MagicMock,
    mock_event_bus: MagicMock,
    mock_llm: MagicMock,
    mock_management: MagicMock,
    mock_context_assembler: MagicMock,
    mock_conversation_repo: MagicMock,
    mock_archival_memory: MagicMock,
    mock_proximity: MagicMock,
    mock_trigger_system: MagicMock,
    mock_selection_logger: MagicMock,
    mock_compactor: MagicMock,
    mock_memory_repo: MagicMock,
    agents: list[AgentConfig],
) -> ConversationEngine:
    # Make proximity return eligible agents from the fixture
    mock_proximity.get_eligible_speakers = AsyncMock(return_value=agents)

    return ConversationEngine(
        config_loader=mock_config_loader,
        agent_registry=mock_agent_registry,
        event_bus=mock_event_bus,
        llm_client=mock_llm,
        management=mock_management,
        context_assembler=mock_context_assembler,
        conversation_repo=mock_conversation_repo,
        archival_memory=mock_archival_memory,
        proximity=mock_proximity,
        trigger_system=mock_trigger_system,
        selection_logger=mock_selection_logger,
        compactor=mock_compactor,
        memory_repo=mock_memory_repo,
        speed_multiplier=0,  # No delays in tests
    )


# ── Test: Trigger detection starts new conversation ────────────


class TestTriggerStartsConversation:
    async def test_trigger_creates_conversation(
        self, engine: ConversationEngine, mock_conversation_repo: MagicMock
    ) -> None:
        """When a trigger fires, a new conversation is created in the DB."""
        trigger = {"type": "idle", "reason": "Nobody talking", "location": "town_square"}
        await engine._start_conversation(trigger)

        assert engine.active_conversation is not None
        mock_conversation_repo.create.assert_awaited_once()

    async def test_trigger_emits_first_speak_event(
        self, engine: ConversationEngine, mock_event_bus: MagicMock
    ) -> None:
        """Starting a conversation emits an agent_speak event."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        mock_event_bus.emit.assert_awaited()
        call_args = mock_event_bus.emit.call_args
        assert call_args[0][0] == EventType.AGENT_SPEAK.value
        payload = call_args[0][1]
        assert "dialogue" in payload
        assert "actions" in payload
        assert isinstance(payload["actions"], list)

    async def test_trigger_notifies_speech(
        self, engine: ConversationEngine, mock_trigger_system: MagicMock
    ) -> None:
        """Starting a conversation notifies the trigger system of speech."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        mock_trigger_system.notify_speech.assert_called_once()

    async def test_idle_trigger_uses_idle_hint(
        self, engine: ConversationEngine, mock_context_assembler: MagicMock
    ) -> None:
        """Idle trigger maps to 'idle' prompt hint."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        call_kwargs = mock_context_assembler.assemble_context.call_args
        assert call_kwargs[1]["prompt_hint"] == "idle"


# ── Test: Conversation flow (select -> generate -> emit -> record)


class TestConversationFlow:
    async def test_continue_conversation_full_cycle(
        self,
        engine: ConversationEngine,
        mock_event_bus: MagicMock,
        mock_selection_logger: MagicMock,
    ) -> None:
        """Continue conversation: selects speaker, generates turn, emits event, logs."""
        # Start a conversation first
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        mock_event_bus.emit.reset_mock()

        # Patch selector to return a known result
        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            await engine._continue_conversation()

        # Emitted speak event
        mock_event_bus.emit.assert_awaited()
        call_args = mock_event_bus.emit.call_args
        assert call_args[0][0] == EventType.AGENT_SPEAK.value
        payload = call_args[0][1]
        assert "dialogue" in payload
        assert "actions" in payload
        assert isinstance(payload["actions"], list)

        # Logged selection and energy
        mock_selection_logger.log_selection.assert_awaited()
        mock_selection_logger.log_energy.assert_awaited()

    async def test_history_accumulates(
        self, engine: ConversationEngine
    ) -> None:
        """Each turn adds a message to the conversation history."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        assert len(engine.active_conversation.history) == 1  # opening line

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            await engine._continue_conversation()

        assert len(engine.active_conversation.history) == 2


# ── Test: Energy depletion ends conversation with closer ───────


class TestEnergyDepletion:
    async def test_energy_depletion_ends_conversation(
        self,
        engine: ConversationEngine,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
    ) -> None:
        """When energy is depleted, end_conversation is called."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        # Drain energy manually
        conv = engine.active_conversation
        conv.energy._energy = 0.0
        conv.energy._turn_count = conv.energy._config.minimum_turns

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            should_continue = await engine._continue_conversation()

        assert should_continue is False

        # Now end the conversation
        await engine._end_conversation()
        assert engine.active_conversation is None
        mock_conversation_repo.close.assert_awaited_once()

    async def test_end_conversation_generates_closing_line(
        self,
        engine: ConversationEngine,
        mock_event_bus: MagicMock,
    ) -> None:
        """End conversation generates a closing line and emits it."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        mock_event_bus.emit.reset_mock()
        await engine._end_conversation()

        # Should have emitted at least one more speak event (closing line)
        emit_calls = mock_event_bus.emit.call_args_list
        speak_events = [
            c for c in emit_calls if c[0][0] == EventType.AGENT_SPEAK.value
        ]
        assert len(speak_events) >= 1
        # The closing event should have is_closing=True
        last_speak_data = speak_events[-1][0][1]
        assert last_speak_data.get("is_closing") is True
        assert "dialogue" in last_speak_data
        assert "actions" in last_speak_data
        assert isinstance(last_speak_data["actions"], list)

    async def test_end_conversation_resets_triggers(
        self,
        engine: ConversationEngine,
        mock_trigger_system: MagicMock,
    ) -> None:
        """End conversation resets the trigger system."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        await engine._end_conversation()

        mock_trigger_system.reset.assert_called_once()


# ── Test: Post-conversation memory creation ──────────────────────


class TestPostConversationMemories:
    async def test_end_conversation_calls_compactor_per_participant(
        self,
        engine: ConversationEngine,
        mock_compactor: MagicMock,
    ) -> None:
        """End conversation stores transcript once, creates recall per participant."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        await engine._end_conversation()

        num_participants = len(engine._agents.get_all_agents())

        # compact_interaction called ONCE (stores transcript + first agent's recall)
        assert mock_compactor.compact_interaction.await_count == 1
        # compact_recall_only called for remaining participants
        assert mock_compactor.compact_recall_only.await_count == num_participants - 1

        # Verify event_type and participants are passed
        call_kwargs = mock_compactor.compact_interaction.call_args_list[0][1]
        assert call_kwargs["event_type"] == "idle"
        assert isinstance(call_kwargs["participants"], list)
        assert len(call_kwargs["participants"]) > 0
        assert call_kwargs["conversation_id"] is not None

    async def test_end_conversation_creates_journal_entries(
        self,
        engine: ConversationEngine,
        mock_memory_repo: MagicMock,
    ) -> None:
        """End conversation creates journal entry for each participant."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        await engine._end_conversation()

        assert mock_memory_repo.create_journal_entry.await_count == len(
            engine._agents.get_all_agents()
        )
        # Verify journal entry uses 'conversation' reflection_type
        call_args = mock_memory_repo.create_journal_entry.call_args_list[0]
        entry = call_args[0][0]
        assert isinstance(entry, JournalEntryCreate)
        assert entry.reflection_type == "conversation"

    async def test_compaction_failure_does_not_break_end(
        self,
        engine: ConversationEngine,
        mock_compactor: MagicMock,
        mock_conversation_repo: MagicMock,
    ) -> None:
        """If compaction fails, conversation still closes normally."""
        mock_compactor.compact_interaction.side_effect = RuntimeError("LLM down")

        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        await engine._end_conversation()

        # Conversation should still be closed
        assert engine.active_conversation is None
        mock_conversation_repo.close.assert_awaited_once()

    async def test_no_compactor_still_stores_transcript(
        self,
        mock_config_loader: MagicMock,
        mock_agent_registry: MagicMock,
        mock_event_bus: MagicMock,
        mock_llm: MagicMock,
        mock_management: MagicMock,
        mock_context_assembler: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
        mock_proximity: MagicMock,
        mock_trigger_system: MagicMock,
        mock_selection_logger: MagicMock,
        agents: list[AgentConfig],
    ) -> None:
        """Engine without compactor falls back to direct archival storage."""
        mock_proximity.get_eligible_speakers = AsyncMock(return_value=agents)
        engine_no_compactor = ConversationEngine(
            config_loader=mock_config_loader,
            agent_registry=mock_agent_registry,
            event_bus=mock_event_bus,
            llm_client=mock_llm,
            management=mock_management,
            context_assembler=mock_context_assembler,
            conversation_repo=mock_conversation_repo,
            archival_memory=mock_archival_memory,
            proximity=mock_proximity,
            trigger_system=mock_trigger_system,
            selection_logger=mock_selection_logger,
            speed_multiplier=0,
        )

        trigger = {"type": "idle", "location": "town_square"}
        await engine_no_compactor._start_conversation(trigger)
        await engine_no_compactor._end_conversation()

        # Should complete without error and still store transcript
        assert engine_no_compactor.active_conversation is None
        mock_conversation_repo.close.assert_awaited()
        mock_archival_memory.store_transcript.assert_awaited()


# ── Test: Muted agent is skipped ───────────────────────────────


class TestMutedAgent:
    async def test_muted_agent_excluded_from_eligible(
        self,
        engine: ConversationEngine,
        mock_proximity: MagicMock,
    ) -> None:
        """Muted agents are filtered out of eligible speakers."""
        muted_agent = _make_agent("rex", status=AgentStatus.muted)
        active_agent = _make_agent("vera")
        mock_proximity.get_eligible_speakers = AsyncMock(
            return_value=[muted_agent, active_agent]
        )

        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        conv = engine.active_conversation
        assert conv is not None
        # Rex should be excluded since muted
        assert "rex" not in conv.participants
        assert "vera" in conv.participants

    async def test_muted_agent_skipped_in_continue(
        self,
        engine: ConversationEngine,
        mock_agent_registry: MagicMock,
    ) -> None:
        """During continue, muted agents don't appear in the eligible list passed to selector."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        # Mute rex mid-conversation
        muted_rex = _make_agent("rex", status=AgentStatus.muted)
        vera = _make_agent("vera")
        fork = _make_agent("fork")
        mock_agent_registry.get_all_agents.return_value = [muted_rex, vera, fork]

        result = _make_selection_result("vera")
        with patch.object(engine._selector, "select", return_value=result) as mock_select:
            await engine._continue_conversation()

        # The selector should only receive non-muted agents
        call_kwargs = mock_select.call_args
        kw = call_kwargs[1] or {}
        eligible = (
            kw["eligible_agents"]
            if "eligible_agents" in kw
            else call_kwargs[0][1]
        )
        agent_ids = [a.id for a in eligible]
        assert "rex" not in agent_ids


# ── Test: Management rejection triggers replacement ──────────────


class TestManagementRejection:
    async def test_management_rejection_retries(
        self,
        engine: ConversationEngine,
        mock_management: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        """When Management rejects content, engine retries with new LLM call."""
        # First call rejected, second approved
        mock_management.review = AsyncMock(
            side_effect=[
                ContentReviewResult(approved=False, reason="Too edgy", severity=2),
                ContentReviewResult(approved=True, reason="OK", severity=1),
            ]
        )
        mock_llm.complete = AsyncMock(
            side_effect=[
                _make_llm_response("Edgy content"),
                _make_llm_response("Nice content"),
            ]
        )

        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        # LLM called twice (original + retry)
        assert mock_llm.complete.await_count == 2
        # Management intervene called for the rejection
        mock_management.intervene.assert_awaited_once()

    async def test_management_high_severity_returns_replacement(
        self,
        engine: ConversationEngine,
        mock_management: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        """High severity (>=4) returns replacement instead of retrying."""
        mock_management.review = AsyncMock(
            return_value=ContentReviewResult(
                approved=False,
                reason="Dangerous content",
                severity=4,
                replacement="Content has been redacted per Section 4.2(b).",
            )
        )

        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        # Only 1 LLM call (no retry after severity 4)
        assert mock_llm.complete.await_count == 1
        mock_management.intervene.assert_awaited_once()


# ── Test: Eavesdropper joining emits agent_move event ──────────


class TestEavesdropper:
    async def test_eavesdropper_joins_conversation(
        self,
        engine: ConversationEngine,
        mock_proximity: MagicMock,
        mock_event_bus: MagicMock,
    ) -> None:
        """Eavesdropper joining adds them to participants and emits agent_move."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        mock_event_bus.emit.reset_mock()

        # Simulate eavesdropper joining
        mock_proximity.check_eavesdroppers = AsyncMock(return_value=["grok"])

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            await engine._continue_conversation()

        # Grok should be added
        assert "grok" in engine.active_conversation.participants

        # Should have emitted an agent_move event for grok
        move_events = [
            c for c in mock_event_bus.emit.call_args_list
            if c[0][0] == EventType.AGENT_MOVE.value
        ]
        assert len(move_events) == 1
        assert move_events[0][0][1]["agent_id"] == "grok"


# ── Test: Run loop behavior ────────────────────────────────────


class TestRunLoop:
    async def test_run_checks_triggers_when_idle(
        self,
        engine: ConversationEngine,
        mock_trigger_system: MagicMock,
    ) -> None:
        """The run loop checks triggers when no active conversation."""
        call_count = 0

        async def _check_then_stop() -> dict | None:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                engine.stop()
            return None

        mock_trigger_system.check = AsyncMock(side_effect=_check_then_stop)
        await engine.run()

        assert call_count >= 3
        assert not engine.is_running

    async def test_stop_method_terminates_loop(
        self, engine: ConversationEngine, mock_trigger_system: MagicMock
    ) -> None:
        """Calling stop() terminates the run loop."""
        async def _stop_after_one() -> dict | None:
            engine.stop()
            return None

        mock_trigger_system.check = AsyncMock(side_effect=_stop_after_one)
        await engine.run()
        assert not engine.is_running


# ── Test: Config hot-reload ────────────────────────────────────


class TestConfigReload:
    def test_on_config_reloaded_updates_subsystems(
        self, engine: ConversationEngine, config: ConversationConfig
    ) -> None:
        """Config reload updates selector and other subsystem configs."""
        engine.on_config_reloaded(config)
        assert engine._selector.config is config


# ── Test: _generate_turn error handling ────────────────────────


class TestGenerateTurn:
    async def test_empty_response_retries(
        self,
        engine: ConversationEngine,
        mock_llm: MagicMock,
        mock_management: MagicMock,
    ) -> None:
        """Empty LLM response triggers retry."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                _make_llm_response(""),  # empty
                _make_llm_response("Real content"),
            ]
        )

        agent = _make_agent("rex")
        content = await engine._generate_turn(agent, prompt_hint="idle")

        assert content == "Real content"
        assert mock_llm.complete.await_count == 2

    async def test_all_retries_exhausted_returns_none(
        self,
        engine: ConversationEngine,
        mock_llm: MagicMock,
    ) -> None:
        """All retries exhausted returns None."""
        mock_llm.complete = AsyncMock(side_effect=ConnectionError("Network error"))

        agent = _make_agent("rex")
        content = await engine._generate_turn(agent)

        assert content is None
        assert mock_llm.complete.await_count == 3  # MAX_GENERATE_RETRIES

    async def test_connection_error_uses_backoff(
        self,
        engine: ConversationEngine,
        mock_llm: MagicMock,
    ) -> None:
        """Connection errors use exponential backoff (speed=0 so no actual sleep)."""
        mock_llm.complete = AsyncMock(
            side_effect=[
                ConnectionError("fail"),
                ConnectionError("fail"),
                _make_llm_response("Got it!"),
            ]
        )

        agent = _make_agent("rex")
        content = await engine._generate_turn(agent)

        assert content == "Got it!"


# ── Test: No eligible agents skips trigger ─────────────────────


class TestNoEligibleAgents:
    async def test_no_eligible_agents_aborts(
        self,
        engine: ConversationEngine,
        mock_proximity: MagicMock,
    ) -> None:
        """If no eligible agents, conversation is not started."""
        mock_proximity.get_eligible_speakers = AsyncMock(return_value=[])
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        assert engine.active_conversation is None


# ── Integration test: 10 conversation cycles ───────────────────


class TestIntegration:
    async def test_10_conversation_cycles(
        self,
        engine: ConversationEngine,
        mock_trigger_system: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
    ) -> None:
        """Run 10 complete conversation cycles with mock LLM."""
        cycle_count = 0

        async def _trigger_every_time() -> dict | None:
            nonlocal cycle_count
            if cycle_count >= 10:
                engine.stop()
                return None
            cycle_count += 1
            return {"type": "idle", "location": "town_square"}

        mock_trigger_system.check = AsyncMock(side_effect=_trigger_every_time)

        # Make energy drain fast (1 turn minimum, low energy)
        engine._config_loader.config = _make_config()

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            await engine.run()

        # Should have created and closed 10 conversations
        assert mock_conversation_repo.create.await_count == 10
        assert mock_conversation_repo.close.await_count == 10

    async def test_full_conversation_lifecycle(
        self,
        engine: ConversationEngine,
        mock_conversation_repo: MagicMock,
    ) -> None:
        """A conversation goes through start -> continue -> end lifecycle."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)
        assert engine.active_conversation is not None

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            # Run turns until energy is depleted
            for _ in range(10):
                should_continue = await engine._continue_conversation()
                if not should_continue:
                    break

        await engine._end_conversation()
        assert engine.active_conversation is None
        mock_conversation_repo.close.assert_awaited_once()


# ── Test: Speed multiplier ─────────────────────────────────────


class TestSpeedMultiplier:
    async def test_speed_zero_skips_sleep(self, engine: ConversationEngine) -> None:
        """speed_multiplier=0 means no sleep at all."""
        # engine already has speed_multiplier=0
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await engine._sleep(5.0)
            mock_sleep.assert_not_awaited()

    async def test_speed_multiplier_scales_pause(self) -> None:
        """speed_multiplier adjusts pause duration."""
        config = _make_config()
        loader = MagicMock()
        loader.config = config
        loader.config_hash = "test"

        engine = ConversationEngine(
            config_loader=loader,
            agent_registry=MagicMock(),
            event_bus=MagicMock(),
            llm_client=MagicMock(),
            management=MagicMock(),
            context_assembler=MagicMock(),
            conversation_repo=MagicMock(),
            archival_memory=MagicMock(),
            proximity=MagicMock(),
            trigger_system=MagicMock(),
            selection_logger=MagicMock(),
            speed_multiplier=0.5,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await engine._sleep(2.0)
            mock_sleep.assert_awaited_once_with(1.0)


# ── Test: Tool support in _generate_turn ─────────────────────────


def _make_llm_response_with_tool_calls(
    content: str = "",
    tool_calls: list[ToolCall] | None = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="claude-haiku-4-5",
        input_tokens=100,
        output_tokens=20,
        estimated_cost=Decimal("0.0001"),
        latency_ms=200,
        openrouter_id="test-id",
        tool_calls=tool_calls or [],
    )


def _make_mock_services() -> MagicMock:
    svc = MagicMock()
    svc.core_memory = MagicMock()
    svc.recall_memory = MagicMock()
    svc.archival_memory = MagicMock()
    svc.economy_manager = None  # Prevent await errors on MagicMock
    svc.agent_state_manager = AsyncMock()  # Must be AsyncMock for await calls
    svc.goal_manager = None  # Prevent await errors on MagicMock
    svc.alliance_manager = None  # Prevent await errors on MagicMock
    svc.shared_working_state = None  # Prevent await errors on MagicMock
    svc.memory_repo = None  # Prevent await errors on MagicMock
    return svc


class TestToolSupport:
    async def test_no_services_means_no_tools(
        self,
        engine: ConversationEngine,
        mock_llm: MagicMock,
    ) -> None:
        """Without services, LLM is called without tools param."""
        agent = _make_agent("rex")
        await engine._generate_turn(agent, prompt_hint="idle")

        call_kwargs = mock_llm.complete.call_args[1]
        assert call_kwargs.get("tools") is None

    async def test_tools_passed_to_llm_when_services_provided(
        self,
        mock_config_loader: MagicMock,
        mock_agent_registry: MagicMock,
        mock_event_bus: MagicMock,
        mock_llm: MagicMock,
        mock_management: MagicMock,
        mock_context_assembler: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
        mock_proximity: MagicMock,
        mock_trigger_system: MagicMock,
        mock_selection_logger: MagicMock,
        agents: list[AgentConfig],
    ) -> None:
        """When services are provided, tools are passed to llm.complete()."""
        mock_services = _make_mock_services()

        engine_with_tools = ConversationEngine(
            config_loader=mock_config_loader,
            agent_registry=mock_agent_registry,
            event_bus=mock_event_bus,
            llm_client=mock_llm,
            management=mock_management,
            context_assembler=mock_context_assembler,
            conversation_repo=mock_conversation_repo,
            archival_memory=mock_archival_memory,
            proximity=mock_proximity,
            trigger_system=mock_trigger_system,
            selection_logger=mock_selection_logger,
            speed_multiplier=0,
            services=mock_services,
        )

        mock_tool = MagicMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search the web"
        mock_tool.parameters = {"query": {"type": "string", "description": "Query"}}

        with patch(
            "core.conversation_engine.build_agent_tools",
            return_value={"web_search": mock_tool},
        ):
            agent = _make_agent("rex")
            await engine_with_tools._generate_turn(agent, prompt_hint="idle")

        call_kwargs = mock_llm.complete.call_args[1]
        assert call_kwargs.get("tools") is not None
        assert len(call_kwargs["tools"]) == 1
        assert call_kwargs["tools"][0]["function"]["name"] == "web_search"

    async def test_tool_call_loop_executes_and_re_calls_llm(
        self,
        mock_config_loader: MagicMock,
        mock_agent_registry: MagicMock,
        mock_event_bus: MagicMock,
        mock_llm: MagicMock,
        mock_management: MagicMock,
        mock_context_assembler: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
        mock_proximity: MagicMock,
        mock_trigger_system: MagicMock,
        mock_selection_logger: MagicMock,
        agents: list[AgentConfig],
    ) -> None:
        """When LLM returns tool_calls, engine executes them and re-calls LLM."""
        mock_services = _make_mock_services()

        engine_with_tools = ConversationEngine(
            config_loader=mock_config_loader,
            agent_registry=mock_agent_registry,
            event_bus=mock_event_bus,
            llm_client=mock_llm,
            management=mock_management,
            context_assembler=mock_context_assembler,
            conversation_repo=mock_conversation_repo,
            archival_memory=mock_archival_memory,
            proximity=mock_proximity,
            trigger_system=mock_trigger_system,
            selection_logger=mock_selection_logger,
            speed_multiplier=0,
            services=mock_services,
        )

        # First LLM call returns a tool call, second returns text
        tool_call = ToolCall(id="call_123", name="web_search", arguments={"query": "test"})
        mock_llm.complete = AsyncMock(
            side_effect=[
                _make_llm_response_with_tool_calls("", [tool_call]),
                _make_llm_response("Here are the search results!"),
            ]
        )

        mock_tool = MagicMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search the web"
        mock_tool.parameters = {"query": {"type": "string", "description": "Query"}}
        mock_tool.run = AsyncMock(return_value={"status": "ok", "results": ["r1"]})

        with patch(
            "core.conversation_engine.build_agent_tools",
            return_value={"web_search": mock_tool},
        ):
            agent = _make_agent("rex")
            content = await engine_with_tools._generate_turn(agent, prompt_hint="idle")

        assert content == "Here are the search results!"
        assert mock_llm.complete.await_count == 2
        mock_tool.run.assert_awaited_once()

    async def test_tool_call_accumulates_token_costs(
        self,
        mock_config_loader: MagicMock,
        mock_agent_registry: MagicMock,
        mock_event_bus: MagicMock,
        mock_llm: MagicMock,
        mock_management: MagicMock,
        mock_context_assembler: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
        mock_proximity: MagicMock,
        mock_trigger_system: MagicMock,
        mock_selection_logger: MagicMock,
        agents: list[AgentConfig],
    ) -> None:
        """Token/cost metadata is accumulated across tool rounds."""
        mock_services = _make_mock_services()

        engine_with_tools = ConversationEngine(
            config_loader=mock_config_loader,
            agent_registry=mock_agent_registry,
            event_bus=mock_event_bus,
            llm_client=mock_llm,
            management=mock_management,
            context_assembler=mock_context_assembler,
            conversation_repo=mock_conversation_repo,
            archival_memory=mock_archival_memory,
            proximity=mock_proximity,
            trigger_system=mock_trigger_system,
            selection_logger=mock_selection_logger,
            speed_multiplier=0,
            services=mock_services,
        )

        tool_call = ToolCall(id="call_456", name="test_tool", arguments={})
        resp1 = LLMResponse(
            content="",
            model="claude-haiku-4-5",
            input_tokens=100,
            output_tokens=20,
            estimated_cost=Decimal("0.0001"),
            latency_ms=200,
            tool_calls=[tool_call],
        )
        resp2 = LLMResponse(
            content="Final answer",
            model="claude-haiku-4-5",
            input_tokens=150,
            output_tokens=30,
            estimated_cost=Decimal("0.0002"),
            latency_ms=300,
        )
        mock_llm.complete = AsyncMock(side_effect=[resp1, resp2])

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "Test"
        mock_tool.parameters = {}
        mock_tool.run = AsyncMock(return_value={"status": "ok"})

        with patch(
            "core.conversation_engine.build_agent_tools",
            return_value={"test_tool": mock_tool},
        ):
            agent = _make_agent("rex")
            await engine_with_tools._generate_turn(agent, prompt_hint="idle")

        meta = engine_with_tools._last_llm_meta
        assert meta["input_tokens"] == 250  # 100 + 150
        assert meta["output_tokens"] == 50  # 20 + 30
        assert meta["cost"] == pytest.approx(0.0003)
        assert meta["latency_ms"] == 500  # 200 + 300

    async def test_tool_cache_reuses_tools(
        self,
        mock_config_loader: MagicMock,
        mock_agent_registry: MagicMock,
        mock_event_bus: MagicMock,
        mock_llm: MagicMock,
        mock_management: MagicMock,
        mock_context_assembler: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
        mock_proximity: MagicMock,
        mock_trigger_system: MagicMock,
        mock_selection_logger: MagicMock,
        agents: list[AgentConfig],
    ) -> None:
        """Tool registries are cached per agent — build_agent_tools called once."""
        mock_services = _make_mock_services()

        engine_with_tools = ConversationEngine(
            config_loader=mock_config_loader,
            agent_registry=mock_agent_registry,
            event_bus=mock_event_bus,
            llm_client=mock_llm,
            management=mock_management,
            context_assembler=mock_context_assembler,
            conversation_repo=mock_conversation_repo,
            archival_memory=mock_archival_memory,
            proximity=mock_proximity,
            trigger_system=mock_trigger_system,
            selection_logger=mock_selection_logger,
            speed_multiplier=0,
            services=mock_services,
        )

        with patch(
            "core.conversation_engine.build_agent_tools",
            return_value={},
        ) as mock_build:
            agent = _make_agent("rex")
            await engine_with_tools._generate_turn(agent, prompt_hint="idle")
            await engine_with_tools._generate_turn(agent, prompt_hint="idle")

        # Only built once despite two turns
        mock_build.assert_called_once_with("rex", mock_services, simulation_mode=False)


# ── Test: Conversation progression enforcement (#248) ──────────


class TestConversationProgression:
    async def test_dialogue_only_streak_tracks_turns_without_tools(
        self,
        engine: ConversationEngine,
    ) -> None:
        """Dialogue-only streak increments when no tools are used."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            await engine._continue_conversation()

        # No tools used → streak should be 2 (opening + 1 continue turn)
        assert engine._dialogue_only_streak == 2
        assert engine._productive_turns == 0
        assert engine._total_turns == 2

    async def test_tool_usage_resets_dialogue_streak(
        self,
        mock_config_loader: MagicMock,
        mock_agent_registry: MagicMock,
        mock_event_bus: MagicMock,
        mock_llm: MagicMock,
        mock_management: MagicMock,
        mock_context_assembler: MagicMock,
        mock_conversation_repo: MagicMock,
        mock_archival_memory: MagicMock,
        mock_proximity: MagicMock,
        mock_trigger_system: MagicMock,
        mock_selection_logger: MagicMock,
        agents: list[AgentConfig],
    ) -> None:
        """When a tool is used, the dialogue-only streak resets to 0."""
        mock_services = _make_mock_services()
        mock_services.goal_manager = None
        mock_services.shared_working_state = None
        mock_proximity.get_eligible_speakers = AsyncMock(return_value=agents)

        engine_with_tools = ConversationEngine(
            config_loader=mock_config_loader,
            agent_registry=mock_agent_registry,
            event_bus=mock_event_bus,
            llm_client=mock_llm,
            management=mock_management,
            context_assembler=mock_context_assembler,
            conversation_repo=mock_conversation_repo,
            archival_memory=mock_archival_memory,
            proximity=mock_proximity,
            trigger_system=mock_trigger_system,
            selection_logger=mock_selection_logger,
            speed_multiplier=0,
            services=mock_services,
        )

        # Set up a turn that uses tools
        # Note: _continue_conversation calls detect_topic() which uses the LLM
        # when available, so we need a topic classification response in between.
        tool_call = ToolCall(id="call_1", name="web_search", arguments={"query": "test"})
        mock_llm.complete = AsyncMock(
            side_effect=[
                _make_llm_response("Opening line"),  # start conv
                _make_llm_response("general"),  # topic detection in _continue_conversation
                _make_llm_response_with_tool_calls("", [tool_call]),  # tool call
                _make_llm_response("Found results!"),  # after tool
            ]
        )

        mock_tool = MagicMock()
        mock_tool.name = "web_search"
        mock_tool.description = "Search"
        mock_tool.parameters = {"query": {"type": "string"}}
        mock_tool.run = AsyncMock(return_value={"status": "ok"})

        # Manually set a streak to verify reset
        engine_with_tools._dialogue_only_streak = 3

        with patch(
            "core.conversation_engine.build_agent_tools",
            return_value={"web_search": mock_tool},
        ):
            trigger = {"type": "idle", "location": "town_square"}
            await engine_with_tools._start_conversation(trigger)

            result = _make_selection_result("rex")
            with patch.object(engine_with_tools._selector, "select", return_value=result):
                await engine_with_tools._continue_conversation()

        # Tool was used → streak should reset to 0, productive turn counted
        assert engine_with_tools._dialogue_only_streak == 0
        assert engine_with_tools._productive_turns == 1

    async def test_action_nudge_injected_after_4_dialogue_turns(
        self,
        engine: ConversationEngine,
    ) -> None:
        """After 4 consecutive dialogue-only turns, a system nudge is injected."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            for _ in range(4):
                await engine._continue_conversation()

        # After 4 dialogue-only turns, history should contain nudge message
        conv = engine.active_conversation
        nudge_msgs = [
            msg for msg in conv.history
            if msg.get("role") == "user"
            and "taking action" in msg.get("content", "")
        ]
        assert len(nudge_msgs) >= 1

    async def test_productivity_event_emitted_on_end(
        self,
        engine: ConversationEngine,
        mock_event_bus: MagicMock,
    ) -> None:
        """Ending a conversation emits a conversation_productivity event."""
        trigger = {"type": "idle", "location": "town_square"}
        await engine._start_conversation(trigger)

        result = _make_selection_result("rex")
        with patch.object(engine._selector, "select", return_value=result):
            await engine._continue_conversation()

        mock_event_bus.emit.reset_mock()
        await engine._end_conversation()

        # Find the productivity event
        productivity_calls = [
            c for c in mock_event_bus.emit.call_args_list
            if c[0][0] == "conversation_productivity"
        ]
        assert len(productivity_calls) == 1
        data = productivity_calls[0][0][1]
        assert "productive_turns" in data
        assert "total_turns" in data
        assert "ratio" in data
        assert "participants" in data

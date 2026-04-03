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
    LLMResponse,
    LoggingConfig,
    PauseMultipliers,
    ProximityConfig,
    SelectionResult,
    SelectionWeights,
    TimingConfig,
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
def mock_overseer() -> MagicMock:
    overseer = MagicMock()
    overseer.review = AsyncMock(
        return_value=ContentReviewResult(approved=True, reason="OK", severity=1)
    )
    overseer.intervene = AsyncMock()
    overseer.is_muted = AsyncMock(return_value=False)
    return overseer


@pytest.fixture()
def mock_context_assembler() -> MagicMock:
    assembler = MagicMock()
    assembler.assemble_context = AsyncMock(
        return_value=[{"role": "system", "content": "You are an agent."}]
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
def engine(
    mock_config_loader: MagicMock,
    mock_agent_registry: MagicMock,
    mock_event_bus: MagicMock,
    mock_llm: MagicMock,
    mock_overseer: MagicMock,
    mock_context_assembler: MagicMock,
    mock_conversation_repo: MagicMock,
    mock_archival_memory: MagicMock,
    mock_proximity: MagicMock,
    mock_trigger_system: MagicMock,
    mock_selection_logger: MagicMock,
    agents: list[AgentConfig],
) -> ConversationEngine:
    # Make proximity return eligible agents from the fixture
    mock_proximity.get_eligible_speakers = AsyncMock(return_value=agents)

    return ConversationEngine(
        config_loader=mock_config_loader,
        agent_registry=mock_agent_registry,
        event_bus=mock_event_bus,
        llm_client=mock_llm,
        overseer=mock_overseer,
        context_assembler=mock_context_assembler,
        conversation_repo=mock_conversation_repo,
        archival_memory=mock_archival_memory,
        proximity=mock_proximity,
        trigger_system=mock_trigger_system,
        selection_logger=mock_selection_logger,
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
        mock_archival_memory.store_transcript.assert_awaited_once()

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


# ── Test: Overseer rejection triggers replacement ──────────────


class TestOverseerRejection:
    async def test_overseer_rejection_retries(
        self,
        engine: ConversationEngine,
        mock_overseer: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        """When Overseer rejects content, engine retries with new LLM call."""
        # First call rejected, second approved
        mock_overseer.review = AsyncMock(
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
        # Overseer intervene called for the rejection
        mock_overseer.intervene.assert_awaited_once()

    async def test_overseer_high_severity_returns_replacement(
        self,
        engine: ConversationEngine,
        mock_overseer: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        """High severity (>=4) returns replacement instead of retrying."""
        mock_overseer.review = AsyncMock(
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
        mock_overseer.intervene.assert_awaited_once()


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
        mock_overseer: MagicMock,
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
        assert mock_archival_memory.store_transcript.await_count == 10

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
            overseer=MagicMock(),
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

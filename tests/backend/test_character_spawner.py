"""Tests for the character spawning system (#275)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.characters.departure import (
    EXILE_MIN_VOTES,
    EXILE_VOTE_THRESHOLD,
    DepartureManager,
)
from core.characters.spawner import (
    MAX_CAST_SIZE,
    MIN_CAST_SIZE,
    CharacterApplication,
    CharacterSpawner,
)
from core.characters.voting import (
    AGENT_VOTE_WEIGHT,
    AUDIENCE_VOTE_WEIGHT,
    APPROVAL_THRESHOLD,
    VotingManager,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_agent(agent_id: str, role: str = "Test", voice_id: str = "v1") -> MagicMock:
    """Create a mock AgentConfig."""
    agent = MagicMock()
    agent.id = agent_id
    agent.display_name = f"{agent_id.capitalize()} — {role}"
    agent.role = role
    agent.voice_id = voice_id
    agent.color_hex = "#000000"
    agent.tools = []
    return agent


def _make_registry(count: int = 9) -> MagicMock:
    """Create a mock AgentRegistry with *count* agents."""
    registry = MagicMock()
    agents = [_make_agent(f"agent{i}", f"Role{i}", f"voice{i}") for i in range(count)]
    registry.get_all_agents.return_value = agents
    return registry


# ── CharacterSpawner Tests ───────────────────────────────────────


class TestCharacterSpawner:
    """Tests for CharacterSpawner concept generation and onboarding."""

    def test_can_add_character_under_limit(self) -> None:
        registry = _make_registry(9)
        spawner = CharacterSpawner(agent_registry=registry)
        assert spawner.can_add_character() is True

    def test_cannot_add_character_at_limit(self) -> None:
        registry = _make_registry(MAX_CAST_SIZE)
        spawner = CharacterSpawner(agent_registry=registry)
        assert spawner.can_add_character() is False

    def test_get_active_count(self) -> None:
        registry = _make_registry(7)
        spawner = CharacterSpawner(agent_registry=registry)
        assert spawner.get_active_count() == 7

    @pytest.mark.asyncio
    async def test_generate_concept_returns_none_when_full(self) -> None:
        registry = _make_registry(MAX_CAST_SIZE)
        spawner = CharacterSpawner(agent_registry=registry)
        result = await spawner.generate_concept()
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_concept_returns_none_without_llm(self) -> None:
        registry = _make_registry(9)
        spawner = CharacterSpawner(agent_registry=registry, llm_client=None)
        result = await spawner.generate_concept()
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_concept_with_llm(self) -> None:
        registry = _make_registry(9)
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(
            content='{"name": "nova", "display_name": "Nova — The Diplomat", '
                    '"role": "Diplomat", "personality_sketch": "Calm and persuasive."}'
        )
        spawner = CharacterSpawner(agent_registry=registry, llm_client=llm)
        result = await spawner.generate_concept()
        assert result is not None
        assert result.name == "nova"
        assert result.role == "Diplomat"
        assert result.source == "system"

    @pytest.mark.asyncio
    async def test_create_agent_config(self, tmp_path: Path) -> None:
        registry = _make_registry(9)
        # Create template dir
        template_dir = tmp_path / "template"
        template_dir.mkdir()
        (template_dir / "config.yaml").write_text("id: template\n")
        (template_dir / "system_prompt.md").write_text(
            "You are {name}, {role}.\n{personality}"
        )
        (template_dir / "behaviors.yaml").write_text("morning_routine: []\n")

        spawner = CharacterSpawner(
            agent_registry=registry,
            config_dir=tmp_path,
        )

        app = CharacterApplication(
            name="nova",
            display_name="Nova — The Diplomat",
            role="Diplomat",
            personality_sketch="Calm and persuasive.",
        )

        agent_dir = await spawner.create_agent_config(app)
        assert agent_dir.exists()
        assert (agent_dir / "config.yaml").exists()
        assert (agent_dir / "system_prompt.md").exists()
        assert (agent_dir / "behaviors.yaml").exists()

    @pytest.mark.asyncio
    async def test_assign_desk(self) -> None:
        registry = _make_registry(9)
        spawner = CharacterSpawner(agent_registry=registry)
        pos = await spawner.assign_desk("nova")
        assert "x" in pos
        assert "y" in pos
        assert pos["agent_id"] == "nova"

    @pytest.mark.asyncio
    async def test_onboard_fails_when_full(self) -> None:
        registry = _make_registry(MAX_CAST_SIZE)
        spawner = CharacterSpawner(agent_registry=registry)
        app = CharacterApplication(name="nova", role="Diplomat")
        result = await spawner.onboard(app)
        assert result is None


# ── VotingManager Tests ──────────────────────────────────────────


class TestVotingManager:
    """Tests for character voting mechanics."""

    @pytest.mark.asyncio
    async def test_start_deliberation_queues_trigger(self) -> None:
        trigger_system = MagicMock()
        vm = VotingManager(trigger_system=trigger_system)
        await vm.start_deliberation("test-app-id")
        trigger_system.queue_event.assert_called_once()
        call_args = trigger_system.queue_event.call_args
        assert call_args[0][0] == "character_deliberation"

    @pytest.mark.asyncio
    async def test_record_agent_vote(self) -> None:
        db = AsyncMock()
        db.fetchrow.return_value = {"agent_votes": {}}
        vm = VotingManager(db=db)
        await vm.record_agent_vote("app-1", "vera", True, "She's cool")
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tally_votes_approved(self) -> None:
        db = AsyncMock()
        # 3 yes, 1 no from agents → agent_score = 0.75
        # 10 yes, 5 no from audience → audience_score = 0.667
        # combined = 0.75 * 0.6 + 0.667 * 0.4 = 0.45 + 0.267 = 0.717 > 0.5
        db.fetchrow.return_value = {
            "agent_votes": '{"vera": {"vote": true}, "rex": {"vote": true}, '
                          '"fork": {"vote": true}, "grok": {"vote": false}}',
            "audience_votes_for": 10,
            "audience_votes_against": 5,
        }
        vm = VotingManager(db=db)
        result = await vm.tally_votes("app-1")
        assert result == "approved"

    @pytest.mark.asyncio
    async def test_tally_votes_rejected(self) -> None:
        db = AsyncMock()
        # 1 yes, 3 no from agents → agent_score = 0.25
        # 2 yes, 8 no from audience → audience_score = 0.2
        # combined = 0.25 * 0.6 + 0.2 * 0.4 = 0.15 + 0.08 = 0.23 < 0.5
        db.fetchrow.return_value = {
            "agent_votes": '{"vera": {"vote": false}, "rex": {"vote": false}, '
                          '"fork": {"vote": false}, "grok": {"vote": true}}',
            "audience_votes_for": 2,
            "audience_votes_against": 8,
        }
        vm = VotingManager(db=db)
        result = await vm.tally_votes("app-1")
        assert result == "rejected"

    @pytest.mark.asyncio
    async def test_tally_no_audience_votes_defaults_neutral(self) -> None:
        db = AsyncMock()
        # 2 yes, 1 no → agent_score = 0.667
        # No audience → audience_score = 0.5
        # combined = 0.667 * 0.6 + 0.5 * 0.4 = 0.4 + 0.2 = 0.6 > 0.5
        db.fetchrow.return_value = {
            "agent_votes": '{"vera": {"vote": true}, "rex": {"vote": true}, '
                          '"fork": {"vote": false}}',
            "audience_votes_for": 0,
            "audience_votes_against": 0,
        }
        vm = VotingManager(db=db)
        result = await vm.tally_votes("app-1")
        assert result == "approved"

    @pytest.mark.asyncio
    async def test_get_pending_empty_without_db(self) -> None:
        vm = VotingManager()
        result = await vm.get_pending_applications()
        assert result == []


# ── DepartureManager Tests ───────────────────────────────────────


class TestDepartureManager:
    """Tests for character departure mechanics."""

    @pytest.mark.asyncio
    async def test_check_departure_conditions_true(self) -> None:
        state_mgr = AsyncMock()
        state = MagicMock()
        state.satisfaction = 0.1
        state.frustration = 0.9
        state_mgr.get_state.return_value = state

        dm = DepartureManager(agent_state_manager=state_mgr)
        assert await dm.check_departure_conditions("test") is True

    @pytest.mark.asyncio
    async def test_check_departure_conditions_false(self) -> None:
        state_mgr = AsyncMock()
        state = MagicMock()
        state.satisfaction = 0.5
        state.frustration = 0.3
        state_mgr.get_state.return_value = state

        dm = DepartureManager(agent_state_manager=state_mgr)
        assert await dm.check_departure_conditions("test") is False

    def test_can_depart_above_minimum(self) -> None:
        registry = _make_registry(8)
        dm = DepartureManager(agent_registry=registry)
        assert dm.can_depart() is True

    def test_cannot_depart_at_minimum(self) -> None:
        registry = _make_registry(MIN_CAST_SIZE)
        dm = DepartureManager(agent_registry=registry)
        assert dm.can_depart() is False

    @pytest.mark.asyncio
    async def test_process_departure_blocked_when_cast_too_small(self) -> None:
        registry = _make_registry(MIN_CAST_SIZE)
        dm = DepartureManager(agent_registry=registry)
        result = await dm.process_departure("test", "voluntary")
        assert result is None

    @pytest.mark.asyncio
    async def test_process_departure_success(self) -> None:
        registry = _make_registry(8)
        dm = DepartureManager(agent_registry=registry, llm_client=None)
        result = await dm.process_departure("test", "voluntary")
        assert result is not None
        assert result["agent_id"] == "test"
        assert result["reason"] == "voluntary"

    @pytest.mark.asyncio
    async def test_exile_vote_passes(self) -> None:
        dm = DepartureManager()
        # 40 yes, 10 no → 80% > 70%, total 50 >= 50
        assert await dm.check_exile_vote("test", 40, 10) is True

    @pytest.mark.asyncio
    async def test_exile_vote_fails_threshold(self) -> None:
        dm = DepartureManager()
        # 30 yes, 20 no → 60% < 70%
        assert await dm.check_exile_vote("test", 30, 20) is False

    @pytest.mark.asyncio
    async def test_exile_vote_fails_minimum(self) -> None:
        dm = DepartureManager()
        # 10 yes, 1 no → 91% > 70%, but total 11 < 50
        assert await dm.check_exile_vote("test", 10, 1) is False


# ── Trigger Integration ──────────────────────────────────────────


class TestCharacterTriggerIntegration:
    """Tests for character events in the trigger system."""

    def test_character_events_recognized(self) -> None:
        from core.conversation.triggers import CHARACTER_EVENTS
        assert "character_deliberation" in CHARACTER_EVENTS
        assert "character_welcome" in CHARACTER_EVENTS

    def test_queue_character_event(self) -> None:
        from core.conversation.triggers import TriggerSystem
        from core.models import TriggerConfig

        config = TriggerConfig(
            idle_timeout_seconds=90,
            agent_initiative={"vera": 0.8},
            trigger_type_weights={"idle": 1.0},
        )
        ts = TriggerSystem(config)
        ts.queue_event("character_deliberation", {"application_id": "test"})
        # Event should be queued
        assert len(ts._pending_events) == 1
        event = ts._pending_events[0]
        assert event["category"] == "character"
        assert event["event_type"] == "character_deliberation"

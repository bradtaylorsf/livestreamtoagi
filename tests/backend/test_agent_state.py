"""Tests for the agent internal state system (#267)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_state import AgentState, AgentStateManager, _clamp, _derive_mood


# ── Model Tests ───────────────────────────────────────────────────


class TestAgentStateModel:
    """AgentState model with defaults and validation."""

    def test_defaults(self) -> None:
        state = AgentState(agent_id="vera")
        assert state.energy == 0.7
        assert state.satisfaction == 0.5
        assert state.boredom == 0.2
        assert state.frustration == 0.1
        assert state.social_need == 0.5
        assert state.creative_need == 0.3
        assert state.recognition_need == 0.3
        assert state.mood == "neutral"
        assert state.version == 1

    def test_custom_values(self) -> None:
        state = AgentState(
            agent_id="rex",
            energy=0.9,
            boredom=0.8,
            frustration=0.7,
            mood="frustrated",
        )
        assert state.agent_id == "rex"
        assert state.energy == 0.9
        assert state.boredom == 0.8
        assert state.frustration == 0.7
        assert state.mood == "frustrated"

    def test_refresh_mood(self) -> None:
        state = AgentState(agent_id="vera", frustration=0.8, boredom=0.6)
        state.refresh_mood()
        assert state.mood == "frustrated"

    def test_serialization_roundtrip(self) -> None:
        state = AgentState(agent_id="rex", energy=0.42)
        json_str = state.model_dump_json()
        restored = AgentState.model_validate_json(json_str)
        assert restored.agent_id == "rex"
        assert restored.energy == 0.42


# ── Mood Derivation ───────────────────────────────────────────────


class TestMoodDerivation:
    """Mood is derived from composite state variables."""

    def test_frustrated(self) -> None:
        state = AgentState(agent_id="a", frustration=0.75, boredom=0.55)
        assert _derive_mood(state) == "frustrated"

    def test_irritated(self) -> None:
        state = AgentState(agent_id="a", frustration=0.65, boredom=0.3)
        assert _derive_mood(state) == "irritated"

    def test_bored(self) -> None:
        state = AgentState(agent_id="a", boredom=0.75, frustration=0.2)
        assert _derive_mood(state) == "bored"

    def test_inspired(self) -> None:
        state = AgentState(agent_id="a", energy=0.8, creative_need=0.6, frustration=0.1, boredom=0.1)
        assert _derive_mood(state) == "inspired"

    def test_content(self) -> None:
        state = AgentState(agent_id="a", energy=0.65, satisfaction=0.65, frustration=0.1, boredom=0.1, creative_need=0.2)
        assert _derive_mood(state) == "content"

    def test_lonely(self) -> None:
        state = AgentState(agent_id="a", social_need=0.75, frustration=0.1, boredom=0.1, energy=0.4)
        assert _derive_mood(state) == "lonely"

    def test_exhausted(self) -> None:
        state = AgentState(agent_id="a", energy=0.15, frustration=0.1, boredom=0.1)
        assert _derive_mood(state) == "exhausted"

    def test_competitive(self) -> None:
        state = AgentState(agent_id="a", recognition_need=0.75, energy=0.5, frustration=0.1, boredom=0.1, social_need=0.3)
        assert _derive_mood(state) == "competitive"

    def test_neutral_default(self) -> None:
        state = AgentState(agent_id="a")
        assert _derive_mood(state) == "neutral"


# ── Clamp ─────────────────────────────────────────────────────────


class TestClamp:
    def test_clamp_normal(self) -> None:
        assert _clamp(0.5) == 0.5

    def test_clamp_below(self) -> None:
        assert _clamp(-0.3) == 0.0

    def test_clamp_above(self) -> None:
        assert _clamp(1.5) == 1.0


# ── State Manager ─────────────────────────────────────────────────


class TestAgentStateManager:
    """AgentStateManager reads/writes state and applies transitions."""

    @pytest.fixture()
    def manager(self) -> AgentStateManager:
        """Manager with no Redis or DB (pure in-memory mode)."""
        return AgentStateManager()

    async def test_get_state_returns_defaults(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        assert state.agent_id == "vera"
        assert state.energy == 0.7

    async def test_get_state_cached(self, manager: AgentStateManager) -> None:
        state1 = await manager.get_state("vera")
        state1.energy = 0.42
        state2 = await manager.get_state("vera")
        assert state2.energy == 0.42  # Same object from cache

    async def test_save_state_refreshes_mood(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("rex")
        state.frustration = 0.8
        state.boredom = 0.6
        await manager.save_state(state)
        assert state.mood == "frustrated"

    async def test_on_conversation_turn_depletes_energy(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        initial_energy = state.energy
        await manager.on_conversation_turn("vera")
        state = await manager.get_state("vera")
        assert state.energy < initial_energy

    async def test_on_conversation_turn_reduces_social_need(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        initial = state.social_need
        await manager.on_conversation_turn("vera")
        state = await manager.get_state("vera")
        assert state.social_need < initial

    async def test_on_conversation_turn_boredom_increases_on_same_topic(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        initial = state.boredom
        await manager.on_conversation_turn("vera", topic="code", previous_topics=["code", "code"])
        state = await manager.get_state("vera")
        assert state.boredom > initial

    async def test_on_conversation_turn_boredom_decreases_on_novel_topic(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        initial = state.boredom
        await manager.on_conversation_turn("vera", topic="art", previous_topics=["code", "planning"])
        state = await manager.get_state("vera")
        assert state.boredom < initial

    async def test_on_idle_tick_recharges_energy(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("rex")
        state.energy = 0.3
        await manager.save_state(state)
        await manager.on_idle_tick("rex")
        state = await manager.get_state("rex")
        assert state.energy == pytest.approx(0.4, abs=0.01)

    async def test_on_idle_tick_increases_needs(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("rex")
        initial_social = state.social_need
        initial_creative = state.creative_need
        await manager.on_idle_tick("rex")
        state = await manager.get_state("rex")
        assert state.social_need > initial_social
        assert state.creative_need > initial_creative

    async def test_on_goal_progress(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        state.frustration = 0.5
        await manager.save_state(state)
        await manager.on_goal_progress("vera")
        state = await manager.get_state("vera")
        assert state.frustration < 0.5
        assert state.satisfaction > 0.5

    async def test_on_goal_blocked(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("vera")
        initial_frust = state.frustration
        await manager.on_goal_blocked("vera")
        state = await manager.get_state("vera")
        assert state.frustration > initial_frust

    async def test_on_building_activity(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("aurora")
        state.creative_need = 0.8
        await manager.save_state(state)
        await manager.on_building_activity("aurora")
        state = await manager.get_state("aurora")
        assert state.creative_need == pytest.approx(0.5, abs=0.01)

    async def test_on_novel_event(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("grok")
        state.boredom = 0.6
        await manager.save_state(state)
        await manager.on_novel_event("grok")
        state = await manager.get_state("grok")
        assert state.boredom == pytest.approx(0.4, abs=0.01)

    async def test_on_recognition(self, manager: AgentStateManager) -> None:
        state = await manager.get_state("pixel")
        state.recognition_need = 0.7
        await manager.save_state(state)
        await manager.on_recognition("pixel")
        state = await manager.get_state("pixel")
        assert state.recognition_need == pytest.approx(0.5, abs=0.01)

    async def test_state_diverges_across_agents(self, manager: AgentStateManager) -> None:
        """After different events, agents should have different states."""
        # Rex builds a lot
        for _ in range(5):
            await manager.on_building_activity("rex")
        # Aurora chats a lot
        for _ in range(5):
            await manager.on_conversation_turn("aurora")
        # Grok idles
        for _ in range(5):
            await manager.on_idle_tick("grok")

        rex = await manager.get_state("rex")
        aurora = await manager.get_state("aurora")
        grok = await manager.get_state("grok")

        # Creative need: rex should be low, grok should be higher
        assert rex.creative_need < grok.creative_need
        # Energy: aurora should be lower from conversations
        assert aurora.energy < grok.energy
        # Social need: grok should be higher from idle
        assert grok.social_need > rex.social_need


class TestAgentStateManagerWithRedis:
    """Tests with mocked Redis for persistence."""

    async def test_loads_from_redis(self) -> None:
        redis = MagicMock()
        state_data = AgentState(agent_id="vera", energy=0.42).model_dump_json()
        redis.get = AsyncMock(return_value=state_data)
        redis.set = AsyncMock()

        manager = AgentStateManager(redis_client=redis)
        state = await manager.get_state("vera")
        assert state.energy == 0.42

    async def test_saves_to_redis(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        manager = AgentStateManager(redis_client=redis)
        state = await manager.get_state("vera")
        await manager.save_state(state)

        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == "agent:state:vera"

    async def test_falls_back_to_db_when_redis_empty(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        repo = MagicMock()
        db_state = AgentState(agent_id="vera", energy=0.33)
        repo.get = AsyncMock(return_value=db_state)

        manager = AgentStateManager(redis_client=redis, state_repo=repo)
        state = await manager.get_state("vera")
        assert state.energy == 0.33
        # Should have written back to Redis
        redis.set.assert_called_once()

    async def test_snapshot_to_db(self) -> None:
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        repo.upsert = AsyncMock()

        manager = AgentStateManager(state_repo=repo)
        state = await manager.get_state("vera")
        await manager.snapshot_to_db("vera")
        repo.upsert.assert_called_once()


# ── Context Formatting ────────────────────────────────────────────


class TestFormatStateForContext:
    """State formatting for system prompt injection."""

    def test_includes_mood(self) -> None:
        manager = AgentStateManager()
        state = AgentState(agent_id="vera", frustration=0.8, boredom=0.6)
        state.refresh_mood()
        text = manager.format_state_for_context(state)
        assert "frustrated" in text

    def test_includes_all_variables(self) -> None:
        manager = AgentStateManager()
        state = AgentState(agent_id="vera")
        text = manager.format_state_for_context(state)
        assert "Energy" in text
        assert "Satisfaction" in text
        assert "Boredom" in text
        assert "Frustration" in text
        assert "Social need" in text
        assert "Creative need" in text
        assert "Recognition need" in text

    def test_level_labels(self) -> None:
        manager = AgentStateManager()
        state = AgentState(agent_id="vera", energy=0.9, boredom=0.1)
        text = manager.format_state_for_context(state)
        assert "very high" in text  # energy 0.9
        assert "very low" in text   # boredom 0.1


# ── Trigger Integration ───────────────────────────────────────────


class TestStateTriggers:
    """State-driven conversation triggers."""

    @pytest.fixture()
    def trigger_config(self) -> MagicMock:
        config = MagicMock()
        config.idle_timeout_seconds = 999999  # Prevent idle triggers
        config.memory_trigger_chance = 0.0
        config.agent_initiative = {"vera": 0.7, "rex": 0.5}
        config.daily_schedule = {}  # Empty schedule
        return config

    @staticmethod
    def _make_now_fn():
        """Return a now_fn at hour 15 (no default schedule event)."""
        return lambda: datetime(2026, 4, 7, 15, 0, 0)

    async def test_boredom_trigger(self, trigger_config: MagicMock) -> None:
        from core.conversation.triggers import TriggerSystem

        state_manager = AgentStateManager()
        state = await state_manager.get_state("vera")
        state.boredom = 0.8
        await state_manager.save_state(state)

        ts = TriggerSystem(
            trigger_config,
            agent_state_manager=state_manager,
            rng=__import__("random").Random(42),
            now_fn=self._make_now_fn(),
        )

        trigger = await ts.check()
        assert trigger is not None
        assert trigger["type"] == "state"
        assert trigger["state_trigger"] == "boredom"

    async def test_creative_need_trigger(self, trigger_config: MagicMock) -> None:
        from core.conversation.triggers import TriggerSystem

        state_manager = AgentStateManager()
        state = await state_manager.get_state("rex")
        state.creative_need = 0.8
        await state_manager.save_state(state)

        ts = TriggerSystem(
            trigger_config,
            agent_state_manager=state_manager,
            rng=__import__("random").Random(42),
            now_fn=self._make_now_fn(),
        )

        trigger = await ts.check()
        assert trigger is not None
        assert trigger["type"] == "state"
        assert trigger["state_trigger"] == "creative_need"

    async def test_social_need_trigger(self, trigger_config: MagicMock) -> None:
        from core.conversation.triggers import TriggerSystem

        state_manager = AgentStateManager()
        for aid in ("vera", "rex"):
            state = await state_manager.get_state(aid)
            state.social_need = 0.8
            await state_manager.save_state(state)

        ts = TriggerSystem(
            trigger_config,
            agent_state_manager=state_manager,
            rng=__import__("random").Random(42),
            now_fn=self._make_now_fn(),
        )

        trigger = await ts.check()
        assert trigger is not None
        assert trigger["type"] == "state"
        assert trigger["state_trigger"] == "social_need"

    async def test_no_trigger_when_state_normal(self, trigger_config: MagicMock) -> None:
        from core.conversation.triggers import TriggerSystem

        state_manager = AgentStateManager()

        ts = TriggerSystem(
            trigger_config,
            agent_state_manager=state_manager,
            rng=__import__("random").Random(42),
            now_fn=self._make_now_fn(),
        )

        trigger = await ts.check()
        assert trigger is None

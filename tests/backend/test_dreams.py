"""Tests for the dream system (#272)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.memory.dreams import (
    DREAM_TEMPERATURE,
    MOOD_SHIFT_EFFECTS,
    DreamGoal,
    DreamManager,
    DreamResult,
)


# ── DreamResult Model Tests ──────────────────────────────────────


class TestDreamResult:
    """Tests for DreamResult model."""

    def test_defaults(self) -> None:
        result = DreamResult(dream_narrative="A dream about code...")
        assert result.dream_narrative == "A dream about code..."
        assert result.insights == []
        assert result.new_goals == []
        assert result.mood_shift == "inspired"

    def test_full_result(self) -> None:
        result = DreamResult(
            dream_narrative="I dreamed of infinite loops...",
            insights=["Code is poetry", "Bugs are features"],
            new_goals=[
                DreamGoal(description="Write a poem in code", category="creative", priority=2),
            ],
            mood_shift="determined",
        )
        assert len(result.insights) == 2
        assert len(result.new_goals) == 1
        assert result.new_goals[0].priority == 2


class TestDreamGoal:
    def test_defaults(self) -> None:
        goal = DreamGoal(description="Build something")
        assert goal.category == "creative"
        assert goal.priority == 3


# ── DreamManager Tests ───────────────────────────────────────────


class TestDreamManager:
    """Tests for DreamManager dream generation and effects."""

    def _make_llm(self, response_json: dict) -> AsyncMock:
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(
            content=json.dumps(response_json)
        )
        return llm

    def _default_dream_response(self) -> dict:
        return {
            "dream_narrative": "I was floating through a world of data...",
            "insights": ["Data has patterns everywhere"],
            "new_goals": [
                {"description": "Explore new data visualization", "category": "creative", "priority": 2},
            ],
            "mood_shift": "inspired",
        }

    @pytest.mark.asyncio
    async def test_run_dream_returns_none_without_llm(self) -> None:
        mgr = DreamManager()
        result = await mgr.run_dream("vera")
        assert result is None

    @pytest.mark.asyncio
    async def test_run_dream_success(self) -> None:
        llm = self._make_llm(self._default_dream_response())
        mgr = DreamManager(llm_client=llm)
        result = await mgr.run_dream("vera")
        assert result is not None
        assert isinstance(result, DreamResult)
        assert "floating" in result.dream_narrative
        assert len(result.insights) == 1
        assert len(result.new_goals) == 1
        assert result.mood_shift == "inspired"

    @pytest.mark.asyncio
    async def test_dream_uses_high_temperature(self) -> None:
        llm = self._make_llm(self._default_dream_response())
        mgr = DreamManager(llm_client=llm)
        await mgr.run_dream("vera")

        # Check that the LLM was called with high temperature
        call_kwargs = llm.complete.call_args
        assert call_kwargs.kwargs["temperature"] == DREAM_TEMPERATURE

    @pytest.mark.asyncio
    async def test_dream_applies_mood_shift(self) -> None:
        from core.agent_state import AgentStateManager

        llm = self._make_llm(self._default_dream_response())
        state_mgr = AgentStateManager()
        mgr = DreamManager(llm_client=llm, agent_state_manager=state_mgr)

        await mgr.run_dream("vera")

        state = await state_mgr.get_state("vera")
        # "inspired" mood shift: creative_need-0.3, satisfaction+0.15
        assert state.creative_need == 0.0  # 0.3 - 0.3 = 0.0
        assert state.satisfaction == 0.65  # 0.5 + 0.15

    @pytest.mark.asyncio
    async def test_dream_creates_goals(self) -> None:
        llm = self._make_llm(self._default_dream_response())
        goal_mgr = AsyncMock()
        mgr = DreamManager(llm_client=llm, goal_manager=goal_mgr)

        await mgr.run_dream("vera")

        goal_mgr.add_goal.assert_called_once()
        call_kwargs = goal_mgr.add_goal.call_args
        assert call_kwargs[0][0] == "vera"
        assert "visualization" in call_kwargs[0][1]
        assert call_kwargs.kwargs["source"] == "dream"

    @pytest.mark.asyncio
    async def test_dream_stores_journal_entry(self) -> None:
        llm = self._make_llm(self._default_dream_response())
        repo = AsyncMock()
        repo.get_recent_journal_entries.return_value = []
        mgr = DreamManager(llm_client=llm, memory_repo=repo)

        await mgr.run_dream("vera")

        repo.create_journal_entry.assert_called_once()
        entry = repo.create_journal_entry.call_args[0][0]
        assert entry.reflection_type == "dream"
        assert "floating" in entry.content

    @pytest.mark.asyncio
    async def test_dream_stores_insights_as_recall(self) -> None:
        llm = self._make_llm(self._default_dream_response())
        repo = AsyncMock()
        repo.get_recent_journal_entries.return_value = []
        embedding_fn = AsyncMock(return_value=[0.1] * 1536)
        mgr = DreamManager(llm_client=llm, memory_repo=repo, embedding_fn=embedding_fn)

        await mgr.run_dream("vera")

        repo.add_recall.assert_called_once()
        memory = repo.add_recall.call_args[0][0]
        assert "[Dream insight]" in memory.summary
        assert memory.importance_score == 0.8

    @pytest.mark.asyncio
    async def test_dream_with_memories(self) -> None:
        llm = self._make_llm(self._default_dream_response())
        repo = AsyncMock()

        # Simulate having recent journal entries
        mock_entries = [
            MagicMock(content="Had a productive day building the API"),
            MagicMock(content="Fork disagreed with my approach"),
        ]
        repo.get_recent_journal_entries.return_value = mock_entries
        mgr = DreamManager(llm_client=llm, memory_repo=repo)

        result = await mgr.run_dream("vera")
        assert result is not None
        # Verify the LLM was called (memories were included in prompt)
        llm.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_dream_with_state_context(self) -> None:
        from core.agent_state import AgentState, AgentStateManager

        llm = self._make_llm(self._default_dream_response())
        state_mgr = AgentStateManager()
        # Set high frustration and creative need
        state = AgentState(
            agent_id="vera", frustration=0.7, creative_need=0.8,
            boredom=0.6,
        )
        state_mgr._cache["vera"] = state

        mgr = DreamManager(llm_client=llm, agent_state_manager=state_mgr)
        result = await mgr.run_dream("vera")
        assert result is not None

    @pytest.mark.asyncio
    async def test_parse_invalid_response(self) -> None:
        llm = AsyncMock()
        llm.complete.return_value = MagicMock(content="This is not JSON at all")
        mgr = DreamManager(llm_client=llm)
        result = await mgr.run_dream("vera")
        assert result is None

    @pytest.mark.asyncio
    async def test_mood_shift_effects_all_valid(self) -> None:
        """All mood shifts should map to valid state field names."""
        from core.agent_state import AgentState
        state = AgentState(agent_id="test")
        for mood, effects in MOOD_SHIFT_EFFECTS.items():
            for field_name in effects:
                assert hasattr(state, field_name), (
                    f"Mood '{mood}' references invalid field '{field_name}'"
                )

    @pytest.mark.asyncio
    async def test_each_mood_shift(self) -> None:
        """Verify each mood shift applies the correct state changes."""
        from core.agent_state import AgentStateManager

        for mood_name, effects in MOOD_SHIFT_EFFECTS.items():
            response = {
                "dream_narrative": "A dream...",
                "insights": [],
                "new_goals": [],
                "mood_shift": mood_name,
            }
            llm = AsyncMock()
            llm.complete.return_value = MagicMock(content=json.dumps(response))
            state_mgr = AgentStateManager()
            mgr = DreamManager(llm_client=llm, agent_state_manager=state_mgr)

            await mgr.run_dream("test")
            state = await state_mgr.get_state("test")

            for field_name, delta in effects.items():
                # Defaults: energy=0.7, satisfaction=0.5, boredom=0.2,
                # frustration=0.1, social_need=0.5, creative_need=0.3
                defaults = {
                    "energy": 0.7, "satisfaction": 0.5, "boredom": 0.2,
                    "frustration": 0.1, "social_need": 0.5, "creative_need": 0.3,
                    "recognition_need": 0.3,
                }
                expected = max(0.0, min(1.0, defaults[field_name] + delta))
                actual = getattr(state, field_name)
                assert abs(actual - expected) < 0.01, (
                    f"Mood '{mood_name}', field '{field_name}': "
                    f"expected {expected}, got {actual}"
                )


# ── Reflection Scheduler Dream Integration ───────────────────────


class TestReflectionSchedulerDreamIntegration:
    """Tests for dream triggers in the reflection scheduler."""

    def _make_clock(self, start_hours: int = 0) -> MagicMock:
        clock = MagicMock()
        base = datetime(2024, 1, 1, 0, 0, 0)
        clock.now.return_value = base + timedelta(hours=start_hours)
        clock.simulated_day.return_value = 1
        return clock

    @pytest.mark.asyncio
    async def test_dream_triggers_after_interval(self) -> None:
        from core.memory.reflection_scheduler import ReflectionScheduler

        clock = self._make_clock(0)
        reflection_mgr = MagicMock()
        dream_mgr = AsyncMock()

        scheduler = ReflectionScheduler(
            clock=clock,
            reflection_manager=reflection_mgr,
            dream_manager=dream_mgr,
            dream_interval_hours=14,
        )
        scheduler._ensure_tracking("vera")

        # Advance clock past dream interval
        clock.now.return_value = datetime(2024, 1, 1, 15, 0, 0)
        await scheduler._check_and_run_dream("vera", clock.now())
        dream_mgr.run_dream.assert_called_once_with("vera")

    @pytest.mark.asyncio
    async def test_dream_does_not_trigger_before_interval(self) -> None:
        from core.memory.reflection_scheduler import ReflectionScheduler

        clock = self._make_clock(0)
        reflection_mgr = MagicMock()
        dream_mgr = AsyncMock()

        scheduler = ReflectionScheduler(
            clock=clock,
            reflection_manager=reflection_mgr,
            dream_manager=dream_mgr,
            dream_interval_hours=14,
        )
        scheduler._ensure_tracking("vera")

        # Only 5 hours have passed — not enough for dream
        clock.now.return_value = datetime(2024, 1, 1, 5, 0, 0)
        await scheduler._check_and_run_dream("vera", clock.now())
        dream_mgr.run_dream.assert_not_called()

    @pytest.mark.asyncio
    async def test_boredom_triggers_dream_early(self) -> None:
        from core.agent_state import AgentState, AgentStateManager
        from core.memory.reflection_scheduler import ReflectionScheduler

        clock = self._make_clock(0)
        reflection_mgr = MagicMock()
        dream_mgr = AsyncMock()
        state_mgr = AgentStateManager()

        # Set very high boredom
        state = AgentState(agent_id="vera", boredom=0.9)
        state_mgr._cache["vera"] = state

        scheduler = ReflectionScheduler(
            clock=clock,
            reflection_manager=reflection_mgr,
            dream_manager=dream_mgr,
            dream_interval_hours=14,
            agent_state_manager=state_mgr,
        )
        scheduler._ensure_tracking("vera")

        # Only 5 hours — normally wouldn't dream, but boredom overrides
        clock.now.return_value = datetime(2024, 1, 1, 5, 0, 0)
        await scheduler._check_and_run_dream("vera", clock.now())
        dream_mgr.run_dream.assert_called_once_with("vera")

    @pytest.mark.asyncio
    async def test_no_dream_without_manager(self) -> None:
        from core.memory.reflection_scheduler import ReflectionScheduler

        clock = self._make_clock(0)
        reflection_mgr = MagicMock()

        scheduler = ReflectionScheduler(
            clock=clock,
            reflection_manager=reflection_mgr,
            dream_manager=None,
        )
        scheduler._ensure_tracking("vera")

        # Should not crash without dream manager
        clock.now.return_value = datetime(2024, 1, 1, 15, 0, 0)
        await scheduler._check_and_run_dream("vera", clock.now())


# ── Context Assembly Dream Integration ───────────────────────────


class TestContextAssemblyDreamIntegration:
    """Tests for dream context in the context assembler."""

    def test_assemble_context_accepts_dream_param(self) -> None:
        """Verify the assemble_context method accepts recent_dream parameter."""
        import inspect
        from core.context_assembly import ContextAssembler
        sig = inspect.signature(ContextAssembler.assemble_context)
        assert "recent_dream" in sig.parameters

    def test_dream_temperature_is_high(self) -> None:
        assert DREAM_TEMPERATURE >= 1.2

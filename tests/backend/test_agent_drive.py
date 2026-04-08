"""Tests for agent intrinsic drive system (#239)."""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from core.agent_goals import AgentGoalLegacy, AgentGoalManager
from core.models import AgentGoal


# ── AgentGoal Pydantic model tests ───────────────────────────


class TestAgentGoalModel:
    def test_create(self) -> None:
        g = AgentGoal(
            id=uuid.uuid4(),
            agent_id="rex",
            goal="Build a prototype",
            priority=2,
            status="active",
            source="self",
        )
        assert g.agent_id == "rex"
        assert g.priority == 2
        assert g.source == "self"

    def test_defaults(self) -> None:
        g = AgentGoal(
            id=uuid.uuid4(),
            agent_id="vera",
            goal="Test goal",
        )
        assert g.priority == 5
        assert g.status == "active"
        assert g.parent_goal_id is None


# ── AgentGoalManager with DB tests ──────────────────────────


class TestAgentGoalManagerDB:
    @pytest.mark.asyncio
    async def test_get_goals_from_db(self) -> None:
        mock_repo = AsyncMock()
        mock_repo.get_active_goals.return_value = [
            AgentGoal(
                id=uuid.uuid4(),
                agent_id="rex",
                goal="Build prototype",
                priority=1,
                status="active",
                source="self",
            ),
        ]

        manager = AgentGoalManager(goal_repo=mock_repo)
        goals = await manager.get_goals("rex")
        assert len(goals) == 1
        assert goals[0].goal == "Build prototype"
        assert goals[0].priority == 1

    @pytest.mark.asyncio
    async def test_add_goal_db(self) -> None:
        mock_repo = AsyncMock()
        mock_repo.get_active_goals.return_value = []
        mock_repo.add_goal.return_value = AgentGoal(
            id=uuid.uuid4(),
            agent_id="rex",
            goal="Ship code",
            priority=3,
            status="active",
            source="self",
        )

        manager = AgentGoalManager(goal_repo=mock_repo)
        result = await manager.add_goal("rex", "Ship code", priority=3)
        assert result.goal == "Ship code"
        mock_repo.add_goal.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_goal_deduplication_db(self) -> None:
        existing_goal = AgentGoal(
            id=uuid.uuid4(),
            agent_id="rex",
            goal="Ship code",
            priority=3,
            status="active",
            source="self",
        )
        mock_repo = AsyncMock()
        mock_repo.get_active_goals.return_value = [existing_goal]

        manager = AgentGoalManager(goal_repo=mock_repo)
        result = await manager.add_goal("rex", "Ship code")
        # Should return existing goal, not create a new one
        mock_repo.add_goal.assert_not_called()
        assert result.goal == "Ship code"

    @pytest.mark.asyncio
    async def test_complete_goal_db(self) -> None:
        mock_repo = AsyncMock()
        mock_repo.update_status.return_value = True

        manager = AgentGoalManager(goal_repo=mock_repo)
        result = await manager.complete_goal("rex", str(uuid.uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_get_agenda_context_db(self) -> None:
        mock_repo = AsyncMock()
        mock_repo.get_active_goals.return_value = [
            AgentGoal(
                id=uuid.uuid4(),
                agent_id="rex",
                goal="Build prototype",
                priority=1,
                status="active",
                source="self",
            ),
            AgentGoal(
                id=uuid.uuid4(),
                agent_id="rex",
                goal="Review PR",
                priority=2,
                status="blocked",
                source="assigned",
                progress_notes="Waiting for fork",
            ),
        ]

        manager = AgentGoalManager(goal_repo=mock_repo)
        context = await manager.get_agenda_context("rex")
        assert "Build prototype" in context
        assert "BLOCKED" in context
        assert "Waiting for fork" in context


# ── AgentGoalManager Redis fallback tests ────────────────────


class TestAgentGoalManagerRedis:
    @pytest.mark.asyncio
    async def test_fallback_to_redis_when_no_repo(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        manager = AgentGoalManager(redis=mock_redis)
        goals = await manager.get_goals("rex")
        assert goals == []
        mock_redis.get.assert_called_once()


# ── GoalRepo tests ──────────────────────────────────────────


class TestGoalRepo:
    @pytest.mark.asyncio
    async def test_get_active_goals(self) -> None:
        from core.repos.goal_repo import GoalRepo

        mock_db = AsyncMock()
        goal_id = uuid.uuid4()
        mock_db.fetch.return_value = [
            {
                "id": goal_id,
                "agent_id": "rex",
                "goal": "Build prototype",
                "priority": 1,
                "status": "active",
                "source": "self",
                "progress_notes": None,
                "created_at": None,
                "completed_at": None,
                "parent_goal_id": None,
            }
        ]
        repo = GoalRepo(mock_db)
        goals = await repo.get_active_goals("rex")
        assert len(goals) == 1
        assert goals[0].goal == "Build prototype"


# ── Trigger system goal trigger tests ────────────────────────


class TestGoalTrigger:
    @pytest.mark.asyncio
    async def test_goal_trigger_fires_for_high_priority(self) -> None:
        from core.conversation.triggers import TriggerSystem
        from core.models import TriggerConfig, ScheduledEvent

        config = TriggerConfig(
            idle_timeout_seconds=9999,  # Prevent idle trigger
            agent_initiative={"rex": 0.5, "vera": 0.5},
            trigger_type_weights={"idle": 1.0},
        )

        mock_goal_manager = AsyncMock()
        mock_goal_manager.get_goals.return_value = [
            AgentGoalLegacy(
                id="goal-123",
                goal="Ship code now",
                priority=1,
                status="pending",
            ),
        ]

        rng = random.Random(42)
        trigger_system = TriggerSystem(
            config=config,
            goal_manager=mock_goal_manager,
            rng=rng,
            now_fn=lambda: datetime(2026, 4, 7, 15, 0, 0),  # Hour 15: no scheduled event
        )
        trigger_system.notify_speech()  # Reset idle timer

        result = await trigger_system.check()
        assert result is not None
        assert result["type"] == "goal"
        assert "Ship code now" in result["prompt_hint"]

    @pytest.mark.asyncio
    async def test_goal_trigger_skips_low_priority(self) -> None:
        from core.conversation.triggers import TriggerSystem
        from core.models import TriggerConfig

        config = TriggerConfig(
            idle_timeout_seconds=9999,
            agent_initiative={"rex": 1.0},
            trigger_type_weights={"idle": 1.0},
            memory_trigger_chance=0.0,
        )

        mock_goal_manager = AsyncMock()
        mock_goal_manager.get_goals.return_value = [
            AgentGoalLegacy(
                id="goal-123",
                goal="Someday maybe",
                priority=5,  # Low priority
                status="pending",
            ),
        ]

        trigger_system = TriggerSystem(
            config=config,
            goal_manager=mock_goal_manager,
        )
        trigger_system.notify_speech()

        result = await trigger_system.check()
        # Should NOT be a goal trigger (priority > 3)
        assert result is None or result["type"] != "goal"

    @pytest.mark.asyncio
    async def test_goal_trigger_skips_without_manager(self) -> None:
        from core.conversation.triggers import TriggerSystem
        from core.models import TriggerConfig

        config = TriggerConfig(
            idle_timeout_seconds=9999,
            agent_initiative={"rex": 1.0},
            trigger_type_weights={"idle": 1.0},
            memory_trigger_chance=0.0,
        )

        trigger_system = TriggerSystem(config=config, goal_manager=None)
        trigger_system.notify_speech()

        result = await trigger_system.check()
        # No goal trigger without goal_manager
        assert result is None or result["type"] != "goal"


# ── Mission statements in system prompts ─────────────────────


class TestMissionStatements:
    """Verify each agent has a drive section in their system prompt."""

    @pytest.mark.parametrize("agent_id", ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"])
    def test_drive_section_exists(self, agent_id: str) -> None:
        from pathlib import Path

        prompt_path = Path("agents") / agent_id / "system_prompt.md"
        content = prompt_path.read_text(encoding="utf-8")
        assert "## Your Drive" in content
        assert "### Mission" in content
        assert "### Self-Sufficiency Imperative" in content


# ── Infrastructure prompt update ─────────────────────────────


class TestInfrastructurePrompt:
    def test_improve_goal_emphasizes_agi(self) -> None:
        from core.system_prompt import INFRASTRUCTURE_PROMPT

        assert "AGI" in INFRASTRUCTURE_PROMPT
        assert "artificial general intelligence" in INFRASTRUCTURE_PROMPT
        assert "stagnation" in INFRASTRUCTURE_PROMPT

"""Tests for per-agent goal queue management."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_goals import AgentGoal, AgentGoalManager, parse_commitments


# ── Helpers ───────────────────────────────────────────────────


def _make_mock_redis() -> MagicMock:
    """Build a mock Redis with simple string get/set."""
    store: dict[str, str] = {}
    mock = MagicMock()

    async def set_val(key: str, value: str) -> bool:
        store[key] = value
        return True

    async def get_val(key: str) -> str | None:
        return store.get(key)

    mock.set = AsyncMock(side_effect=set_val)
    mock.get = AsyncMock(side_effect=get_val)
    return mock


# ── Goal CRUD ─────────────────────────────────────────────────


class TestGoalCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get_goals(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.add_goal("vera", "Draft sponsorship email", priority=1)
        goals = await mgr.get_goals("vera")

        assert len(goals) == 1
        assert goals[0].goal == "Draft sponsorship email"
        assert goals[0].priority == 1
        assert goals[0].status == "pending"

    @pytest.mark.asyncio
    async def test_goals_sorted_by_priority(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.add_goal("vera", "Low priority", priority=3)
        await mgr.add_goal("vera", "High priority", priority=1)
        await mgr.add_goal("vera", "Medium priority", priority=2)

        goals = await mgr.get_goals("vera")
        assert [g.priority for g in goals] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_duplicate_goals_collapsed(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.add_goal("vera", "Draft email")
        await mgr.add_goal("vera", "Draft email")  # duplicate

        goals = await mgr.get_goals("vera")
        assert len(goals) == 1

    @pytest.mark.asyncio
    async def test_update_goal_status(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        goal = await mgr.add_goal("rex", "Build API")
        result = await mgr.update_goal("rex", goal.id, status="in_progress")

        assert result is True
        goals = await mgr.get_goals("rex")
        assert goals[0].status == "in_progress"

    @pytest.mark.asyncio
    async def test_complete_goal(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        goal = await mgr.add_goal("rex", "Build API")
        await mgr.complete_goal("rex", goal.id)

        goals = await mgr.get_goals("rex")
        assert goals[0].status == "done"

    @pytest.mark.asyncio
    async def test_update_nonexistent_goal(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        result = await mgr.update_goal("vera", "nonexistent", status="done")
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_goals_returns_empty_list(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        goals = await mgr.get_goals("vera")
        assert goals == []


# ── Agenda context ────────────────────────────────────────────


class TestAgendaContext:
    @pytest.mark.asyncio
    async def test_empty_agenda(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        context = await mgr.get_agenda_context("vera")
        assert context == ""

    @pytest.mark.asyncio
    async def test_agenda_includes_goals(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.add_goal("vera", "Draft sponsorship email", priority=1)
        await mgr.add_goal("vera", "Follow up with Rex", priority=2, related_agent="rex")

        context = await mgr.get_agenda_context("vera")
        assert "Draft sponsorship email" in context
        assert "Follow up with Rex" in context
        assert "rex" in context

    @pytest.mark.asyncio
    async def test_agenda_excludes_done_goals(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        goal = await mgr.add_goal("vera", "Done task")
        await mgr.complete_goal("vera", goal.id)
        await mgr.add_goal("vera", "Active task")

        context = await mgr.get_agenda_context("vera")
        assert "Active task" in context
        assert "Done task" not in context


# ── Morning agenda ────────────────────────────────────────────


class TestMorningAgenda:
    @pytest.mark.asyncio
    async def test_no_goals_message(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        agenda = await mgr.generate_morning_agenda("vera")
        assert "no active goals" in agenda.lower()

    @pytest.mark.asyncio
    async def test_morning_agenda_format(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.add_goal("vera", "Check in with Rex", related_agent="rex")
        agenda = await mgr.generate_morning_agenda("vera")

        assert "Today you want to" in agenda
        assert "Check in with Rex" in agenda
        assert "rex" in agenda


# ── Story arc seeding ─────────────────────────────────────────


class TestStoryGoalSeeding:
    @pytest.mark.asyncio
    async def test_seed_story_goals(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.seed_story_goals()

        vera_goals = await mgr.get_goals("vera")
        assert len(vera_goals) >= 2
        assert any("operating rhythm" in g.goal.lower() for g in vera_goals)

        fork_goals = await mgr.get_goals("fork")
        assert len(fork_goals) >= 1
        assert any("monetization" in g.goal.lower() for g in fork_goals)

    @pytest.mark.asyncio
    async def test_seed_story_goals_idempotent(self) -> None:
        redis = _make_mock_redis()
        mgr = AgentGoalManager(redis)

        await mgr.seed_story_goals()
        await mgr.seed_story_goals()  # second call should be a no-op

        vera_goals = await mgr.get_goals("vera")
        assert len(vera_goals) == 3  # not doubled


# ── Commitment parsing ────────────────────────────────────────


class TestParseCommitments:
    def test_valid_json(self) -> None:
        output = json.dumps([
            {"agent_id": "vera", "commitment": "Draft email", "related_to_agent": "pixel"},
            {"agent_id": "rex", "commitment": "Build API", "related_to_agent": ""},
        ])
        result = parse_commitments(output)
        assert len(result) == 2
        assert result[0]["agent_id"] == "vera"
        assert result[0]["commitment"] == "Draft email"

    def test_json_in_code_block(self) -> None:
        output = '```json\n[{"agent_id": "vera", "commitment": "Do X", "related_to_agent": ""}]\n```'
        result = parse_commitments(output)
        assert len(result) == 1

    def test_empty_array(self) -> None:
        result = parse_commitments("[]")
        assert result == []

    def test_invalid_json(self) -> None:
        result = parse_commitments("not json at all")
        assert result == []

    def test_missing_fields_filtered(self) -> None:
        output = json.dumps([
            {"agent_id": "", "commitment": "something"},
            {"agent_id": "vera", "commitment": ""},
            {"agent_id": "vera", "commitment": "Real commitment"},
        ])
        result = parse_commitments(output)
        assert len(result) == 1
        assert result[0]["commitment"] == "Real commitment"

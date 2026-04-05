"""Tests for ManageTaskTool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.shared_state import SharedTask, SharedWorkingState
from tools.task_management import ManageTaskTool


def _make_mock_redis() -> MagicMock:
    """Build a mock Redis that stores hashes in memory."""
    hashes: dict[str, dict[str, str]] = {}

    mock = MagicMock()

    async def hset(key: str, field: str, value: str) -> int:
        hashes.setdefault(key, {})[field] = value
        return 1

    async def hget(key: str, field: str) -> str | None:
        return hashes.get(key, {}).get(field)

    async def hgetall(key: str) -> dict[str, str]:
        return dict(hashes.get(key, {}))

    mock.hset = AsyncMock(side_effect=hset)
    mock.hget = AsyncMock(side_effect=hget)
    mock.hgetall = AsyncMock(side_effect=hgetall)

    return mock


@pytest.mark.asyncio
async def test_list_tasks_empty():
    redis = _make_mock_redis()
    state = SharedWorkingState(redis)
    tool = ManageTaskTool(shared_state=state, agent_id="vera")

    result = await tool.execute(action="list_tasks")
    assert result["status"] == "ok"
    assert result["tasks"] == []


@pytest.mark.asyncio
async def test_create_task():
    redis = _make_mock_redis()
    state = SharedWorkingState(redis)
    tool = ManageTaskTool(shared_state=state, agent_id="vera")

    result = await tool.execute(action="create_task", title="Build revenue dashboard")
    assert result["status"] == "ok"
    assert result["owner"] == "vera"
    assert "task_id" in result

    # Verify task appears in list
    list_result = await tool.execute(action="list_tasks")
    assert len(list_result["tasks"]) == 1
    assert list_result["tasks"][0]["title"] == "Build revenue dashboard"


@pytest.mark.asyncio
async def test_update_task_status():
    redis = _make_mock_redis()
    state = SharedWorkingState(redis)
    tool = ManageTaskTool(shared_state=state, agent_id="rex")

    # Create a task first
    create_result = await tool.execute(action="create_task", title="Write API endpoint")
    task_id = create_result["task_id"]

    # Update status
    result = await tool.execute(action="update_status", task_id=task_id, status="in_progress")
    assert result["status"] == "ok"

    # Verify
    list_result = await tool.execute(action="list_tasks")
    assert list_result["tasks"][0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_create_task_requires_title():
    redis = _make_mock_redis()
    state = SharedWorkingState(redis)
    tool = ManageTaskTool(shared_state=state, agent_id="vera")

    result = await tool.execute(action="create_task")
    assert result["status"] == "error"
    assert "title" in result["reason"]

"""Extended tests for tools/task_management.py — claim_task, blocked status, error paths.

Basic tests (list/create/update/missing title) are in test_task_tool.py;
this file covers the remaining gaps.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from tools.task_management import ManageTaskTool


def _make_mock_shared_state() -> AsyncMock:
    state = AsyncMock()
    state.get_tasks = AsyncMock(return_value=[])
    state.add_task = AsyncMock()
    state.update_task_status = AsyncMock(return_value=True)
    state.claim_task = AsyncMock(return_value={"status": "ok", "owner": "rex"})
    return state


class TestClaimTask:
    async def test_claim_task_success(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="rex")

        result = await tool.execute(action="claim_task", task_id="task-abc")
        assert result["status"] == "ok"
        assert result["new_owner"] == "rex"
        state.claim_task.assert_called_once_with("task-abc", "rex")

    async def test_claim_task_already_claimed_informs_loser(self) -> None:
        state = _make_mock_shared_state()
        state.claim_task.return_value = {"status": "already_claimed", "owner": "aurora"}

        tool = ManageTaskTool(shared_state=state, agent_id="rex")
        result = await tool.execute(action="claim_task", task_id="task-abc")
        # Loser must NOT receive "ok" — it must learn who took the task.
        assert result["status"] == "already_claimed"
        assert result["owner"] == "aurora"
        assert result["task_id"] == "task-abc"

    async def test_claim_task_not_found(self) -> None:
        state = _make_mock_shared_state()
        state.claim_task.return_value = {"status": "not_found"}

        tool = ManageTaskTool(shared_state=state, agent_id="rex")
        result = await tool.execute(action="claim_task", task_id="task-missing")
        assert result["status"] == "error"
        assert "not found" in result["reason"].lower()

    async def test_claim_task_missing_id(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="rex")

        result = await tool.execute(action="claim_task")
        assert result["status"] == "error"
        assert "task_id" in result["reason"]


class TestCreateTaskOwnership:
    async def test_create_task_default_is_unowned(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="vera")

        result = await tool.execute(action="create_task", title="Build a well")
        assert result["status"] == "ok"
        # Open proposal: no owner until someone claims it.
        assert result["owner"] is None
        created = state.add_task.call_args.args[0]
        assert created.owner is None
        assert created.status == "pending"

    async def test_create_task_claim_true_is_self_owned(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="vera")

        result = await tool.execute(action="create_task", title="Build a well", claim=True)
        assert result["status"] == "ok"
        assert result["owner"] == "vera"
        created = state.add_task.call_args.args[0]
        assert created.owner == "vera"
        assert created.status == "in_progress"


class TestUpdateStatusEdgeCases:
    async def test_blocked_status_with_reason(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="rex")

        result = await tool.execute(
            action="update_status",
            task_id="task-abc",
            status="blocked",
            blocked_reason="Waiting for API key",
        )
        assert result["status"] == "ok"
        assert result["new_status"] == "blocked"
        state.update_task_status.assert_called_once_with(
            "task-abc",
            "blocked",
            "Waiting for API key",
        )

    async def test_update_status_not_found(self) -> None:
        state = _make_mock_shared_state()
        state.update_task_status.return_value = False

        tool = ManageTaskTool(shared_state=state, agent_id="rex")
        result = await tool.execute(
            action="update_status",
            task_id="task-missing",
            status="done",
        )
        assert result["status"] == "error"
        assert "not found" in result["reason"].lower()

    async def test_update_status_missing_params(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="rex")

        result = await tool.execute(action="update_status", task_id="task-abc")
        assert result["status"] == "error"
        assert "status" in result["reason"]

        result2 = await tool.execute(action="update_status", status="done")
        assert result2["status"] == "error"
        assert "task_id" in result2["reason"]


class TestUnknownAction:
    async def test_unknown_action(self) -> None:
        state = _make_mock_shared_state()
        tool = ManageTaskTool(shared_state=state, agent_id="rex")

        result = await tool.execute(action="delete_task")
        assert result["status"] == "error"
        assert "unknown" in result["reason"].lower()

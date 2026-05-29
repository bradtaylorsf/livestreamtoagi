"""E21-7g: bridge task-board ops let embodied bots drive the shared task list.

Covers the new ``shared_state.write`` operations (task_create / task_claim /
task_complete / task_list) wired for the Mindcraft ``!manageTask`` command, plus
the task-board section rendered into the agent context summary so bots can
observe open work to claim.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bridge.contract import BridgeRequest, CostContext
from core.bridge.handlers.shared_state import handle_shared_state_write
from core.shared_state import SharedWorkingState


def _make_redis() -> MagicMock:
    """In-memory Redis fake with SET NX support (required by claim_task)."""
    hashes: dict[str, dict[str, str]] = {}
    strings: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    mock = MagicMock()

    async def rpush(key: str, value: str) -> int:
        lists.setdefault(key, []).append(value)
        return len(lists[key])

    async def lrange(key: str, start: int, stop: int) -> list[str]:
        data = lists.get(key, [])
        return data[start:] if stop == -1 else data[start : stop + 1]

    async def hset(key: str, field: str, value: str) -> int:
        hashes.setdefault(key, {})[field] = value
        return 1

    async def hget(key: str, field: str) -> str | None:
        return hashes.get(key, {}).get(field)

    async def hgetall(key: str) -> dict[str, str]:
        return dict(hashes.get(key, {}))

    async def hdel(key: str, field: str) -> int:
        return 1 if hashes.get(key, {}).pop(field, None) is not None else 0

    async def set_str(key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in strings:
            return False
        strings[key] = value
        return True

    async def get_str(key: str) -> str | None:
        return strings.get(key)

    mock.hset = AsyncMock(side_effect=hset)
    mock.hget = AsyncMock(side_effect=hget)
    mock.hgetall = AsyncMock(side_effect=hgetall)
    mock.hdel = AsyncMock(side_effect=hdel)
    mock.rpush = AsyncMock(side_effect=rpush)
    mock.lrange = AsyncMock(side_effect=lrange)
    mock.set = AsyncMock(side_effect=set_str)
    mock.get = AsyncMock(side_effect=get_str)
    return mock


def _services(state: SharedWorkingState) -> SimpleNamespace:
    # redis=None forces _state_for_request to use the supplied shared state.
    return SimpleNamespace(redis=None, shared_working_state=state)


def _env(agent_id: str, **payload: object) -> BridgeRequest:
    return BridgeRequest(
        version="1.7",
        request_id="req-task-test",
        agent_id=agent_id,
        run_id="run-test",
        simulation_id="sim-task-test",
        service="shared_state",
        method="write",
        payload=payload,
        deadline_ms=1000,
        cost_context=CostContext(
            agent_tier="conversation",
            budget_bucket="shared-state",
            estimated_cost_usd=0.0,
        ),
    )


@pytest.mark.asyncio
async def test_task_create_opens_unclaimed_task() -> None:
    state = SharedWorkingState(_make_redis())
    result = await handle_shared_state_write(
        _env("vera", operation="task_create", task_title="build a watchtower"),
        _services(state),
    )
    assert result["accepted"] is True
    assert result["task_status"] == "created"
    task_id = result["task_id"]
    assert task_id and task_id.startswith("task-")

    tasks = await state.get_tasks()
    assert len(tasks) == 1
    # Created OPEN so any agent (not just the proposer) can claim it.
    assert tasks[0].owner is None
    assert tasks[0].status == "pending"
    assert tasks[0].title == "build a watchtower"


@pytest.mark.asyncio
async def test_task_create_requires_title() -> None:
    state = SharedWorkingState(_make_redis())
    with pytest.raises(ValueError, match="task_create requires task_title"):
        await handle_shared_state_write(
            _env("vera", operation="task_create", task_title="   "),
            _services(state),
        )


@pytest.mark.asyncio
async def test_task_claim_first_wins_second_sees_owner() -> None:
    state = SharedWorkingState(_make_redis())
    created = await handle_shared_state_write(
        _env("vera", operation="task_create", task_title="gather oak"),
        _services(state),
    )
    task_id = created["task_id"]

    won = await handle_shared_state_write(
        _env("rex", operation="task_claim", task_id=task_id),
        _services(state),
    )
    assert won["task_status"] == "ok"
    assert won["task_owner"] == "rex"

    lost = await handle_shared_state_write(
        _env("aurora", operation="task_claim", task_id=task_id),
        _services(state),
    )
    assert lost["task_status"] == "already_claimed"
    assert lost["task_owner"] == "rex"

    tasks = {t.id: t for t in await state.get_tasks()}
    assert tasks[task_id].owner == "rex"
    assert tasks[task_id].status == "in_progress"


@pytest.mark.asyncio
async def test_task_complete_marks_done() -> None:
    state = SharedWorkingState(_make_redis())
    created = await handle_shared_state_write(
        _env("rex", operation="task_create", task_title="raise a wall"),
        _services(state),
    )
    task_id = created["task_id"]
    await handle_shared_state_write(
        _env("rex", operation="task_claim", task_id=task_id), _services(state)
    )
    done = await handle_shared_state_write(
        _env("rex", operation="task_complete", task_id=task_id, task_evidence="wall at 0,64,0"),
        _services(state),
    )
    assert done["task_status"] == "done"
    tasks = {t.id: t for t in await state.get_tasks()}
    assert tasks[task_id].status == "done"


@pytest.mark.asyncio
async def test_task_complete_missing_task() -> None:
    state = SharedWorkingState(_make_redis())
    res = await handle_shared_state_write(
        _env("rex", operation="task_complete", task_id="task-ghost"),
        _services(state),
    )
    assert res["task_status"] == "not_found"


@pytest.mark.asyncio
async def test_summary_renders_task_board() -> None:
    state = SharedWorkingState(_make_redis())
    await handle_shared_state_write(
        _env("vera", operation="task_create", task_title="dig a well"),
        _services(state),
    )
    listed = await handle_shared_state_write(_env("vera", operation="task_list"), _services(state))
    # task_list surfaces the board through the formatted summary.
    assert "Shared task board" in listed["formatted"]
    assert "dig a well" in listed["formatted"]
    assert "OPEN" in listed["formatted"]

    summary = await state.get_summary_for_context()
    assert "Shared task board" in summary
    assert "!manageTask" in summary
    assert "dig a well" in summary

"""Tests for SharedWorkingState Redis-backed shared state."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.bridge.contract import BridgeRequest, CostContext
from core.bridge.handlers.shared_state import handle_shared_state_write
from core.shared_state import (
    Decision,
    SettlementObjective,
    SharedTask,
    SharedWorkingState,
)

# ── Helpers ───────────────────────────────────────────────────


def _make_mock_redis() -> MagicMock:
    """Build a mock Redis that stores hashes, lists, and strings in memory."""
    hashes: dict[str, dict[str, str]] = {}
    lists: dict[str, list[str]] = {}
    strings: dict[str, str] = {}

    mock = MagicMock()

    async def hset(key: str, field: str, value: str) -> int:
        hashes.setdefault(key, {})[field] = value
        return 1

    async def hget(key: str, field: str) -> str | None:
        return hashes.get(key, {}).get(field)

    async def hgetall(key: str) -> dict[str, str]:
        return dict(hashes.get(key, {}))

    async def rpush(key: str, value: str) -> int:
        lists.setdefault(key, []).append(value)
        return len(lists[key])

    async def lrange(key: str, start: int, stop: int) -> list[str]:
        data = lists.get(key, [])
        if stop == -1:
            return data[start:]
        return data[start : stop + 1]

    async def set_str(key: str, value: str) -> bool:
        strings[key] = value
        return True

    async def get_str(key: str) -> str | None:
        return strings.get(key)

    mock.hset = AsyncMock(side_effect=hset)
    mock.hget = AsyncMock(side_effect=hget)
    mock.hgetall = AsyncMock(side_effect=hgetall)
    mock.rpush = AsyncMock(side_effect=rpush)
    mock.lrange = AsyncMock(side_effect=lrange)
    mock.set = AsyncMock(side_effect=set_str)
    mock.get = AsyncMock(side_effect=get_str)

    return mock


# ── Tests ─────────────────────────────────────────────────────


class TestSharedTaskCRUD:
    """SharedWorkingState task operations."""

    @pytest.mark.asyncio
    async def test_add_and_get_tasks(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        task = SharedTask(id="t1", title="Build dashboard", owner="rex")
        await state.add_task(task)

        tasks = await state.get_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "t1"
        assert tasks[0].title == "Build dashboard"
        assert tasks[0].owner == "rex"
        assert tasks[0].status == "pending"

    @pytest.mark.asyncio
    async def test_update_task_status(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        task = SharedTask(id="t1", title="Build dashboard", owner="rex")
        await state.add_task(task)
        await state.update_task_status("t1", "blocked", blocked_reason="waiting on API")

        tasks = await state.get_tasks()
        assert tasks[0].status == "blocked"
        assert tasks[0].blocked_reason == "waiting on API"

    @pytest.mark.asyncio
    async def test_update_nonexistent_task_is_noop(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        # Should not raise
        await state.update_task_status("nonexistent", "done")


class TestDecisionCRUD:
    """SharedWorkingState decision operations."""

    @pytest.mark.asyncio
    async def test_add_and_get_decisions(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        d = Decision(summary="Agreed to build a dashboard first", made_by=["vera", "rex"])
        await state.add_decision(d)

        decisions = await state.get_recent_decisions(5)
        assert len(decisions) == 1
        assert decisions[0].summary == "Agreed to build a dashboard first"
        assert "vera" in decisions[0].made_by

    @pytest.mark.asyncio
    async def test_get_recent_decisions_limits_count(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        for i in range(10):
            await state.add_decision(Decision(summary=f"Decision {i}", made_by=["vera"]))

        decisions = await state.get_recent_decisions(3)
        assert len(decisions) == 3


class TestPriorities:
    """SharedWorkingState priorities operations."""

    @pytest.mark.asyncio
    async def test_set_and_get_priorities(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        await state.set_priorities(["revenue", "content"], set_by="vera")
        p = await state.get_priorities()

        assert p is not None
        assert p["priorities"] == ["revenue", "content"]
        assert p["set_by"] == "vera"

    @pytest.mark.asyncio
    async def test_get_priorities_returns_none_when_unset(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        assert await state.get_priorities() is None


class TestSeedInitialTasks:
    """SharedWorkingState.seed_initial_tasks()."""

    @pytest.mark.asyncio
    async def test_seed_initial_tasks_populates_board(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        await state.seed_initial_tasks()
        tasks = await state.get_tasks()

        assert len(tasks) == 7
        owners = {t.owner for t in tasks}
        assert owners == {"vera", "rex", "pixel", "fork", "sentinel", "aurora", "grok"}
        assert all(t.status == "pending" for t in tasks)

    @pytest.mark.asyncio
    async def test_seed_initial_tasks_idempotent(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        await state.seed_initial_tasks()
        await state.seed_initial_tasks()  # second call should be a no-op

        tasks = await state.get_tasks()
        assert len(tasks) == 7


class TestSettlementObjectives:
    """SharedWorkingState settlement objective operations."""

    @pytest.mark.asyncio
    async def test_blocked_objective_advances_active_phase(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await state.set_settlement_objectives(
            [
                SettlementObjective(
                    objective_id="phase-1-watch-tower",
                    phase_index=0,
                    description="watch tower",
                    status="blocked",
                    owner_agent_id="aurora",
                    verified_blocks=13,
                    completion_ratio=0.68,
                ),
                SettlementObjective(
                    objective_id="phase-2-mine-staging",
                    phase_index=1,
                    description="mine staging yard",
                    status="pending",
                    owner_agent_id="rex",
                ),
            ]
        )

        active = await state.get_active_settlement_objective()

        assert active is not None
        assert active.objective_id == "phase-2-mine-staging"

    @pytest.mark.asyncio
    async def test_completed_objective_does_not_regress_on_stale_assign(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await state.set_settlement_objectives(
            [
                SettlementObjective(
                    objective_id="phase-1-starter-cabin",
                    phase_index=0,
                    description="starter cabin",
                    status="completed",
                    owner_agent_id="fork",
                    verified_blocks=12,
                    completion_ratio=1.0,
                )
            ]
        )

        updated = await state.assign_settlement_objective_owner(
            "phase-1-starter-cabin",
            "rex",
            reason="stale_director_context",
        )

        assert updated is not None
        assert updated.status == "completed"
        assert updated.owner_agent_id == "fork"
        objectives = await state.get_settlement_objectives()
        assert objectives[0].status == "completed"
        assert objectives[0].verified_blocks == 12

    @pytest.mark.asyncio
    async def test_completed_objective_does_not_regress_on_stale_blocked_advance(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await state.set_settlement_objectives(
            [
                SettlementObjective(
                    objective_id="phase-1-starter-cabin",
                    phase_index=0,
                    description="starter cabin",
                    status="completed",
                    owner_agent_id="fork",
                    verified_blocks=12,
                    completion_ratio=1.0,
                )
            ]
        )

        updated = await state.advance_settlement_objective(
            "phase-1-starter-cabin",
            status="blocked",
            verified_blocks=2,
            completion_ratio=0.5,
            evidence={"action_id": "stale-plan"},
        )

        assert updated is not None
        assert updated.status == "completed"
        objectives = await state.get_settlement_objectives()
        assert objectives[0].status == "completed"
        assert objectives[0].verified_blocks == 12
        assert objectives[0].completion_ratio == 1.0
        assert "action_id" not in objectives[0].evidence


class TestAdvanceSettlementObjective:
    """Positive-latch behavior of advance_settlement_objective (#904)."""

    @staticmethod
    async def _seed_in_progress(state: SharedWorkingState) -> None:
        await state.set_settlement_objectives(
            [
                SettlementObjective(
                    objective_id="phase-1-starter-cabin",
                    phase_index=0,
                    description="starter cabin",
                    status="in_progress",
                    owner_agent_id="fork",
                    verified_blocks=13,
                    completion_ratio=0.4,
                )
            ]
        )

    @pytest.mark.asyncio
    async def test_high_ratio_advance_latches_completed(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await self._seed_in_progress(state)

        # A blocked advance that nonetheless cleared the bar must latch completed.
        updated = await state.advance_settlement_objective(
            "phase-1-starter-cabin",
            status="blocked",
            verified_blocks=31,
            completion_ratio=0.969,
            evidence={"action_id": "high-ratio"},
        )

        assert updated is not None
        assert updated.status == "completed"
        assert updated.completed_at is not None

        # A later lower-ratio advance must not revert it (existing demotion guard).
        again = await state.advance_settlement_objective(
            "phase-1-starter-cabin",
            status="blocked",
            verified_blocks=13,
            completion_ratio=0.5,
        )

        assert again is not None
        assert again.status == "completed"
        objectives = await state.get_settlement_objectives()
        assert objectives[0].status == "completed"
        assert objectives[0].completion_ratio == 0.969

    @pytest.mark.asyncio
    async def test_latch_bar_honors_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Raise the bar above the incoming ratio: the advance must NOT latch.
        monkeypatch.setenv("MC_SIM_SETTLEMENT_COMPLETE_RATIO", "0.99")
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await self._seed_in_progress(state)

        updated = await state.advance_settlement_objective(
            "phase-1-starter-cabin",
            status="blocked",
            completion_ratio=0.969,
        )

        assert updated is not None
        assert updated.status == "blocked"
        assert updated.completed_at is None

    @pytest.mark.asyncio
    async def test_abandoned_status_round_trips(self) -> None:
        # The 'abandoned' status (used by JS reassignment writes) must survive
        # normalization instead of being silently demoted to 'pending'.
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await self._seed_in_progress(state)

        updated = await state.advance_settlement_objective(
            "phase-1-starter-cabin",
            status="abandoned",
            completion_ratio=0.1,
        )

        assert updated is not None
        assert updated.status == "abandoned"


class TestSettlementObjectiveAdvanceBridge:
    """Bridge handler plumbing for settlement_objective_advance (#904)."""

    @staticmethod
    def _services(state: SharedWorkingState) -> SimpleNamespace:
        return SimpleNamespace(redis=None, shared_working_state=state)

    @staticmethod
    def _advance_env(objective: dict[str, object]) -> BridgeRequest:
        return BridgeRequest(
            version="1.7",
            request_id="req-advance-test",
            agent_id="fork",
            run_id="run-test",
            simulation_id="sim-advance-test",
            service="shared_state",
            method="write",
            payload={
                "operation": "settlement_objective_advance",
                "settlement_objective": objective,
            },
            deadline_ms=1000,
            cost_context=CostContext(
                agent_tier="conversation",
                budget_bucket="shared-state",
                estimated_cost_usd=0.0,
            ),
        )

    @pytest.mark.asyncio
    async def test_no_match_advance_error_includes_objective_id(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        # No objectives seeded -> the advance cannot match.
        env = self._advance_env(
            {
                "objective_id": "phase-9-ghost",
                "phase_index": 8,
                "description": "ghost objective",
                "status": "blocked",
            }
        )

        with pytest.raises(ValueError) as excinfo:
            await handle_shared_state_write(env, self._services(state))

        message = str(excinfo.value)
        assert "phase-9-ghost" in message
        assert "blocked" in message

    @pytest.mark.asyncio
    async def test_build_exception_blocked_advance_records_on_ledger(self) -> None:
        # Mirrors the JS throw-path emit: a build exception sends a blocked
        # advance for the back-filled objective so it does not stay in_progress.
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        await state.set_settlement_objectives(
            [
                SettlementObjective(
                    objective_id="phase-1-starter-cabin",
                    phase_index=0,
                    description="starter cabin",
                    status="in_progress",
                    owner_agent_id="fork",
                )
            ]
        )
        env = self._advance_env(
            {
                "objective_id": "phase-1-starter-cabin",
                "phase_index": 0,
                "description": "starter cabin",
                "owner_agent_id": "fork",
                "status": "blocked",
                "reassign_reason": "build_exception",
                "evidence": {"error": "RconBuildExecutor crashed"},
            }
        )

        result = await handle_shared_state_write(env, self._services(state))

        assert result["accepted"] is True
        objectives = await state.get_settlement_objectives()
        assert objectives[0].status == "blocked"
        assert objectives[0].evidence.get("error") == "RconBuildExecutor crashed"


class TestGetSummaryForContext:
    """get_summary_for_context formatting."""

    @pytest.mark.asyncio
    async def test_empty_state_returns_empty_string(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)
        assert await state.get_summary_for_context() == ""

    @pytest.mark.asyncio
    async def test_includes_priorities_tasks_decisions(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        await state.set_priorities(["ship MVP"], set_by="vera")
        await state.add_task(SharedTask(id="t1", title="Build API", owner="rex"))
        await state.add_decision(Decision(summary="Use FastAPI", made_by=["rex", "fork"]))

        summary = await state.get_summary_for_context()

        assert "Current priorities" in summary
        assert "ship MVP" in summary
        assert "Active tasks" in summary
        assert "Build API" in summary
        assert "Recent decisions" in summary
        assert "Use FastAPI" in summary

    @pytest.mark.asyncio
    async def test_done_tasks_excluded_from_active(self) -> None:
        redis = _make_mock_redis()
        state = SharedWorkingState(redis)

        await state.add_task(SharedTask(id="t1", title="Done task", owner="rex", status="done"))
        await state.add_task(SharedTask(id="t2", title="Active task", owner="aurora"))

        summary = await state.get_summary_for_context()
        assert "Active task" in summary
        assert "Done task" not in summary

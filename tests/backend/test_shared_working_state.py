"""Tests for embodied shared task/world-state blackboard."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.bridge import contract as c
from core.bridge.server import build_bridge_response_with_services
from core.event_bus import EventType, event_bus
from core.redis_keys import ScopedRedis
from core.shared_state import (
    AgentClaim,
    BuildSite,
    DangerReport,
    GroupGoal,
    NextStep,
    ResourceEntry,
    SettlementObjective,
    SharedTask,
    SharedWorkingState,
    VerifiedAction,
)


class _MemoryRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}

    async def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key: str, *fields: str) -> int:
        bucket = self.hashes.get(key, {})
        removed = 0
        for field in fields:
            if field in bucket:
                del bucket[field]
                removed += 1
        return removed

    async def rpush(self, key: str, *values: str) -> int:
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        data = self.lists.get(key, [])
        if start < 0:
            start = max(len(data) + start, 0)
        if stop < 0:
            stop = len(data) + stop
        return data[start : stop + 1]

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        data = self.lists.get(key, [])
        if start < 0:
            start = max(len(data) + start, 0)
        if stop < 0:
            stop = len(data) + stop
        self.lists[key] = data[start : stop + 1]
        return True

    async def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        del ex
        if nx and key in self.strings:
            return False
        self.strings[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.strings.pop(key, None) is not None)
            removed += int(self.hashes.pop(key, None) is not None)
            removed += int(self.lists.pop(key, None) is not None)
        return removed


def _state(redis: _MemoryRedis | None = None, simulation_id: uuid.UUID | None = None):
    raw = redis or _MemoryRedis()
    sim_id = simulation_id or uuid.uuid4()
    return SharedWorkingState(ScopedRedis(raw, sim_id)), raw, sim_id


def _bridge_request(
    *,
    agent_id: str,
    simulation_id: uuid.UUID,
    method: str,
    payload: dict,
) -> dict:
    return {
        "version": c.PROTOCOL_VERSION,
        "request_id": f"req-{method}-{agent_id}",
        "agent_id": agent_id,
        "run_id": "run-shared-state-test",
        "simulation_id": str(simulation_id),
        "service": "shared_state",
        "method": method,
        "payload": payload,
        "deadline_ms": 3000,
        "cost_context": {
            "agent_tier": "conversation",
            "budget_bucket": "shared-state-test",
            "estimated_cost_usd": 0.0,
        },
    }


@pytest.mark.asyncio
async def test_embodied_blackboard_round_trips_all_entity_types() -> None:
    state, _, _ = _state()

    await state.set_group_goal(GroupGoal(text="Build a safe camp", set_by="vera"))
    await state.upsert_resource(
        ResourceEntry(
            id="woodpile",
            kind="oak_log",
            location={"x": 1, "y": 64, "z": 2},
            quantity=12,
            reported_by="rex",
        )
    )
    await state.set_agent_claim(
        AgentClaim(agent_id="rex", target="camp-frame", role="builder", claimed_by="rex")
    )
    await state.report_danger(
        DangerReport(agent_id="aurora", kind="stuck", location="east ridge", severity=2)
    )
    await state.record_verified_action(
        VerifiedAction(agent_id="rex", action="placed oak frame", result="verified")
    )
    await state.set_build_site(
        BuildSite(site_id="camp", location={"x": 3, "y": 64, "z": 4}, name="Camp", status="open")
    )
    await state.add_next_step(NextStep(text="Pixel lights the entry", added_by="pixel"))

    assert (await state.get_group_goal()).text == "Build a safe camp"  # type: ignore[union-attr]
    assert (await state.get_resources())[0].reported_by == "rex"
    assert (await state.get_agent_claims())[0].target == "camp-frame"
    assert (await state.get_danger_reports())[0].kind == "stuck"
    assert (await state.get_recent_verified_actions())[0].result == "verified"
    assert (await state.get_build_site()).site_id == "camp"  # type: ignore[union-attr]
    assert (await state.get_next_steps())[0].added_by == "pixel"

    summary = await state.get_summary_for_context()
    assert "Active group goal" in summary
    assert "Known resources" in summary
    assert "Agent claims" in summary
    assert "Recent verified actions" in summary


@pytest.mark.asyncio
async def test_danger_reports_dispatch_rescue_task_and_resolve() -> None:
    state, _, _ = _state()

    await state.report_danger(
        DangerReport(
            agent_id="aurora",
            kind="drowning",
            location={"x": 1, "y": 62, "z": 2},
            severity=5,
        )
    )
    danger = (await state.get_unresolved_dangers())[0]

    task = await state.dispatch_rescue_task(
        danger.danger_id,
        rescuer_id="rex",
        strategy="navigate",
        mode="standard",
    )
    assert task is not None
    assert task.owner == "rex"
    assert task.id == f"rescue-{danger.danger_id}"

    unresolved = await state.get_unresolved_dangers()
    assert unresolved[0].recovery_status == "rescue_dispatched"
    assert unresolved[0].rescuer_id == "rex"

    resolved = await state.mark_danger_resolved(
        danger_id=danger.danger_id,
        rescuer_id="rex",
        recovery_status="resolved",
    )
    assert resolved is not None
    assert resolved.resolved_at is not None
    assert await state.get_unresolved_dangers() == []


@pytest.mark.asyncio
async def test_two_agents_coordinate_through_shared_state() -> None:
    state_a, redis, sim_id = _state()
    state_b = SharedWorkingState(ScopedRedis(redis, sim_id))

    await state_a.set_agent_claim(
        AgentClaim(agent_id="vera", target="camp", role="planner", claimed_by="vera")
    )
    await state_a.upsert_resource(
        ResourceEntry(
            id="torches",
            kind="torch",
            location="starter chest",
            quantity=8,
            reported_by="vera",
        )
    )

    summary = await state_b.get_summary_for_context()
    assert "vera: planner on camp" in summary
    assert "torch x8 at starter chest" in summary


@pytest.mark.asyncio
async def test_shared_state_is_scoped_by_simulation_id() -> None:
    redis = _MemoryRedis()
    sim_a = uuid.uuid4()
    sim_b = uuid.uuid4()
    state_a = SharedWorkingState(ScopedRedis(redis, sim_a))
    state_b = SharedWorkingState(ScopedRedis(redis, sim_b))

    await state_a.set_group_goal(GroupGoal(text="Build north camp", set_by="vera"))
    await state_b.set_group_goal(GroupGoal(text="Scout south valley", set_by="rex"))

    assert (await state_a.get_group_goal()).text == "Build north camp"  # type: ignore[union-attr]
    assert (await state_b.get_group_goal()).text == "Scout south valley"  # type: ignore[union-attr]
    assert f"sim:{sim_a}:shared:goal" in redis.strings
    assert f"sim:{sim_b}:shared:goal" in redis.strings


@pytest.mark.asyncio
async def test_claims_are_advisory_but_writer_is_audited_by_bridge() -> None:
    redis = _MemoryRedis()
    sim_id = uuid.uuid4()
    services = SimpleNamespace(redis=redis)

    response = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="vera",
            simulation_id=sim_id,
            method="write",
            payload={
                "operation": "claim_set",
                "claim": {
                    "agent_id": "rex",
                    "target": "camp-roof",
                    "role": "builder",
                    "claimed_by": "rex",
                },
            },
        ),
        services,
    )

    assert response.ok is True
    state = SharedWorkingState(ScopedRedis(redis, sim_id))
    claims = await state.get_agent_claims()
    assert claims[0].agent_id == "rex"
    assert claims[0].claimed_by == "vera"


@pytest.mark.asyncio
async def test_verified_actions_are_trimmed_to_recent_window() -> None:
    state, _, _ = _state()

    for i in range(30):
        await state.record_verified_action(
            VerifiedAction(agent_id="rex", action=f"action-{i}", result="ok")
        )

    actions = await state.get_recent_verified_actions(30)
    assert len(actions) == 25
    assert actions[0].action == "action-5"
    assert actions[-1].action == "action-29"


@pytest.mark.asyncio
async def test_bridge_read_write_returns_run_scoped_blackboard_summary() -> None:
    redis = _MemoryRedis()
    sim_id = uuid.uuid4()
    services = SimpleNamespace(redis=redis, shared_working_state=None)

    write = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="vera",
            simulation_id=sim_id,
            method="write",
            payload={
                "operation": "goal_set",
                "goal": {"text": "Raise a signal tower", "set_by": "untrusted"},
            },
        ),
        services,
    )
    assert write.ok is True
    assert "Raise a signal tower" in write.payload["formatted"]  # type: ignore[index]

    read = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="rex",
            simulation_id=sim_id,
            method="read",
            payload={},
        ),
        services,
    )
    assert read.ok is True
    assert read.payload["goal"]["set_by"] == "vera"  # type: ignore[index]
    assert "Active group goal" in read.payload["formatted"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_bridge_danger_report_emits_distress_and_rescue_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _MemoryRedis()
    sim_id = uuid.uuid4()
    services = SimpleNamespace(redis=redis)
    seen: list[dict] = []

    async def on_distress(event: dict) -> None:
        seen.append(event["data"])

    monkeypatch.setenv("RESCUE_MODE", "easy")
    event_bus.on(EventType.DISTRESS_REPORTED, on_distress)
    try:
        response = await build_bridge_response_with_services(
            _bridge_request(
                agent_id="aurora",
                simulation_id=sim_id,
                method="write",
                payload={
                    "operation": "danger_report",
                    "danger": {
                        "agent_id": "aurora",
                        "kind": "stuck",
                        "location": {"x": 3, "y": 63, "z": -4},
                        "severity": 4,
                    },
                },
            ),
            services,
        )
    finally:
        event_bus.off(EventType.DISTRESS_REPORTED, on_distress)

    assert response.ok is True
    assert seen
    assert seen[0]["rescue_mode"] == "easy"
    assert seen[0]["rescue_strategy"] == "teleport_op"
    c.RescueTaskRequest.model_validate(seen[0]["rescue_request"])
    assert seen[0]["rescue_request"]["target_agent_id"] == "aurora"
    assert seen[0]["rescue_task"]["owner"] != "aurora"

    state = SharedWorkingState(ScopedRedis(redis, sim_id))
    dangers = await state.get_unresolved_dangers()
    tasks = await state.get_tasks()
    assert dangers[0].kind == "stuck"
    assert dangers[0].recovery_status == "rescue_dispatched"
    assert tasks[0].id == f"rescue-{dangers[0].danger_id}"


@pytest.mark.asyncio
async def test_bridge_danger_resolve_clears_unresolved_distress() -> None:
    redis = _MemoryRedis()
    sim_id = uuid.uuid4()
    services = SimpleNamespace(redis=redis)
    state = SharedWorkingState(ScopedRedis(redis, sim_id))
    await state.report_danger(
        DangerReport(agent_id="pixel", kind="trapped", location="pit", severity=4)
    )
    danger = (await state.get_unresolved_dangers())[0]

    response = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="rex",
            simulation_id=sim_id,
            method="write",
            payload={
                "operation": "danger_resolve",
                "danger_resolution": {
                    "danger_id": danger.danger_id,
                    "rescuer_id": "rex",
                    "recovery_status": "escaped",
                },
            },
        ),
        services,
    )

    assert response.ok is True
    assert await state.get_unresolved_dangers() == []


@pytest.mark.asyncio
async def test_bridge_shared_state_settlement_objectives_round_trip() -> None:
    redis = _MemoryRedis()
    sim_id = uuid.uuid4()
    services = SimpleNamespace(redis=redis)

    response = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="alpha",
            simulation_id=sim_id,
            method="write",
            payload={
                "operation": "settlement_objectives_set",
                "settlement_objectives": [
                    {
                        "objective_id": "phase-cabin",
                        "phase_index": 0,
                        "description": "small shared cabin",
                    },
                    {
                        "objective_id": "phase-wall",
                        "phase_index": 1,
                        "description": "simple perimeter wall",
                    },
                ],
            },
        ),
        services,
    )
    assert response.ok is True

    assign = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="fork",
            simulation_id=sim_id,
            method="write",
            payload={
                "operation": "settlement_objective_assign",
                "settlement_objective": {
                    "objective_id": "phase-cabin",
                    "phase_index": 0,
                    "description": "small shared cabin",
                    "owner_agent_id": "fork",
                    "status": "in_progress",
                    "reassign_reason": "initial_phase_owner",
                },
            },
        ),
        services,
    )
    assert assign.ok is True

    state = SharedWorkingState(ScopedRedis(redis, sim_id))
    active = await state.get_active_settlement_objective()
    assert isinstance(active, SettlementObjective)
    assert active.objective_id == "phase-cabin"
    assert active.owner_agent_id == "fork"
    assert active.status == "in_progress"
    assert active.reassign_reason == "initial_phase_owner"

    read = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="vera",
            simulation_id=sim_id,
            method="read",
            payload={},
        ),
        services,
    )

    assert read.ok is True
    assert read.payload["active_objective"]["objective_id"] == "phase-cabin"  # type: ignore[index]
    assert "Active settlement objective" in read.payload["formatted"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_bridge_shared_state_requires_payload_entity_for_operation() -> None:
    response = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="vera",
            simulation_id=uuid.uuid4(),
            method="write",
            payload={"operation": "resource_upsert"},
        ),
        SimpleNamespace(redis=_MemoryRedis()),
    )

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == "invalid_payload"


@pytest.mark.asyncio
async def test_bridge_can_fall_back_to_injected_shared_state() -> None:
    state, _, sim_id = _state()
    state.get_group_goal = AsyncMock(return_value=GroupGoal(text="Fallback goal", set_by="vera"))
    services = SimpleNamespace(redis=None, shared_working_state=state)

    response = await build_bridge_response_with_services(
        _bridge_request(
            agent_id="rex",
            simulation_id=sim_id,
            method="read",
            payload={},
        ),
        services,
    )

    assert response.ok is True
    assert response.payload["goal"]["text"] == "Fallback goal"  # type: ignore[index]


async def _get_task(state: SharedWorkingState, task_id: str) -> SharedTask:
    tasks = {t.id: t for t in await state.get_tasks()}
    return tasks[task_id]


@pytest.mark.asyncio
async def test_claim_task_happy_path_claims_open_task() -> None:
    state, _, _ = _state()
    await state.add_task(SharedTask(id="t1", title="Build a well"))  # open, unowned

    result = await state.claim_task("t1", "rex")

    assert result == {"status": "ok", "owner": "rex"}
    task = await _get_task(state, "t1")
    assert task.owner == "rex"
    assert task.status == "in_progress"


@pytest.mark.asyncio
async def test_claim_task_double_claim_informs_loser_of_winner() -> None:
    state, _, _ = _state()
    await state.add_task(SharedTask(id="t1", title="Build a well"))

    first = await state.claim_task("t1", "rex")
    second = await state.claim_task("t1", "aurora")

    assert first == {"status": "ok", "owner": "rex"}
    assert second == {"status": "already_claimed", "owner": "rex"}
    # Owner unchanged by the losing claim.
    task = await _get_task(state, "t1")
    assert task.owner == "rex"


@pytest.mark.asyncio
async def test_claim_task_concurrent_race_has_exactly_one_winner() -> None:
    state, _, _ = _state()
    await state.add_task(SharedTask(id="t1", title="Lead the settlement"))

    results = await asyncio.gather(
        state.claim_task("t1", "rex"),
        state.claim_task("t1", "aurora"),
    )

    winners = [r for r in results if r["status"] == "ok"]
    losers = [r for r in results if r["status"] == "already_claimed"]
    assert len(winners) == 1
    assert len(losers) == 1
    winner_id = winners[0]["owner"]
    # The loser was told who won, and the persisted owner matches.
    assert losers[0]["owner"] == winner_id
    task = await _get_task(state, "t1")
    assert task.owner == winner_id
    assert task.status == "in_progress"


@pytest.mark.asyncio
async def test_claim_task_rejects_completed_task() -> None:
    state, _, _ = _state()
    await state.add_task(SharedTask(id="t1", title="Already built", owner="rex", status="done"))

    result = await state.claim_task("t1", "aurora")

    assert result["status"] == "already_claimed"
    assert result["owner"] == "rex"
    task = await _get_task(state, "t1")
    assert task.owner == "rex"
    assert task.status == "done"


@pytest.mark.asyncio
async def test_claim_task_idempotent_for_current_owner() -> None:
    state, _, _ = _state()
    await state.add_task(SharedTask(id="t1", title="Build a well"))
    await state.claim_task("t1", "rex")

    again = await state.claim_task("t1", "rex")

    assert again == {"status": "ok", "owner": "rex"}
    task = await _get_task(state, "t1")
    assert task.owner == "rex"
    assert task.status == "in_progress"


@pytest.mark.asyncio
async def test_claim_task_missing_task_returns_not_found() -> None:
    state, _, _ = _state()

    result = await state.claim_task("nope", "rex")

    assert result == {"status": "not_found"}

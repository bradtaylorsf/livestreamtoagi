"""Tests for embodied shared task/world-state blackboard."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.bridge import contract as c
from core.bridge.server import build_bridge_response_with_services
from core.redis_keys import ScopedRedis
from core.shared_state import (
    AgentClaim,
    BuildSite,
    DangerReport,
    GroupGoal,
    NextStep,
    ResourceEntry,
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
        DangerReport(agent_id="aurora", kind="nightfall", location="east ridge", severity=2)
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
    assert (await state.get_danger_reports())[0].kind == "nightfall"
    assert (await state.get_recent_verified_actions())[0].result == "verified"
    assert (await state.get_build_site()).site_id == "camp"  # type: ignore[union-attr]
    assert (await state.get_next_steps())[0].added_by == "pixel"

    summary = await state.get_summary_for_context()
    assert "Active group goal" in summary
    assert "Known resources" in summary
    assert "Agent claims" in summary
    assert "Recent verified actions" in summary


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

"""Tests for Director V2 prompt gating of Mindcraft bot prompts."""

from __future__ import annotations

from typing import Any

import pytest

from core.bridge.contract import BridgeRequest, CostContext
from core.bridge.handlers.director import handle_director_gate
from core.bridge.server import build_bridge_response_with_services
from core.minecraft.director.prompt_gate import DirectorPromptGate, reset_prompt_gates
from core.minecraft.director.turn_scheduler import SchedulerConfig

AGENTS = ["alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"]


def _event(**overrides: Any) -> dict[str, Any]:
    event = {
        "agent_id": "vera",
        "event_kind": "chat",
        "event_text": "Let's pick a camp marker and place the first visible block.",
        "source_agent": "viewer",
        "mentions": [],
        "position": {"x": 0, "y": 64, "z": 0},
        "scene_hint": "batch:1:viewer:camp",
        "available_tools": ["!inventory", "!placeHere"],
    }
    event.update(overrides)
    return event


def _build_event(**overrides: Any) -> dict[str, Any]:
    event = _event(
        event_text="Viewer asks the group to build a small shared cabin.",
        scene_hint="batch:1:viewer:shared-cabin",
        available_tools=["!inventory", "!planAndBuild", "!buildFromPlan"],
    )
    event.update(overrides)
    return event


def _gate() -> DirectorPromptGate:
    gate = DirectorPromptGate(
        scheduler_config=SchedulerConfig(max_turns_per_scene=1, random_jitter=0.0)
    )
    for idx, agent_id in enumerate(AGENTS):
        gate.register_agent(
            agent_id,
            position={"x": idx, "y": 64, "z": 0},
            timestamp_ms=1_000,
        )
    return gate


def _bridge_request(payload: dict[str, Any]) -> BridgeRequest:
    return BridgeRequest(
        version="1.7",
        request_id="req-director-gate-test",
        agent_id=payload["agent_id"],
        run_id="run-test",
        simulation_id="sim-director-gate",
        service="director",
        method="gate",
        payload=payload,
        deadline_ms=1500,
        cost_context=CostContext(
            agent_tier="conversation",
            budget_bucket="director-gate",
            estimated_cost_usd=0.0,
        ),
    )


@pytest.fixture(autouse=True)
def _reset_gate_state() -> None:
    reset_prompt_gates()


async def test_single_utterance_eight_agents_produces_one_prompt() -> None:
    gate = _gate()

    decisions = [await gate.evaluate("sim-test", agent_id, _event()) for agent_id in AGENTS]

    selected = [decision for decision in decisions if decision.selected]
    suppressed = [decision for decision in decisions if not decision.selected]
    assert len(selected) == 1
    assert len(suppressed) == 7
    assert all(decision.suppression_reason for decision in suppressed)
    assert all(decision.queue_depth <= 1 for decision in decisions)


async def test_unselected_agents_have_zero_legacy_prompts() -> None:
    gate = _gate()
    legacy_prompt_calls = 0

    for agent_id in AGENTS:
        decision = await gate.evaluate("sim-test", agent_id, _event())
        if decision.selected:
            legacy_prompt_calls += 1

    assert legacy_prompt_calls == 1


async def test_mode_bypass_returns_selected_true_when_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "embodied")

    responses = [
        await handle_director_gate(_bridge_request(_event(agent_id=agent_id)), services=None)
        for agent_id in AGENTS
    ]

    assert [response["selected"] for response in responses] == [True] * len(AGENTS)
    assert {response["reason"] for response in responses} == {"mode_bypass"}


async def test_director_v2_mode_routes_through_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")
    gate = _gate()
    first = [await gate.evaluate("sim-test", agent_id, _event()) for agent_id in AGENTS]

    second_gate = _gate()
    second = [await second_gate.evaluate("sim-test", agent_id, _event()) for agent_id in AGENTS]

    assert [decision.selected for decision in first] == [decision.selected for decision in second]
    assert sum(decision.selected for decision in first) == 1


async def test_telemetry_records_suppressed_and_queue_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")
    gate = _gate()

    decisions = [await gate.evaluate("sim-test", agent_id, _event()) for agent_id in AGENTS]
    suppressed = next(decision for decision in decisions if not decision.selected)

    assert suppressed.queue_depth == 1
    assert len(suppressed.suppressed_agents) == 7
    assert suppressed.scene_id
    assert suppressed.scene_digest


async def test_director_gate_bridge_response_surfaces_prompt_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")
    payload = _event(agent_id="vera")

    response = await build_bridge_response_with_services(
        _bridge_request(payload).model_dump(),
        services=None,
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload["selected"] is True
    assert response.payload["queue_depth"] == 1
    assert "scene_digest" in response.payload


async def test_planner_turn_gets_build_macro_ownership_and_plan_tool() -> None:
    gate = _gate()

    decisions = [await gate.evaluate("sim-test", agent_id, _build_event()) for agent_id in AGENTS]

    owners = [
        decision
        for decision in decisions
        if decision.build_macro is not None and decision.build_macro.role == "planner_owner"
    ]
    assert len(owners) == 1
    owner = owners[0]
    assert owner.selected is True
    assert owner.turn_kind == "planner"
    assert owner.build_macro is not None
    assert owner.build_macro.granted is True
    assert owner.build_macro.plan_id
    assert "!planAndBuild" in owner.available_tools

    supports = [
        decision
        for decision in decisions
        if decision.build_macro is not None and decision.build_macro.role == "support"
    ]
    assert supports
    assert all("!planAndBuild" not in decision.available_tools for decision in supports)
    assert all(decision.build_macro.support_task for decision in supports if decision.build_macro)


async def test_director_gate_bridge_response_surfaces_build_macro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")

    response = await build_bridge_response_with_services(
        _bridge_request(_build_event(agent_id="rex")).model_dump(),
        services=None,
    )

    assert response.ok is True
    assert response.payload is not None
    assert response.payload["build_macro"]["role"] == "planner_owner"
    assert response.payload["build_macro"]["granted"] is True
    assert "!planAndBuild" in response.payload["granted_tools"]

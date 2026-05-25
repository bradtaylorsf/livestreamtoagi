"""Tests for Director V2 prompt gating of Mindcraft bot prompts."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.bridge.consumers import get_scene_memory_consumer, unregister_scene_memory_consumer
from core.bridge.contract import BridgeRequest, CostContext
from core.bridge.handlers.director import handle_director_gate
from core.bridge.server import build_bridge_response_with_services
from core.event_bus import EventBus
from core.event_bus import event_bus as global_event_bus
from core.minecraft.director.prompt_gate import DirectorPromptGate, reset_prompt_gates
from core.minecraft.director.timeline import ensure_soak_run_dir_from_run_id
from core.minecraft.director.turn_scheduler import SchedulerConfig

AGENTS = ["alpha", "vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"]


class _FakeCompactor:
    def __init__(self) -> None:
        self.compact_calls: list[dict[str, Any]] = []
        self.recall_calls: list[dict[str, Any]] = []

    async def compact_interaction(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        participants: list[str] | None = None,
        conversation_id: object | None = None,
        summary_style: str = "default",
    ) -> object:
        self.compact_calls.append(
            {
                "agent_id": agent_id,
                "interaction": interaction,
                "event_type": event_type,
                "participants": participants,
                "conversation_id": conversation_id,
                "summary_style": summary_style,
            }
        )
        return SimpleNamespace(
            transcript=SimpleNamespace(id=202),
            recall_memory=SimpleNamespace(summary="Vera coordinated a shared camp marker."),
        )

    async def compact_recall_only(
        self,
        agent_id: str,
        interaction: str,
        event_type: str,
        transcript_id: int,
        participants: list[str] | None = None,
        summary_style: str = "default",
    ) -> object:
        self.recall_calls.append(
            {
                "agent_id": agent_id,
                "interaction": interaction,
                "event_type": event_type,
                "transcript_id": transcript_id,
                "participants": participants,
                "summary_style": summary_style,
            }
        )
        return SimpleNamespace(id=len(self.recall_calls) + 1)


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


async def test_director_gate_lazily_registers_scene_memory_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")
    bus = EventBus()
    services = SimpleNamespace(event_bus=bus, compactor=object())

    try:
        await handle_director_gate(_bridge_request(_event(agent_id="vera")), services=services)

        assert get_scene_memory_consumer(bus) is not None
    finally:
        unregister_scene_memory_consumer(bus)


async def test_director_gate_scene_reaches_memory_digest_timeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CONVERSATION_MODE", "director_v2")
    monkeypatch.setenv("SOAK_RUN_DIR", str(tmp_path))
    compactor = _FakeCompactor()
    services = SimpleNamespace(event_bus=global_event_bus, compactor=compactor)

    try:
        await handle_director_gate(
            _bridge_request(
                _event(
                    agent_id="vera",
                    event_text="Let's mark the shared camp before we build.",
                )
            ),
            services=services,
        )
        consumer = get_scene_memory_consumer(global_event_bus)
        assert consumer is not None
        await consumer.flush_due_scenes(now_ms=9_999_999_999_999)
    finally:
        unregister_scene_memory_consumer(global_event_bus)

    assert len(compactor.compact_calls) == 1
    assert compactor.compact_calls[0]["agent_id"] == "vera"
    assert "vera" in compactor.compact_calls[0]["participants"]
    assert "shared camp" in compactor.compact_calls[0]["interaction"]

    path = tmp_path / "timeline-raw" / "director_v2.ndjson"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    event_types = [record["event_type"] for record in records]
    assert "director.scene.opened" in event_types
    assert "director.gate.decision" in event_types
    assert "director.scene.digest" in event_types


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


async def test_build_plan_success_notice_does_not_start_second_macro() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="rex",
        event_text=(
            "build-from-plan build-plan-1 success: intended=32; present=32; "
            "missing=0; unexpected=0; verified=32; completion=1.000"
        ),
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]

    assert all(decision.build_macro is None for decision in decisions)
    assert all("!planAndBuild" not in decision.available_tools for decision in decisions)


async def test_build_completion_chatter_does_not_start_second_macro() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="rex",
        event_text="Looks like the cabin is done! Nice job everyone!",
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]

    assert all(decision.build_macro is None for decision in decisions)
    assert all("!planAndBuild" not in decision.available_tools for decision in decisions)


async def test_bare_cabin_followup_does_not_start_second_macro() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="rex",
        event_text="Awesome! The cabin is up. What's next?",
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]

    assert all(decision.build_macro is None for decision in decisions)
    assert all("!planAndBuild" not in decision.available_tools for decision in decisions)


async def test_heartbeat_text_does_not_start_build_macro() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text=(
            "Autonomous heartbeat: you have been quiet in the Minecraft plan-build "
            "simulation. If you are the build owner and !planAndBuild is available, "
            "use one concise request."
        ),
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]

    assert all(decision.build_macro is None for decision in decisions)
    assert all("!planAndBuild" not in decision.available_tools for decision in decisions)


async def test_plan_mode_success_closes_single_build_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_BUILD_MODE", "plan")
    monkeypatch.setenv("MC_SIM_BUILD_MAX_PER_AGENT", "1")
    gate = _gate()
    success_event = _build_event(
        source_agent="rex",
        event_text=(
            "build-from-plan build-plan-1 success: intended=32; present=32; "
            "missing=0; unexpected=0; verified=32; completion=1.000"
        ),
    )
    for agent_id in AGENTS:
        await gate.evaluate("sim-test", agent_id, success_event)

    followup = _build_event(
        source_agent="fork",
        event_text="Let's build a simple work table right here for organized storage.",
    )
    decisions = [await gate.evaluate("sim-test", agent_id, followup) for agent_id in AGENTS]

    assert all(decision.build_macro is None for decision in decisions)
    assert all("!planAndBuild" not in decision.available_tools for decision in decisions)


async def test_plan_mode_success_quiesces_post_build_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_BUILD_MODE", "plan")
    monkeypatch.setenv("MC_SIM_BUILD_MAX_PER_AGENT", "1")
    gate = _gate()
    success_event = _build_event(
        source_agent="vera",
        event_text=(
            "build-from-plan build-plan-1 success: intended=32; present=32; "
            "missing=0; unexpected=0; verified=32; completion=1.000"
        ),
    )

    success_decisions = [
        await gate.evaluate("sim-test", agent_id, success_event) for agent_id in AGENTS
    ]

    assert all(decision.selected is False for decision in success_decisions)
    assert {decision.suppression_reason for decision in success_decisions} == {
        "plan_mode_build_completed"
    }
    assert {decision.queue_depth for decision in success_decisions} == {0}

    followup = _build_event(
        source_agent="system",
        event_text=(
            "Autonomous heartbeat: you have been quiet in the Minecraft plan-build "
            "simulation. Keep the group focused on one coherent shared structure."
        ),
    )
    followup_decisions = [
        await gate.evaluate("sim-test", agent_id, followup) for agent_id in AGENTS
    ]

    assert all(decision.selected is False for decision in followup_decisions)
    assert all(decision.build_macro is None for decision in followup_decisions)
    assert all(decision.available_tools == [] for decision in followup_decisions)
    assert {decision.queue_depth for decision in followup_decisions} == {0}


async def test_system_broadcast_build_turn_considers_full_sim_cohort() -> None:
    gate = DirectorPromptGate(
        scheduler_config=SchedulerConfig(max_turns_per_scene=1, random_jitter=0.0)
    )
    event = _build_event(source_agent="system")

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]

    selected = [decision for decision in decisions if decision.selected]
    assert len(selected) == 1
    assert selected[0].turn_kind == "planner"
    assert selected[0].build_macro is not None
    assert selected[0].build_macro.owner in {"rex", "fork"}


async def test_explicit_build_owner_overrides_builder_role_weight() -> None:
    gate = DirectorPromptGate(
        scheduler_config=SchedulerConfig(max_turns_per_scene=1, random_jitter=0.0)
    )
    event = _build_event(
        source_agent="system",
        event_text=(
            "Vera is the build owner. Build one small coherent starter cabin. "
            "Rex and Aurora should support only by observing and reporting constraints."
        ),
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]

    selected = [decision for decision in decisions if decision.selected]
    assert len(selected) == 1
    owner = selected[0]
    assert owner.turn_kind == "planner"
    assert owner.reason == "explicit_build_owner"
    assert owner.build_macro is not None
    assert owner.build_macro.owner == "vera"
    assert owner.build_macro.role == "planner_owner"
    assert owner.build_macro.granted is True
    assert "!planAndBuild" in owner.available_tools

    by_agent = dict(zip(AGENTS, decisions, strict=True))
    assert by_agent["rex"].build_macro is not None
    assert by_agent["rex"].build_macro.role == "support"
    assert "!planAndBuild" not in by_agent["rex"].available_tools


async def test_settlement_active_objective_controls_build_owner() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Build the next settlement phase.",
        plan_build_agent_allowlist=["vera", "rex", "fork"],
        active_objective={
            "objective_id": "phase-workshop",
            "phase_index": 2,
            "description": "workshop station",
            "owner_agent_id": "vera",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    owner = by_agent["vera"]
    assert owner.selected is True
    assert owner.turn_kind == "planner"
    assert owner.build_macro is not None
    assert owner.build_macro.owner == "vera"
    assert owner.build_macro.objective_id == "phase-workshop"
    assert owner.build_macro.phase_index == 2
    assert "!planAndBuild" in owner.available_tools

    assert by_agent["rex"].build_macro is not None
    assert by_agent["rex"].build_macro.role == "support"
    assert by_agent["rex"].build_macro.objective_id == "phase-workshop"
    assert "!planAndBuild" not in by_agent["rex"].available_tools


async def test_plan_build_allowlist_reassigns_non_builder_objective_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST", "rex fork")
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Build the next team workshop phase.",
        active_objective={
            "objective_id": "phase-workshop",
            "phase_index": 2,
            "description": "workshop station",
            "owner_agent_id": "vera",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    selected = [decision for decision in decisions if decision.selected]

    assert len(selected) == 1
    owner = selected[0]
    assert owner.build_macro is not None
    assert owner.build_macro.owner in {"rex", "fork"}
    assert owner.build_macro.reason in {
        "settlement_phase_owner_assigned",
        "settlement_phase_owner_reassigned",
    }
    assert owner.build_macro.objective_id == "phase-workshop"
    assert "!planAndBuild" in owner.available_tools

    by_agent = dict(zip(AGENTS, decisions, strict=True))
    assert by_agent[owner.build_macro.owner].selected is True
    assert by_agent["vera"].build_macro is not None
    assert by_agent["vera"].build_macro.role == "support"
    assert "!planAndBuild" not in by_agent["vera"].available_tools


async def test_pending_settlement_objective_does_not_lock_out_selected_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS", "0")
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Rex is the build owner. Build the next settlement phase.",
        active_objective={
            "objective_id": "phase-square",
            "phase_index": 6,
            "description": "central town square",
            "owner_agent_id": "sentinel",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    owner = by_agent["rex"]
    assert owner.selected is True
    assert owner.turn_kind == "planner"
    assert owner.build_macro is not None
    assert owner.build_macro.owner == "rex"
    assert owner.build_macro.objective_id == "phase-square"
    assert owner.build_macro.reason == "settlement_phase_owner_assigned"
    assert "!planAndBuild" in owner.available_tools

    assert by_agent["sentinel"].build_macro is not None
    assert by_agent["sentinel"].build_macro.role == "support"
    assert "!planAndBuild" not in by_agent["sentinel"].available_tools


async def test_expired_pending_settlement_owner_can_be_claimed_by_calling_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS", "0")
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Autonomous settlement heartbeat: build the next settlement phase.",
        active_objective={
            "objective_id": "phase-animal-pen",
            "phase_index": 2,
            "description": "garden animal pen",
            "owner_agent_id": "rex",
            "status": "pending",
        },
    )

    decision = await gate.evaluate("sim-test", "sentinel", event)

    assert decision.selected is True
    assert decision.turn_kind == "planner"
    assert decision.build_macro is not None
    assert decision.build_macro.owner == "sentinel"
    assert decision.build_macro.reason == "settlement_phase_owner_assigned"
    assert "!planAndBuild" in decision.available_tools


async def test_pending_settlement_owner_default_grace_blocks_early_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS", raising=False)
    monkeypatch.delenv("MINECRAFT_SETTLEMENT_PENDING_OWNER_GRACE_MS", raising=False)
    now = 1_000

    def fake_now_ms() -> int:
        return now

    monkeypatch.setattr("core.minecraft.director.build_macro_scheduler._now_ms", fake_now_ms)
    monkeypatch.setattr("core.minecraft.director.prompt_gate._now_ms", fake_now_ms)
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text='Build the active settlement phase "garden animal pen".',
        active_objective={
            "objective_id": "phase-animal-pen",
            "phase_index": 2,
            "description": "garden animal pen",
            "owner_agent_id": "rex",
            "status": "pending",
        },
    )

    first = await gate.evaluate("sim-test", "sentinel", event)
    now += 120_000
    event["scene_hint"] = "batch:1:system:garden-animal-pen-retry"
    second = await gate.evaluate("sim-test", "sentinel", event)

    assert first.selected is False
    assert first.build_macro is not None
    assert first.build_macro.owner == "rex"
    assert first.build_macro.reason == "support_assignment"
    assert "!planAndBuild" not in first.available_tools
    assert second.selected is False
    assert second.build_macro is not None
    assert second.build_macro.owner == "rex"
    assert second.build_macro.reason == "support_assignment"
    assert "!planAndBuild" not in second.available_tools


async def test_plan_build_allowlist_blocks_non_eligible_explicit_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST", "rex fork")
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text=(
            "Vera is the build owner. Build one small logistics hut. "
            "Rex and Fork are the currently elected builder-duty agents."
        ),
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    owner = by_agent["vera"]
    assert owner.selected is True
    assert owner.build_macro is not None
    assert owner.build_macro.owner == "vera"
    assert owner.build_macro.reason == "plan_build_agent_not_allowed"
    assert owner.build_macro.granted is False
    assert "!planAndBuild" not in owner.available_tools


async def test_request_allowlist_reassigns_blocked_settlement_owner_without_backend_env() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Build the next settlement phase.",
        plan_build_agent_allowlist=["rex", "fork"],
        active_objective={
            "objective_id": "phase-workshop",
            "phase_index": 2,
            "description": "Team Ember storage workshop station",
            "owner_agent_id": "aurora",
            "status": "blocked",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    selected = [decision for decision in decisions if decision.selected]

    assert len(selected) == 1
    owner = selected[0]
    assert owner.build_macro is not None
    assert owner.build_macro.owner in {"rex", "fork"}
    assert owner.build_macro.owner != "aurora"
    assert owner.build_macro.reason == "settlement_phase_owner_reassigned"
    assert "!planAndBuild" in owner.available_tools


async def test_active_settlement_objective_ignores_stale_backend_plan_mode_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_SIM_BUILD_MODE", "plan")
    monkeypatch.setenv("MC_SIM_BUILD_MAX_PER_AGENT", "1")
    gate = _gate()
    status_notice = _event(
        source_agent="fork",
        event_text=(
            "build-from-plan build-plan-1 success: intended=12; present=12; "
            "missing=0; unexpected=0; verified=12; completion=1.000"
        ),
        available_tools=["!inventory"],
    )
    await gate.evaluate("sim-test", "rex", status_notice)

    event = _build_event(
        source_agent="system",
        event_text='Build the active settlement phase "perimeter wall". Autonomous heartbeat.',
        active_objective={
            "objective_id": "phase-wall",
            "phase_index": 1,
            "description": "perimeter wall",
            "owner_agent_id": "rex",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    owner = by_agent["rex"]
    assert owner.selected is True
    assert owner.build_macro is not None
    assert owner.build_macro.granted is True
    assert owner.build_macro.objective_id == "phase-wall"
    assert "!planAndBuild" in owner.available_tools


async def test_unresolved_distress_preempts_settlement_build_turn() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text='Build the active settlement phase "watch tower".',
        available_tools=["!inventory", "!nearbyBlocks", "!rescue", "!planAndBuild"],
        active_objective={
            "objective_id": "phase-watch-tower",
            "phase_index": 3,
            "description": "watch tower",
            "owner_agent_id": "rex",
            "status": "pending",
        },
        unresolved_dangers=[
            {
                "agent_id": "sentinel",
                "kind": "drowning",
                "location": {"x": 7, "y": 56, "z": -2},
                "severity": 5,
                "danger_id": "danger-sentinel",
                "rescuer_id": "alpha",
                "recovery_status": "rescue_dispatched",
                "reported_at": 1_000.0,
            }
        ],
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    rescuer = by_agent["alpha"]
    assert rescuer.selected is True
    assert rescuer.turn_kind == "speaker"
    assert rescuer.reason == "active_rescue_task"
    assert rescuer.build_macro is None
    assert rescuer.local_observations["active_rescue"]["target_agent_id"] == "sentinel"
    assert rescuer.local_observations["active_rescue"]["danger_id"] == "danger-sentinel"
    assert "!rescue" in rescuer.available_tools
    assert "!planAndBuild" not in rescuer.available_tools
    assert all(decision.build_macro is None for decision in decisions)
    assert all(
        not decision.selected for agent_id, decision in by_agent.items() if agent_id != "alpha"
    )


async def test_new_settlement_objective_releases_previous_scene_owner() -> None:
    gate = _gate()
    phase_one = _build_event(
        source_agent="system",
        event_text='Build the active settlement phase "starter cabin".',
        scene_hint="settlement-shared-scene",
        active_objective={
            "objective_id": "phase-cabin",
            "phase_index": 0,
            "description": "starter cabin",
            "owner_agent_id": "fork",
            "status": "pending",
        },
    )
    first_decisions = [await gate.evaluate("sim-test", agent_id, phase_one) for agent_id in AGENTS]
    assert dict(zip(AGENTS, first_decisions, strict=True))["fork"].build_macro.owner == "fork"

    phase_two = _build_event(
        source_agent="vera",
        event_text='Build the active settlement phase "workshop station".',
        scene_hint="settlement-shared-scene",
        active_objective={
            "objective_id": "phase-workshop",
            "phase_index": 2,
            "description": "workshop station",
            "owner_agent_id": "pixel",
            "status": "pending",
        },
    )

    second_decisions = [await gate.evaluate("sim-test", agent_id, phase_two) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, second_decisions, strict=True))

    owner = by_agent["pixel"]
    assert owner.selected is True
    assert owner.build_macro is not None
    assert owner.build_macro.owner == "pixel"
    assert owner.build_macro.objective_id == "phase-workshop"
    assert "!planAndBuild" in owner.available_tools


async def test_settlement_owner_keeps_plan_grant_after_cached_verdict_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000

    def fake_now_ms() -> int:
        return now

    monkeypatch.setattr("core.minecraft.director.prompt_gate._now_ms", fake_now_ms)
    monkeypatch.setattr("core.minecraft.director.prompt_gate._DECISION_TTL_MS", 10)
    gate = _gate()
    event = _build_event(
        source_agent="fork",
        event_text=(
            'Build the active settlement phase "shared storage depot". '
            "Incoming batch from support agents."
        ),
        scene_hint="settlement-shared-storage-scene",
        active_objective={
            "objective_id": "phase-storage",
            "phase_index": 1,
            "description": "shared storage depot",
            "owner_agent_id": "vera",
            "status": "pending",
        },
    )

    support_decision = await gate.evaluate("sim-test", "sentinel", event)
    assert support_decision.selected is False
    assert support_decision.build_macro is not None
    assert support_decision.build_macro.owner == "vera"

    now = 1_015
    owner_decision = await gate.evaluate("sim-test", "vera", event)

    assert owner_decision.selected is True
    assert owner_decision.turn_kind == "planner"
    assert owner_decision.build_macro is not None
    assert owner_decision.build_macro.owner == "vera"
    assert owner_decision.build_macro.granted is True
    assert owner_decision.build_macro.plan_id == support_decision.build_macro.plan_id
    assert "!planAndBuild" in owner_decision.available_tools


async def test_explicit_plan_and_build_in_settlement_brief_overrides_completion_words() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text=(
            "Complete these settlement objectives in order: starter cabin|perimeter wall. "
            'Use exactly one !planAndBuild("small shared cabin") request for this phase.'
        ),
        active_objective={
            "objective_id": "phase-cabin",
            "phase_index": 0,
            "description": "starter cabin",
            "owner_agent_id": "vera",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    owner = by_agent["vera"]
    assert owner.selected is True
    assert owner.turn_kind == "planner"
    assert owner.build_macro is not None
    assert owner.build_macro.objective_id == "phase-cabin"
    assert owner.build_macro.granted is True
    assert "!planAndBuild" in owner.available_tools


async def test_pending_settlement_owner_preempts_ordinary_chatter() -> None:
    gate = _gate()
    event = _event(
        source_agent="viewer",
        event_text="The storage depot is done. Decide what the settlement should do next.",
        scene_hint="settlement-phase-transition",
        available_tools=["!inventory"],
        active_objective={
            "objective_id": "phase-garden-pen",
            "phase_index": 2,
            "description": "garden animal pen",
            "owner_agent_id": "rex",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    owner = by_agent["rex"]
    assert owner.selected is True
    assert owner.turn_kind == "planner"
    assert owner.reason == "settlement_phase_owner"
    assert owner.build_macro is not None
    assert owner.build_macro.owner == "rex"
    assert owner.build_macro.objective_id == "phase-garden-pen"
    assert owner.build_macro.granted is True
    assert "!planAndBuild" in owner.available_tools
    assert all(not decision.selected for agent, decision in by_agent.items() if agent != "rex")


async def test_settlement_active_objective_reassigns_capped_owner() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Build the next settlement phase.",
        active_objective={
            "objective_id": "phase-wall",
            "phase_index": 1,
            "description": "simple perimeter wall",
            "owner_agent_id": "rex",
            "status": "owner_cap_reached",
            "previous_owner_agent_ids": ["rex"],
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    selected = [decision for decision in decisions if decision.selected]

    assert len(selected) == 1
    assert selected[0].build_macro is not None
    assert selected[0].build_macro.owner == "fork"
    assert selected[0].build_macro.reason == "settlement_phase_owner_reassigned"
    assert selected[0].build_macro.objective_id == "phase-wall"


async def test_settlement_active_objective_retries_previous_owner_when_current_capped() -> None:
    gate = _gate()
    event = _build_event(
        source_agent="system",
        event_text="Build the next settlement phase.",
        plan_build_agent_allowlist=["rex", "fork"],
        active_objective={
            "objective_id": "phase-workshop",
            "phase_index": 3,
            "description": "Team Grove storage workshop station",
            "owner_agent_id": "rex",
            "status": "owner_cap_reached",
            "previous_owner_agent_ids": ["fork"],
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    selected = [decision for decision in decisions if decision.selected]

    assert len(selected) == 1
    assert selected[0].build_macro is not None
    assert selected[0].build_macro.owner == "fork"
    assert selected[0].build_macro.reason == "settlement_phase_owner_reassigned"
    assert selected[0].build_macro.objective_id == "phase-workshop"


async def test_selection_starvation_guard_eventually_selects_every_agent() -> None:
    gate = _gate()
    selected_counts: Counter[str] = Counter()

    for idx in range(len(AGENTS) * 3):
        event = _event(
            source_agent="system",
            event_text=f"Heartbeat coordination round {idx}. Pick one useful visible action.",
            scene_hint=f"heartbeat-round-{idx}",
            position={"x": idx * 64, "y": 64, "z": 0},
        )
        for agent_id in AGENTS:
            decision = await gate.evaluate(
                "sim-test",
                agent_id,
                {**event, "agent_id": agent_id},
            )
            if decision.selected:
                selected_counts[agent_id] += 1

    assert set(selected_counts) == set(AGENTS)
    assert max(selected_counts.values()) - min(selected_counts.values()) <= 2


async def test_scene_selected_agent_cap_limits_starvation_fanout() -> None:
    gate = _gate()
    selected_agents_by_scene: dict[str, set[str]] = {}
    suppression_reasons: Counter[str | None] = Counter()

    for idx in range(len(AGENTS) * 2):
        event = _event(
            source_agent="system",
            event_text=f"Same meadow coordination round {idx}. Pick one useful visible action.",
            scene_hint=f"same-meadow-round-{idx}",
            position={"x": 0, "y": 64, "z": 0},
        )
        for agent_id in AGENTS:
            decision = await gate.evaluate(
                "sim-test",
                agent_id,
                {**event, "agent_id": agent_id},
            )
            if decision.selected:
                selected_agents_by_scene.setdefault(decision.scene_id, set()).add(agent_id)
            else:
                suppression_reasons[decision.suppression_reason] += 1

    assert selected_agents_by_scene
    assert max(len(agent_ids) for agent_ids in selected_agents_by_scene.values()) <= 4
    assert suppression_reasons["scene_selected_agent_cap"] > 0


async def test_scene_cap_does_not_block_new_settlement_phase_owner() -> None:
    gate = _gate()

    for idx in range(len(AGENTS) * 2):
        event = _event(
            source_agent="system",
            event_text=f"Same meadow coordination round {idx}. Pick one useful visible action.",
            scene_hint=f"same-meadow-round-{idx}",
            position={"x": 0, "y": 64, "z": 0},
        )
        for agent_id in AGENTS:
            await gate.evaluate("sim-test", agent_id, {**event, "agent_id": agent_id})

    event = _build_event(
        source_agent="system",
        event_text='Build the active settlement phase "mine staging yard".',
        scene_hint="same-meadow-round-owner",
        position={"x": 0, "y": 64, "z": 0},
        active_objective={
            "objective_id": "phase-mine-yard",
            "phase_index": 4,
            "description": "mine staging yard",
            "owner_agent_id": "pixel",
            "status": "pending",
        },
    )

    decisions = [await gate.evaluate("sim-test", agent_id, event) for agent_id in AGENTS]
    by_agent = dict(zip(AGENTS, decisions, strict=True))

    assert by_agent["pixel"].selected is True
    assert by_agent["pixel"].turn_kind == "planner"
    assert by_agent["pixel"].reason == "settlement_phase_owner"
    assert by_agent["pixel"].build_macro is not None
    assert by_agent["pixel"].build_macro.owner == "pixel"
    assert "!planAndBuild" in by_agent["pixel"].available_tools


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


async def test_director_gate_emits_soak_timeline_decision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SOAK_RUN_DIR", str(tmp_path))
    gate = _gate()

    decision = await gate.evaluate("sim-test", "vera", _event(trace_id="trace-gate-1"))

    path = tmp_path / "timeline-raw" / "director_v2.ndjson"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    gate_records = [
        record for record in records if record["event_type"] == "director.gate.decision"
    ]
    assert len(gate_records) == 1
    record = gate_records[0]
    assert record["trace_id"] == "trace-gate-1"
    assert record["agent"] == "vera"
    assert record["payload"]["scene_id"] == decision.scene_id
    assert record["payload"]["selected"] is decision.selected
    assert record["payload"]["queue_depth"] == decision.queue_depth


def test_soak_run_dir_can_be_inferred_from_run_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SOAK_RUN_DIR", raising=False)
    monkeypatch.delenv("MC_RUN_DIR", raising=False)
    run_dir = tmp_path / "logs" / "soak" / "20260522T171813Z"
    run_dir.mkdir(parents=True)

    resolved = ensure_soak_run_dir_from_run_id("20260522T171813Z", root=tmp_path)

    assert resolved == run_dir
    assert os.environ["MC_RUN_DIR"] == str(run_dir)


def test_soak_run_dir_inference_rejects_non_soak_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SOAK_RUN_DIR", raising=False)
    monkeypatch.delenv("MC_RUN_DIR", raising=False)
    (tmp_path / "logs" / "soak" / "run-test").mkdir(parents=True)

    assert ensure_soak_run_dir_from_run_id("run-test", root=tmp_path) is None
    assert os.environ.get("MC_RUN_DIR") is None

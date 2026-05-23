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

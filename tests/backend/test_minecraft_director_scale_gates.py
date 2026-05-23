"""Scale gates for Director V2 prompt fanout control."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest

from core.minecraft.director.prompt_gate import DirectorPromptGate
from core.minecraft.director.turn_scheduler import SchedulerConfig


@dataclass
class FakeLLMPromptCounter:
    prompts: int = 0
    selected_by_agent: dict[str, int] = field(default_factory=dict)
    selected_sequence: list[str] = field(default_factory=list)

    def record(self, agent_id: str) -> None:
        self.prompts += 1
        self.selected_by_agent[agent_id] = self.selected_by_agent.get(agent_id, 0) + 1
        self.selected_sequence.append(agent_id)


class FakeAgentEventGenerator:
    def __init__(self, agent_count: int, *, active_scene_agents: int = 16) -> None:
        self.agent_ids = [f"agent-{index:04d}" for index in range(agent_count)]
        self.active_agent_ids = self.agent_ids[: min(agent_count, active_scene_agents)]

    def register(self, gate: DirectorPromptGate) -> None:
        for index, agent_id in enumerate(self.agent_ids):
            role = "builder" if index % 5 == 0 else "scene participant"
            gate.register_agent(
                agent_id,
                role=role,
                chattiness=0.5,
                position={"x": index % 8, "y": 64, "z": index // 8},
                timestamp_ms=1_000,
            )

    def event(self, scene_index: int) -> dict[str, Any]:
        mentioned = self.active_agent_ids[scene_index % len(self.active_agent_ids)]
        build_text = " Please build a tiny camp marker." if scene_index % 7 == 0 else ""
        return {
            "agent_id": mentioned,
            "event_kind": "chat",
            "event_text": f"@{mentioned} choose the next scene action.{build_text}",
            "source_agent": "viewer",
            "mentions": [mentioned],
            "position": {"x": 0, "y": 64, "z": 0},
            "scene_hint": f"scale-scene-{scene_index}",
            "available_tools": ["!inventory", "!placeHere", "!planAndBuild"],
            "trace_id": f"trace-scale-{scene_index}",
        }


def _gini(values: list[int]) -> float:
    if not values or sum(values) == 0:
        return 0.0
    ordered = sorted(values)
    total = sum(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2 * weighted) / (len(ordered) * total) - (len(ordered) + 1) / len(ordered)


def _max_gap_between_selections(sequence: list[str], agent_ids: list[str]) -> int:
    max_gap = 0
    for agent_id in agent_ids:
        last_seen = -1
        for index, selected in enumerate(sequence):
            if selected != agent_id:
                continue
            max_gap = max(max_gap, index - last_seen - 1)
            last_seen = index
        max_gap = max(max_gap, len(sequence) - last_seen - 1)
    return max_gap


async def _run_scale_gate(agent_count: int, scene_count: int = 32) -> dict[str, Any]:
    gate = DirectorPromptGate(
        scheduler_config=SchedulerConfig(max_turns_per_scene=1, random_jitter=0.0)
    )
    generator = FakeAgentEventGenerator(agent_count)
    generator.register(gate)
    prompt_counter = FakeLLMPromptCounter()
    queue_depth_max = 0
    suppressed = 0
    build_macro_seen = False

    for scene_index in range(scene_count):
        event = generator.event(scene_index)
        for agent_id in generator.agent_ids:
            decision = await gate.evaluate("sim-scale", agent_id, event)
            queue_depth_max = max(queue_depth_max, decision.queue_depth)
            if decision.selected:
                prompt_counter.record(agent_id)
                build_macro_seen = build_macro_seen or decision.build_macro is not None
            else:
                suppressed += 1

    active_counts = [
        prompt_counter.selected_by_agent.get(agent_id, 0) for agent_id in generator.active_agent_ids
    ]
    return {
        "agent_count": agent_count,
        "scene_count": scene_count,
        "prompts_made": prompt_counter.prompts,
        "naive_fanout_prompts": agent_count * scene_count,
        "suppressed": suppressed,
        "queue_depth_max": queue_depth_max,
        "fairness_gini": _gini(active_counts),
        "max_selection_gap": _max_gap_between_selections(
            prompt_counter.selected_sequence,
            generator.active_agent_ids,
        ),
        "active_agent_count": len(generator.active_agent_ids),
        "build_macro_seen": build_macro_seen,
    }


@pytest.mark.parametrize("agent_count", [8, 32, 128])
async def test_director_prompt_count_scales_with_selected_scene_turns(
    agent_count: int,
) -> None:
    result = await _run_scale_gate(agent_count)

    assert result["prompts_made"] == result["scene_count"]
    assert result["prompts_made"] < result["naive_fanout_prompts"]
    assert result["suppressed"] == result["naive_fanout_prompts"] - result["prompts_made"]
    assert result["queue_depth_max"] <= result["scene_count"]
    assert result["fairness_gini"] <= 0.15
    assert result["max_selection_gap"] <= result["active_agent_count"]
    assert result["build_macro_seen"] is True


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("RUN_SCALE_1K") != "1", reason="set RUN_SCALE_1K=1")
async def test_director_prompt_count_scales_to_1000_agents_when_enabled() -> None:
    result = await _run_scale_gate(1000)

    assert result["prompts_made"] == result["scene_count"]
    assert result["prompts_made"] < result["naive_fanout_prompts"]
    assert result["queue_depth_max"] <= result["scene_count"]

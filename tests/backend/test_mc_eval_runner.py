"""Tests for the text-only Minecraft command eval runner."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from core.minecraft.commands import CommandParam, CommandSchema, CommandSchemaSet
from core.minecraft.eval.runner import DEFAULT_AGENT_ID, build_scenario_messages, run_eval
from core.minecraft.scenarios import ScenarioSet, load_scenario_set
from core.minecraft.skill_cards import get_default_registry
from core.models import LLMResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "mc_scenarios" / "valid"


class FakeClient:
    provider = "fake-provider"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str,
        agent_id: str | None = None,
        *,
        timeout: float = 30.0,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "agent_id": agent_id,
                "timeout": timeout,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        index = len(self.calls)
        return LLMResponse(
            content=f"chat: collected {index}",
            model=model,
            input_tokens=10 * index,
            output_tokens=5 * index,
            estimated_cost=Decimal("0.001") * index,
            latency_ms=index,
            openrouter_id=f"gen-{index}",
        )


def _command_surface() -> CommandSchemaSet:
    return CommandSchemaSet(
        commands=(
            CommandSchema(
                name="!move",
                description="Move a verified distance.",
                params=(
                    CommandParam(name="action_id", type="string"),
                    CommandParam(name="direction", type="string"),
                    CommandParam(name="distance_blocks", type="float"),
                ),
            ),
            CommandSchema(name="!observe", description="Observe the nearby world."),
            CommandSchema(name="!inventory", description="Inspect inventory."),
        )
    )


async def test_run_eval_collects_outputs_and_aggregates_metadata() -> None:
    loaded = load_scenario_set(VALID_FIXTURES)
    scenario_set = ScenarioSet(scenarios=loaded.scenarios[:2])
    client = FakeClient()

    summary = await run_eval(
        scenario_set,
        client=client,
        model="qwen-local",
        provider="lmstudio",
        base_url="http://localhost:1234/v1",
        key_present=True,
        commands=_command_surface(),
        skill_cards=get_default_registry(),
        timeout=9,
        max_tokens=64,
        temperature=0.1,
    )

    assert summary.provider == "lmstudio"
    assert summary.model == "qwen-local"
    assert summary.request_count == 2
    assert summary.prompt_tokens == 30
    assert summary.completion_tokens == 15
    assert summary.estimated_cost == Decimal("0.003")
    assert summary.collected_count == 2
    assert [result.openrouter_id for result in summary.results] == ["gen-1", "gen-2"]
    assert len(client.calls) == 2
    assert {call["agent_id"] for call in client.calls} == {DEFAULT_AGENT_ID}
    assert {call["timeout"] for call in client.calls} == {9}
    assert {call["temperature"] for call in client.calls} == {0.1}
    assert {call["max_tokens"] for call in client.calls} == {64}


def test_build_scenario_messages_render_expected_prompt_surface() -> None:
    scenario = load_scenario_set(VALID_FIXTURES).scenarios[0]

    messages = build_scenario_messages(
        scenario,
        commands=_command_surface(),
        skill_cards=get_default_registry(),
    )

    assert [message["role"] for message in messages] == ["system", "user"]
    prompt = messages[1]["content"]
    assert "Scenario: baseline-observe-area" in prompt
    assert "Available command tokens:" in prompt
    assert "- !observe" in prompt
    assert "## Skill Card: observe" in prompt
    assert "Disallowed command tokens:" in prompt
    assert "!stop" in prompt

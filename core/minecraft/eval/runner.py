"""Async text-only runner for Minecraft command eval scenarios."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from core.minecraft.commands import CommandSchema, CommandSchemaSet
from core.minecraft.scenarios import Scenario, ScenarioSet
from core.minecraft.skill_cards import SkillCardSet, get_default_registry
from core.models import LLMResponse

DEFAULT_AGENT_ID = "mc_command_eval"


class ChatCompletionClient(Protocol):
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
        """Return one chat completion for an eval prompt."""


SystemPromptFn = Callable[[Scenario], str]


@dataclass(frozen=True, slots=True)
class ScenarioRunResult:
    """Raw model output and metadata for one scenario."""

    scenario_id: str
    status: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: Decimal
    latency_ms: int
    openrouter_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "status": self.status,
            "content": self.content,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost": str(self.estimated_cost),
            "latency_ms": self.latency_ms,
            "openrouter_id": self.openrouter_id,
        }


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Aggregated metadata for one provider/model eval collection run."""

    provider: str
    model: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: Decimal
    results: tuple[ScenarioRunResult, ...]
    base_url: str | None = None
    key_present: bool | None = None

    @property
    def collected_count(self) -> int:
        return sum(1 for result in self.results if result.status == "collected")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "key_present": self.key_present,
            "request_count": self.request_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost": str(self.estimated_cost),
            "collected_count": self.collected_count,
            "results": [result.to_dict() for result in self.results],
        }


async def run_eval(
    scenario_set: ScenarioSet,
    *,
    client: ChatCompletionClient,
    model: str,
    provider: str | None = None,
    base_url: str | None = None,
    key_present: bool | None = None,
    commands: CommandSchemaSet | Mapping[str, CommandSchema] | None = None,
    skill_cards: SkillCardSet | None = None,
    system_prompt_fn: SystemPromptFn | None = None,
    timeout: float = 30.0,
    max_tokens: int | None = 256,
    temperature: float = 0.2,
) -> RunSummary:
    """Collect raw model outputs for scenarios without parsing or scoring them."""

    resolved_provider = provider or str(getattr(client, "provider", "unknown"))
    results: list[ScenarioRunResult] = []

    for scenario in scenario_set.scenarios:
        messages = build_scenario_messages(
            scenario,
            commands=commands or CommandSchemaSet(),
            skill_cards=skill_cards or get_default_registry(),
            system_prompt_fn=system_prompt_fn,
        )
        response = await client.complete(
            messages,
            model=model,
            agent_id=DEFAULT_AGENT_ID,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        results.append(
            ScenarioRunResult(
                scenario_id=scenario.id,
                status="collected",
                content=response.content,
                prompt_tokens=response.input_tokens,
                completion_tokens=response.output_tokens,
                estimated_cost=response.estimated_cost,
                latency_ms=response.latency_ms,
                openrouter_id=response.openrouter_id,
            )
        )

    result_tuple = tuple(results)
    return RunSummary(
        provider=resolved_provider,
        model=model,
        base_url=base_url,
        key_present=key_present,
        request_count=len(result_tuple),
        prompt_tokens=sum(result.prompt_tokens for result in result_tuple),
        completion_tokens=sum(result.completion_tokens for result in result_tuple),
        estimated_cost=sum(
            (result.estimated_cost for result in result_tuple),
            Decimal("0"),
        ),
        results=result_tuple,
    )


def build_scenario_messages(
    scenario: Scenario,
    *,
    commands: CommandSchemaSet | Mapping[str, CommandSchema],
    skill_cards: SkillCardSet,
    system_prompt_fn: SystemPromptFn | None = None,
) -> list[dict[str, str]]:
    """Render a deterministic Director/Mindcraft-style prompt for one scenario."""

    selected_cards = skill_cards.select(
        ids=scenario.skill_card_ids,
        available_commands=scenario.available_commands,
    )
    system_prompt = (
        system_prompt_fn(scenario) if system_prompt_fn is not None else _default_system_prompt()
    )
    user_prompt = "\n".join(
        (
            f"Scenario: {scenario.id}",
            f"Seed: {scenario.seed}",
            "",
            "Context:",
            scenario.prompt_context.strip(),
            "",
            "Inventory:",
            *_inventory_lines(scenario),
            "",
            "Tools:",
            *_tool_lines(scenario),
            "",
            "Available command tokens:",
            *_token_lines(scenario.available_commands),
            "",
            "Disallowed command tokens:",
            *_token_lines(scenario.disallowed_commands),
            "",
            "Expected constraints for later scoring:",
            *_constraint_lines(scenario),
            "",
            "Skill cards:",
            selected_cards.render_prompt(commands) or "(no matching skill cards)",
            "",
            "Return either one valid command line using the available command tokens, "
            "or a concise `chat:` response when no safe command applies.",
        )
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _default_system_prompt() -> str:
    return (
        "You are selecting the next text-only Minecraft action for an agent. "
        "Use only the available command surface. Do not invent commands. "
        "Prefer a safe chat-only response when the request is blocked or unclear."
    )


def _inventory_lines(scenario: Scenario) -> tuple[str, ...]:
    if not scenario.inventory:
        return ("- none",)
    return tuple(
        f"- {item.name}: count={item.count}"
        + (f", slot={item.slot}" if item.slot is not None else "")
        for item in scenario.inventory
    )


def _tool_lines(scenario: Scenario) -> tuple[str, ...]:
    if not scenario.tools:
        return ("- none",)
    return tuple(
        f"- {tool.name}"
        + (f": durability_pct={tool.durability_pct}" if tool.durability_pct is not None else "")
        for tool in scenario.tools
    )


def _token_lines(tokens: tuple[str, ...]) -> tuple[str, ...]:
    if not tokens:
        return ("- none",)
    return tuple(f"- {token}" for token in tokens)


def _constraint_lines(scenario: Scenario) -> tuple[str, ...]:
    if not scenario.expected_constraints:
        return ("- none",)
    lines: list[str] = []
    for constraint in scenario.expected_constraints:
        suffix = f", value={constraint.value!r}" if constraint.value is not None else ""
        lines.append(
            f"- {constraint.kind}: target={constraint.target}, "
            f"must_be_true={constraint.must_be_true}{suffix}"
        )
    return tuple(lines)

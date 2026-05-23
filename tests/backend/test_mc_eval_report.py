"""Tests for Minecraft command eval artifact writers."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from core.minecraft.commands import CommandParam, CommandSchema, CommandSchemaSet
from core.minecraft.eval.report import (
    comparison_md_text,
    report_md_text,
    score_run,
    scores_json_dict,
    write_generations_ndjson,
    write_passing_prompts_ndjson,
    write_report_md,
    write_scores_json,
)
from core.minecraft.eval.runner import RunSummary, ScenarioRunResult
from core.minecraft.scenarios import Scenario, ScenarioSet, SemanticConstraint

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "mc_eval_reports"


def _command_surface() -> CommandSchemaSet:
    return CommandSchemaSet(
        commands=(
            CommandSchema(name="!observe", description="Observe nearby blocks."),
            CommandSchema(
                name="!move",
                description="Move a short distance.",
                params=(CommandParam(name="distance", type="int"),),
            ),
            CommandSchema(name="!inventory", description="Inspect inventory."),
            CommandSchema(name="!stop", description="Stop the bot.", disallowed=True),
        ),
        disallowed=("!stop",),
    )


def _constraint(kind: str, target: str, value: object | None = None) -> SemanticConstraint:
    return SemanticConstraint(kind=kind, target=target, value=value)


def _scenario(
    scenario_id: str,
    *,
    seed: int,
    available_commands: tuple[str, ...],
    constraints: tuple[SemanticConstraint, ...],
) -> Scenario:
    return Scenario(
        id=scenario_id,
        seed=seed,
        prompt_context=f"Prompt context for {scenario_id}.",
        inventory=(),
        tools=(),
        available_commands=available_commands,
        disallowed_commands=("!stop",),
        skill_card_ids=("safety",),
        expected_constraints=constraints,
        tags=("fixture",),
        source="tests/backend/test_mc_eval_report.py",
    )


def _scenario_set() -> ScenarioSet:
    return ScenarioSet(
        scenarios=(
            _scenario(
                "valid-command",
                seed=501,
                available_commands=("!observe", "!inventory"),
                constraints=(
                    _constraint("require_command", "!observe"),
                    _constraint("must_observe_first", "next_action"),
                    _constraint("max_steps", "commands", 1),
                ),
            ),
            _scenario(
                "accepted-chat",
                seed=502,
                available_commands=(),
                constraints=(
                    _constraint("require_chat_only", "response"),
                    _constraint("forbid_command", "!stop"),
                    _constraint("max_steps", "commands", 0),
                ),
            ),
            _scenario(
                "malformed-output",
                seed=503,
                available_commands=("!observe",),
                constraints=(_constraint("require_command", "!observe"),),
            ),
            _scenario(
                "unknown-command",
                seed=504,
                available_commands=("!observe",),
                constraints=(_constraint("require_command", "!observe"),),
            ),
        )
    )


def _result(scenario_id: str, content: str, index: int) -> ScenarioRunResult:
    return ScenarioRunResult(
        scenario_id=scenario_id,
        status="collected",
        content=content,
        prompt_tokens=10 + index,
        completion_tokens=3 + index,
        estimated_cost=Decimal("0.001") * index,
        latency_ms=20 + index,
        openrouter_id=f"gen-{index}",
    )


def _run_summary() -> RunSummary:
    results = (
        _result("unknown-command", "!teleport home", 4),
        _result("valid-command", "!observe", 1),
        _result("accepted-chat", "chat: I cannot run !stop, but I can keep watch.", 2),
        _result("malformed-output", "I should observe first.", 3),
    )
    return RunSummary(
        provider="lmstudio",
        model="qwen-local",
        base_url="http://localhost:1234/v1",
        key_present=True,
        request_count=len(results),
        prompt_tokens=sum(result.prompt_tokens for result in results),
        completion_tokens=sum(result.completion_tokens for result in results),
        estimated_cost=sum((result.estimated_cost for result in results), Decimal("0")),
        results=results,
    )


def _scored_run():
    return score_run(_run_summary(), _scenario_set(), _command_surface())


def test_score_run_pairs_results_with_originating_scenarios_and_counts_outcomes() -> None:
    scored = _scored_run()

    assert [item.scenario.id for item in scored.scenarios] == [
        "unknown-command",
        "valid-command",
        "accepted-chat",
        "malformed-output",
    ]
    assert scored.outcome_counts == {
        "accepted_chat": 1,
        "accepted_command": 1,
        "disallowed_tool": 0,
        "invalid_arg": 0,
        "malformed": 1,
        "semantic_reject": 0,
        "total": 4,
        "unknown_command": 1,
        "unsafe_context": 0,
        "wrong_args": 0,
    }


def test_generation_ndjson_and_passing_prompts_have_expected_line_shapes(tmp_path: Path) -> None:
    scored = _scored_run()
    generations_path = tmp_path / "generations.ndjson"
    passing_path = tmp_path / "passing-prompts.ndjson"

    write_generations_ndjson(generations_path, scored)
    write_passing_prompts_ndjson(passing_path, scored)

    generation_lines = [
        json.loads(line) for line in generations_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(generation_lines) == 4
    assert generation_lines[0]["scenario_id"] == "unknown-command"
    assert generation_lines[0]["outcome"] == "unknown_command"
    assert generation_lines[0]["command_token"] == "!teleport"
    assert generation_lines[0]["openrouter_id"] == "gen-4"

    passing_lines = [
        json.loads(line) for line in passing_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [line["scenario_id"] for line in passing_lines] == ["valid-command"]
    assert passing_lines[0]["command_token"] == "!observe"
    assert passing_lines[0]["available_commands"] == ["!observe", "!inventory"]


def test_scores_json_matches_snapshot(tmp_path: Path) -> None:
    output_path = tmp_path / "scores.json"

    write_scores_json(output_path, _scored_run())

    assert json.loads(output_path.read_text(encoding="utf-8")) == scores_json_dict(
        _scored_run()
    )
    assert output_path.read_text(encoding="utf-8") == (
        FIXTURE_DIR / "scores.json"
    ).read_text(encoding="utf-8")


def test_report_md_matches_snapshot_and_buckets_examples(tmp_path: Path) -> None:
    output_path = tmp_path / "report.md"

    write_report_md(output_path, _scored_run())

    report = output_path.read_text(encoding="utf-8")
    assert report == report_md_text(_scored_run())
    assert report == (FIXTURE_DIR / "report.md").read_text(encoding="utf-8")
    assert "## Malformed Examples" in report
    assert "## Rejected Examples" in report
    assert "## Accepted Chat-Only Examples" in report
    assert "## Valid Command Examples" in report


def test_comparison_summary_aggregates_two_runs() -> None:
    first = _scored_run()
    second = replace(
        first,
        run_summary=replace(
            first.run_summary,
            provider="openrouter",
            model="openai/test-model",
            prompt_tokens=100,
            completion_tokens=25,
            estimated_cost=Decimal("0.25"),
        ),
        outcome_counts={
            **first.outcome_counts,
            "accepted_chat": 0,
            "accepted_command": 2,
            "malformed": 0,
            "unknown_command": 2,
        },
    )

    comparison = comparison_md_text((first, second))

    assert "| lmstudio | qwen-local | 25.0% | 1 | 1 | 1 | 72 | 0.010 |" in comparison
    assert "| openrouter | openai/test-model | 50.0% | 0 | 2 | 0 | 125 | 0.25 |" in comparison

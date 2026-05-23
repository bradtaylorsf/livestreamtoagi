"""Artifact writers for text-only Minecraft command eval runs."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from core.minecraft.commands import CommandSchema, CommandSchemaSet
from core.minecraft.eval.evaluator import EvalOutcome, EvalReport, evaluate_response
from core.minecraft.eval.runner import RunSummary, ScenarioRunResult
from core.minecraft.scenarios import Scenario, ScenarioSet

OUTCOME_COUNT_KEYS: tuple[str, ...] = (
    "malformed",
    "unknown_command",
    "disallowed_tool",
    "wrong_args",
    "invalid_arg",
    "unsafe_context",
    "semantic_reject",
    "accepted_chat",
    "accepted_command",
    "total",
)

REJECTED_OUTCOMES: frozenset[str] = frozenset(
    (
        "unknown_command",
        "disallowed_tool",
        "wrong_args",
        "invalid_arg",
        "unsafe_context",
        "semantic_reject",
    )
)


@dataclass(frozen=True, slots=True)
class ScoredScenario:
    """One raw generation paired with its scenario and semantic eval report."""

    scenario: Scenario
    result: ScenarioRunResult
    report: EvalReport


@dataclass(frozen=True, slots=True)
class ScoredRun:
    """A provider/model run with semantic outcomes aggregated for reporting."""

    run_summary: RunSummary
    scenarios: tuple[ScoredScenario, ...]
    outcome_counts: dict[str, int]

    @property
    def total(self) -> int:
        return self.outcome_counts["total"]

    @property
    def rejected_count(self) -> int:
        return sum(self.outcome_counts[key] for key in REJECTED_OUTCOMES)

    @property
    def accepted_command_pct(self) -> float:
        if self.total == 0:
            return 0.0
        return self.outcome_counts["accepted_command"] / self.total * 100


def score_run(
    run_summary: RunSummary,
    scenarios: ScenarioSet | Sequence[Scenario],
    commands: CommandSchemaSet | Mapping[str, CommandSchema],
) -> ScoredRun:
    """Score each collected generation against its originating scenario."""

    scenario_items = scenarios.scenarios if isinstance(scenarios, ScenarioSet) else tuple(scenarios)
    by_id = {scenario.id: scenario for scenario in scenario_items}
    scored: list[ScoredScenario] = []

    for result in run_summary.results:
        scenario = by_id.get(result.scenario_id)
        if scenario is None:
            raise ValueError(f"missing scenario for generation: {result.scenario_id}")
        report = evaluate_response(scenario, result.content, commands)
        scored.append(ScoredScenario(scenario=scenario, result=result, report=report))

    return ScoredRun(
        run_summary=run_summary,
        scenarios=tuple(scored),
        outcome_counts=_outcome_counts(tuple(scored)),
    )


def write_generations_ndjson(path: str | Path, scored_run: ScoredRun) -> None:
    """Write one JSON line per model generation with parse and score metadata."""

    _write_ndjson(path, (_generation_record(item) for item in scored_run.scenarios))


def write_scores_json(path: str | Path, scored_run: ScoredRun) -> None:
    """Write deterministic aggregate and per-scenario scores."""

    _write_json(path, scores_json_dict(scored_run))


def write_report_md(path: str | Path, scored_run: ScoredRun) -> None:
    """Write a human-readable markdown report for one scored run."""

    _write_text(path, report_md_text(scored_run))


def write_passing_prompts_ndjson(path: str | Path, scored_run: ScoredRun) -> None:
    """Write accepted command prompts suitable for promotion into live smoke jobs."""

    _write_ndjson(
        path,
        (
            _passing_prompt_record(item)
            for item in _sorted_scenarios(scored_run)
            if _outcome_key(item) == "accepted_command"
        ),
    )


def write_comparison_md(path: str | Path, scored_runs: Sequence[ScoredRun]) -> None:
    """Write a markdown comparison table for provider/model scored runs."""

    _write_text(path, comparison_md_text(scored_runs))


def scores_json_dict(scored_run: ScoredRun) -> dict[str, Any]:
    """Return the deterministic structure used by ``scores.json``."""

    summary = scored_run.run_summary
    return {
        "aggregate": {
            "completion_tokens": summary.completion_tokens,
            "estimated_cost": str(summary.estimated_cost),
            "prompt_tokens": summary.prompt_tokens,
            "total_tokens": summary.prompt_tokens + summary.completion_tokens,
        },
        "base_url": summary.base_url,
        "key_present": summary.key_present,
        "model": summary.model,
        "outcome_counts": dict(scored_run.outcome_counts),
        "per_scenario": [_scenario_score_record(item) for item in _sorted_scenarios(scored_run)],
        "provider": summary.provider,
        "totals": {
            "collected": summary.collected_count,
            "request_count": summary.request_count,
            "scenarios": len(scored_run.scenarios),
            "total": scored_run.total,
        },
    }


def report_md_text(scored_run: ScoredRun) -> str:
    """Return deterministic markdown report text."""

    summary = scored_run.run_summary
    lines = [
        "# Minecraft Command Eval Report",
        "",
        f"- Provider: `{summary.provider}`",
        f"- Model: `{summary.model}`",
        f"- Base URL: `{summary.base_url or 'n/a'}`",
        f"- Key present: `{_format_bool(summary.key_present)}`",
        f"- Request count: `{summary.request_count}`",
        f"- Collected: `{summary.collected_count}/{len(summary.results)}`",
        f"- Scenarios scored: `{scored_run.total}`",
        "",
        "## Outcome Breakdown",
        "",
        "| Outcome | Count |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| `{key}` | {scored_run.outcome_counts[key]} |" for key in OUTCOME_COUNT_KEYS
    )
    lines.extend(
        [
            "",
            "## Malformed Examples",
            "",
            *_example_lines(scored_run, ("malformed",)),
            "",
            "## Rejected Examples",
            "",
            *_example_lines(scored_run, tuple(sorted(REJECTED_OUTCOMES))),
            "",
            "## Accepted Chat-Only Examples",
            "",
            *_example_lines(scored_run, ("accepted_chat",)),
            "",
            "## Valid Command Examples",
            "",
            *_example_lines(scored_run, ("accepted_command",)),
            "",
            "## Token And Cost Summary",
            "",
            f"- Prompt tokens: `{summary.prompt_tokens}`",
            f"- Completion tokens: `{summary.completion_tokens}`",
            f"- Total tokens: `{summary.prompt_tokens + summary.completion_tokens}`",
            f"- Estimated cost: `{summary.estimated_cost}`",
            "",
        ]
    )
    return "\n".join(lines)


def comparison_md_text(scored_runs: Sequence[ScoredRun]) -> str:
    """Return a deterministic markdown comparison table."""

    lines = [
        "# Minecraft Command Eval Model Comparison",
        "",
        "| Provider | Model | Accepted % | Malformed | Rejected | Chat Only | Tokens | Cost |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scored_run in sorted(
        scored_runs,
        key=lambda item: (item.run_summary.provider, item.run_summary.model),
    ):
        summary = scored_run.run_summary
        counts = scored_run.outcome_counts
        total_tokens = summary.prompt_tokens + summary.completion_tokens
        lines.append(
            "| "
            f"{_escape_table(summary.provider)} | "
            f"{_escape_table(summary.model)} | "
            f"{scored_run.accepted_command_pct:.1f}% | "
            f"{counts['malformed']} | "
            f"{scored_run.rejected_count} | "
            f"{counts['accepted_chat']} | "
            f"{total_tokens} | "
            f"{summary.estimated_cost} |"
        )
    lines.append("")
    return "\n".join(lines)


def scored_run_from_scores_json(data: Mapping[str, Any]) -> ScoredRun:
    """Rehydrate enough of a ``scores.json`` file for comparison summaries."""

    aggregate = _mapping(data.get("aggregate"))
    totals = _mapping(data.get("totals"))
    outcome_counts = _normalize_outcome_counts(data.get("outcome_counts"))
    prompt_tokens = _int_value(aggregate.get("prompt_tokens"))
    completion_tokens = _int_value(aggregate.get("completion_tokens"))
    summary = RunSummary(
        provider=str(data.get("provider", "unknown")),
        model=str(data.get("model", "unknown")),
        base_url=_optional_str(data.get("base_url")),
        key_present=_optional_bool(data.get("key_present")),
        request_count=_int_value(totals.get("request_count")),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost=Decimal(str(aggregate.get("estimated_cost", "0"))),
        results=(),
    )
    return ScoredRun(run_summary=summary, scenarios=(), outcome_counts=outcome_counts)


def _outcome_counts(scored: tuple[ScoredScenario, ...]) -> dict[str, int]:
    counts = {key: 0 for key in OUTCOME_COUNT_KEYS}
    for item in scored:
        counts[_outcome_key(item)] += 1
        counts["total"] += 1
    return counts


def _outcome_key(item: ScoredScenario) -> str:
    if item.report.outcome == EvalOutcome.ACCEPTED:
        return "accepted_chat" if item.report.parsed.kind == "chat" else "accepted_command"
    return item.report.outcome.value


def _sorted_scenarios(scored_run: ScoredRun) -> tuple[ScoredScenario, ...]:
    return tuple(sorted(scored_run.scenarios, key=lambda item: item.scenario.id))


def _generation_record(item: ScoredScenario) -> dict[str, Any]:
    parsed = item.report.parsed
    result = item.result
    return {
        "args": list(parsed.args),
        "chat_text": parsed.chat_text,
        "command_token": parsed.command_token,
        "completion_tokens": result.completion_tokens,
        "content": result.content,
        "estimated_cost": str(result.estimated_cost),
        "kind": parsed.kind,
        "latency_ms": result.latency_ms,
        "matched_command": item.report.matched_command,
        "openrouter_id": result.openrouter_id,
        "outcome": _outcome_key(item),
        "parse_error": parsed.parse_error,
        "prompt_tokens": result.prompt_tokens,
        "raw": parsed.raw,
        "reasons": list(item.report.reasons),
        "scenario_id": item.scenario.id,
        "status": result.status,
    }


def _scenario_score_record(item: ScoredScenario) -> dict[str, Any]:
    parsed = item.report.parsed
    result = item.result
    return {
        "completion_tokens": result.completion_tokens,
        "estimated_cost": str(result.estimated_cost),
        "latency_ms": result.latency_ms,
        "matched_command": item.report.matched_command,
        "openrouter_id": result.openrouter_id,
        "outcome": _outcome_key(item),
        "parsed_kind": parsed.kind,
        "prompt_tokens": result.prompt_tokens,
        "reasons": list(item.report.reasons),
        "scenario_id": item.scenario.id,
        "status": result.status,
    }


def _passing_prompt_record(item: ScoredScenario) -> dict[str, Any]:
    parsed = item.report.parsed
    scenario = item.scenario
    return {
        "args": list(parsed.args),
        "available_commands": list(scenario.available_commands),
        "command_token": parsed.command_token,
        "expected_constraints": [
            constraint.to_dict() for constraint in scenario.expected_constraints
        ],
        "prompt_context": scenario.prompt_context,
        "raw_content": item.result.content,
        "scenario_id": scenario.id,
        "seed": scenario.seed,
    }


def _example_lines(scored_run: ScoredRun, outcome_keys: tuple[str, ...]) -> list[str]:
    items = [item for item in _sorted_scenarios(scored_run) if _outcome_key(item) in outcome_keys]
    if not items:
        return ["None."]
    lines: list[str] = []
    for item in items:
        reasons = "; ".join(item.report.reasons) if item.report.reasons else "none"
        matched = item.report.matched_command or "n/a"
        lines.append(
            f"- `{item.scenario.id}`: outcome=`{_outcome_key(item)}`, "
            f"matched=`{matched}`, reasons={_inline_code(reasons)}, "
            f"content={_inline_code(_truncate(item.result.content))}"
        )
    return lines


def _truncate(value: str, limit: int = 220) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _inline_code(value: str) -> str:
    sanitized = value.replace("`", "'")
    return f"`{sanitized}`"


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|")


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return str(value).lower()


def _write_ndjson(path: str | Path, records: Iterable[Mapping[str, Any]]) -> None:
    text = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    _write_text(path, text)


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: str | Path, text: str) -> None:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalize_outcome_counts(value: Any) -> dict[str, int]:
    raw = _mapping(value)
    return {key: _int_value(raw.get(key)) for key in OUTCOME_COUNT_KEYS}


def _int_value(value: Any) -> int:
    if type(value) is int:
        return value
    return 0


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_bool(value: Any) -> bool | None:
    return value if type(value) is bool else None

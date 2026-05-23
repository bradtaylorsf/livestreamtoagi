"""CLI for text-only Minecraft command provider evals."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from core.minecraft.commands import (
    DEFAULT_DISALLOWED_COMMANDS,
    CommandSchema,
    CommandSchemaSet,
    extract_from_default_locations,
)
from core.minecraft.eval.provider import (
    ClientFactory,
    ProviderConfig,
    ProviderConfigError,
    resolve_provider_config,
)
from core.minecraft.eval.report import (
    OUTCOME_COUNT_KEYS,
    ScoredRun,
    score_run,
    scored_run_from_scores_json,
    write_comparison_md,
    write_generations_ndjson,
    write_passing_prompts_ndjson,
    write_report_md,
    write_scores_json,
)
from core.minecraft.eval.runner import RunSummary, run_eval
from core.minecraft.scenarios import ScenarioSet, ScenarioValidationError, load_scenario_set
from core.minecraft.skill_cards import SkillCardSet, get_default_registry
from core.models import LLMResponse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCENARIOS = PROJECT_ROOT / "tests" / "backend" / "fixtures" / "mc_scenarios" / "valid"


class DryRunClient:
    """Fake provider client for deterministic smoke runs."""

    def __init__(self, provider: str) -> None:
        self.provider = provider

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
        return LLMResponse(
            content="chat: dry-run command eval collection",
            model=model,
            input_tokens=0,
            output_tokens=0,
            estimated_cost=Decimal("0"),
            latency_ms=0,
        )

    async def close(self) -> None:
        return None


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    load_env: bool = True,
) -> int:
    """Run the command eval CLI and return a process exit code."""

    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code)

    if load_env and env is None:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    resolved_env = os.environ if env is None else env

    try:
        config = resolve_provider_config(args, resolved_env)
        scenario_set, commands, skill_cards = _load_inputs(args.scenarios, args.limit)
        if args.list_only:
            _emit_listing(
                config,
                scenario_set=scenario_set,
                commands=commands,
                json_mode=args.json,
                stdout=out,
            )
            if args.output:
                _write_listing_output(args.output, config, scenario_set, commands)
            return 0

        summary = asyncio.run(
            _run_with_client(
                scenario_set,
                config=config,
                commands=commands,
                skill_cards=skill_cards,
                dry_run=args.dry_run,
                client_factory=client_factory,
            )
        )
        scored_run = score_run(summary, scenario_set, commands)
        if args.report_dir:
            _write_report_artifacts(args.report_dir, scored_run)
        if args.passing_prompts:
            _write_passing_prompts(args.passing_prompts, scored_run)
        if args.compare:
            _write_comparison(args.report_dir, scored_run, args.compare)

        _emit_summary(summary, scored_run=scored_run, json_mode=args.json, stdout=out)
        if args.output:
            _write_output(args.output, summary)
    except (ProviderConfigError, ScenarioValidationError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=err)
        return 1
    except Exception as exc:
        print(f"ERROR: command eval failed: {exc}", file=err)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run text-only Minecraft command eval prompts against a provider",
    )
    parser.add_argument(
        "--scenarios",
        default=str(DEFAULT_SCENARIOS.relative_to(PROJECT_ROOT)),
        help="Scenario JSON file or directory",
    )
    parser.add_argument(
        "--provider",
        choices=("openrouter", "lmstudio", "openai-compatible"),
        default=None,
        help="Provider to use. Defaults to LLM_PROVIDER or lmstudio.",
    )
    parser.add_argument("--model", default=None, help="Model ID to request")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible provider base URL")
    parser.add_argument("--api-key", default=None, help="Provider API key. Never printed.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Provider timeout in seconds")
    parser.add_argument("--max-tokens", type=int, default=256, help="Max completion tokens")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--limit", type=int, default=None, help="Limit scenarios collected")
    parser.add_argument(
        "--dry-run", action="store_true", help="Render prompts and skip network I/O"
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print resolved eval inputs and exit before provider client construction",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary")
    parser.add_argument("--output", default=None, help="Write JSON summary artifact to this path")
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Write scored generations.ndjson, scores.json, and report.md artifacts here",
    )
    parser.add_argument(
        "--passing-prompts",
        default=None,
        help="Write accepted command prompts to this NDJSON path",
    )
    parser.add_argument(
        "--compare",
        action="append",
        default=[],
        help=("Existing scores.json path to include in report-dir/comparison.md. May be repeated."),
    )
    return parser


def _load_inputs(
    scenarios_arg: str,
    limit: int | None,
) -> tuple[ScenarioSet, CommandSchemaSet, SkillCardSet]:
    if limit is not None and limit < 0:
        raise ValueError("--limit must be non-negative")

    commands = _default_command_schema_set(PROJECT_ROOT)
    scenario_path = _resolve_path(scenarios_arg)
    scenario_set = load_scenario_set(scenario_path, commands=commands)
    if limit is not None:
        scenario_set = replace(scenario_set, scenarios=scenario_set.scenarios[:limit])
    return scenario_set, commands, get_default_registry()


def _resolve_path(path_arg: str) -> Path:
    path = Path(path_arg)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _default_command_schema_set(repo_root: Path) -> CommandSchemaSet:
    extracted = extract_from_default_locations(repo_root)
    present = {command.name for command in extracted.commands}
    present.update(alias for command in extracted.commands for alias in command.aliases)
    fallback_commands: list[CommandSchema] = []
    for command_name in _skill_card_command_names(get_default_registry()):
        if command_name in present or command_name in extracted.disallowed:
            continue
        fallback_commands.append(
            CommandSchema(
                name=command_name,
                description=f"{command_name} command from built-in skill-card registry.",
                source="skill-card-fallback",
            )
        )
        present.add(command_name)

    return CommandSchemaSet(
        commands=(*extracted.commands, *tuple(fallback_commands)),
        disallowed=tuple({*DEFAULT_DISALLOWED_COMMANDS, *extracted.disallowed}),
    )


def _skill_card_command_names(skill_cards: SkillCardSet) -> tuple[str, ...]:
    command_names: set[str] = set()
    for card in skill_cards.cards:
        command_names.update(card.allowed_commands)
        command_names.update(card.disallowed_commands)
    return tuple(sorted(command_names))


async def _run_with_client(
    scenario_set: ScenarioSet,
    *,
    config: ProviderConfig,
    commands: CommandSchemaSet,
    skill_cards: SkillCardSet,
    dry_run: bool,
    client_factory: ClientFactory | None,
) -> RunSummary:
    client = DryRunClient(config.provider) if dry_run else _make_client(config, client_factory)
    try:
        return await run_eval(
            scenario_set,
            client=client,
            model=config.model,
            provider=config.provider,
            base_url=config.base_url,
            key_present=config.api_key_present,
            commands=commands,
            skill_cards=skill_cards,
            timeout=config.timeout,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def _make_client(config: ProviderConfig, client_factory: ClientFactory | None) -> Any:
    if client_factory is not None:
        return client_factory(config)
    return config.create_client()


def _listing_payload(
    config: ProviderConfig,
    *,
    scenario_set: ScenarioSet,
    commands: CommandSchemaSet,
) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    alias_count = 0
    for command in commands.commands:
        source = command.source or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
        alias_count += len(command.aliases)

    return {
        "mode": "list-only",
        **config.public_metadata(),
        "scenario_count": len(scenario_set.scenarios),
        "scenario_ids": [scenario.id for scenario in scenario_set.scenarios],
        "commands": {
            "command_count": len(commands.commands),
            "alias_count": alias_count,
            "disallowed_count": len(commands.disallowed),
            "source_counts": dict(sorted(source_counts.items())),
        },
    }


def _emit_listing(
    config: ProviderConfig,
    *,
    scenario_set: ScenarioSet,
    commands: CommandSchemaSet,
    json_mode: bool,
    stdout: TextIO,
) -> None:
    payload = _listing_payload(config, scenario_set=scenario_set, commands=commands)
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return

    command_summary = payload["commands"]
    print("Minecraft command eval inputs", file=stdout)
    print(f"mode: {payload['mode']}", file=stdout)
    print(f"provider: {payload['provider']}", file=stdout)
    print(f"model: {payload['model']}", file=stdout)
    print(f"base_url: {payload['base_url']}", file=stdout)
    print(f"key_present: {str(payload['key_present']).lower()}", file=stdout)
    print(f"scenario_count: {payload['scenario_count']}", file=stdout)
    print("scenario_ids:", file=stdout)
    for scenario_id in payload["scenario_ids"]:
        print(f"- {scenario_id}", file=stdout)
    print(
        "commands: "
        f"command_count={command_summary['command_count']}, "
        f"alias_count={command_summary['alias_count']}, "
        f"disallowed_count={command_summary['disallowed_count']}",
        file=stdout,
    )
    if command_summary["source_counts"]:
        sources = ", ".join(
            f"{source}={count}" for source, count in command_summary["source_counts"].items()
        )
        print(f"command_sources: {sources}", file=stdout)


def _emit_summary(
    summary: RunSummary,
    *,
    scored_run: ScoredRun,
    json_mode: bool,
    stdout: TextIO,
) -> None:
    if json_mode:
        print(json.dumps(summary.to_dict(), indent=2, sort_keys=True), file=stdout)
        return

    print("Minecraft command eval", file=stdout)
    print(f"provider: {summary.provider}", file=stdout)
    print(f"model: {summary.model}", file=stdout)
    if summary.base_url:
        print(f"base_url: {summary.base_url}", file=stdout)
    if summary.key_present is not None:
        print(f"key_present: {str(summary.key_present).lower()}", file=stdout)
    print(f"request_count: {summary.request_count}", file=stdout)
    print(f"prompt_tokens: {summary.prompt_tokens}", file=stdout)
    print(f"completion_tokens: {summary.completion_tokens}", file=stdout)
    print(f"estimated_cost: {summary.estimated_cost}", file=stdout)
    print(f"collected: {summary.collected_count}/{len(summary.results)}", file=stdout)
    print(
        "outcomes: "
        + ", ".join(f"{key}={scored_run.outcome_counts[key]}" for key in OUTCOME_COUNT_KEYS),
        file=stdout,
    )
    for result in summary.results:
        print(f"- {result.scenario_id}: {result.status}", file=stdout)


def _write_output(path_arg: str, summary: RunSummary) -> None:
    path = _resolve_path(path_arg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_listing_output(
    path_arg: str,
    config: ProviderConfig,
    scenario_set: ScenarioSet,
    commands: CommandSchemaSet,
) -> None:
    path = _resolve_path(path_arg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _listing_payload(config, scenario_set=scenario_set, commands=commands),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_report_artifacts(report_dir_arg: str, scored_run: ScoredRun) -> None:
    report_dir = _resolve_path(report_dir_arg)
    report_dir.mkdir(parents=True, exist_ok=True)
    write_generations_ndjson(report_dir / "generations.ndjson", scored_run)
    write_scores_json(report_dir / "scores.json", scored_run)
    write_report_md(report_dir / "report.md", scored_run)


def _write_passing_prompts(path_arg: str, scored_run: ScoredRun) -> None:
    write_passing_prompts_ndjson(_resolve_path(path_arg), scored_run)


def _write_comparison(
    report_dir_arg: str | None,
    current_run: ScoredRun,
    scores_paths: Sequence[str],
) -> None:
    if not report_dir_arg:
        raise ValueError("--compare requires --report-dir so comparison.md has a destination")

    runs = [current_run]
    for path_arg in scores_paths:
        runs.append(_load_scores_json(path_arg))
    write_comparison_md(_resolve_path(report_dir_arg) / "comparison.md", runs)


def _load_scores_json(path_arg: str) -> ScoredRun:
    path = _resolve_path(path_arg)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError(f"scores JSON must be an object: {path}")
    return scored_run_from_scores_json(payload)


if __name__ == "__main__":
    raise SystemExit(main())

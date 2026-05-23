"""CLI for replaying E17 passing prompt datasets through Minecraft live eval."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from core.minecraft.eval.dataset_replay import (
    DatasetLoadError,
    PassingPrompt,
    build_command_text,
    filter_prompts,
    load_passing_prompts,
    prompt_to_case_id,
)
from core.minecraft.eval.live_cli import (
    PROJECT_ROOT,
    LiveBridgeConfigError,
    _emit_summary,
    _make_bridge_client,
    _resolve_path,
    _write_output,
    _write_report_artifacts,
)
from core.minecraft.eval.live_profile import DEFAULT_PROFILE_NAME, EvalProfileError, resolve_profile
from core.minecraft.eval.live_runner import (
    BridgeClient,
    _case_error,
    _coerce_action_events,
    _now_ms,
    _profile_detail,
)
from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    LiveRunSummary,
    OutcomeClass,
    classify_bridge_status,
    classify_eval_category,
    derive_block_mutation,
    derive_inventory_delta,
    derive_pathfinding_signals,
)


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    bridge: BridgeClient | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    load_env: bool = True,
) -> int:
    """Run the dataset replay CLI and return a process exit code."""

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
        dataset_path = _resolve_path(args.dataset)
        prompts = load_passing_prompts(dataset_path)
        selected_prompts = filter_prompts(
            prompts,
            commands=args.command,
            scenario_ids=args.scenario,
            limit=args.limit,
        )
        selected_bridge, dry_run = (
            (bridge, False) if bridge is not None else _make_bridge_client(args, resolved_env)
        )
        summary = asyncio.run(
            run_dataset_replay(
                selected_prompts,
                bridge=selected_bridge,
                profile=args.profile,
                dry_run=dry_run,
                verbose=args.verbose,
                env=resolved_env,
                project_root=PROJECT_ROOT,
                dataset_path=dataset_path,
                total_prompts=len(prompts),
                filters={
                    "commands": list(args.command or ()),
                    "scenario_ids": list(args.scenario or ()),
                    "limit": args.limit,
                },
            )
        )
        if not selected_prompts and not args.json:
            print("No dataset prompts matched the selected filters.", file=out)
        if args.report_dir:
            _write_report_artifacts(args.report_dir, summary)
        if args.output:
            _write_output(args.output, summary)
        _emit_summary(summary, json_mode=args.json, verbose=args.verbose, stdout=out)
    except (
        DatasetLoadError,
        EvalProfileError,
        LiveBridgeConfigError,
        OSError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=err)
        return 1
    except Exception as exc:
        print(f"ERROR: Minecraft replay eval failed: {exc}", file=err)
        return 1
    return 0


async def run_dataset_replay(
    prompts: Iterable[PassingPrompt],
    *,
    bridge: BridgeClient,
    profile: str = DEFAULT_PROFILE_NAME,
    dry_run: bool = False,
    verbose: bool = False,
    env: Mapping[str, str] | None = None,
    project_root: Any | None = None,
    dataset_path: str | Path | None = None,
    total_prompts: int | None = None,
    filters: Mapping[str, Any] | None = None,
) -> LiveRunSummary:
    """Replay accepted text-eval commands through a live or fake Minecraft bridge."""

    resolved_profile = resolve_profile(profile, env=env, project_root=project_root)
    prompt_list = tuple(prompts)
    results: list[CaseResult] = []
    for index, prompt in enumerate(prompt_list, start=1):
        results.append(await _run_prompt(prompt, index=index, bridge=bridge))

    profile_detail = _profile_detail(resolved_profile)
    profile_detail["dataset_replay"] = _dataset_replay_detail(
        prompt_list,
        results,
        dataset_path=dataset_path,
        total_prompts=len(prompt_list) if total_prompts is None else total_prompts,
        filters=filters or {},
    )
    return LiveRunSummary(
        command="dataset-replay",
        resolved_command="dataset-replay",
        profile=resolved_profile.name,
        profile_detail=profile_detail,
        seed=0,
        dry_run=dry_run,
        verbose=verbose,
        case_results=tuple(results),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay E17 passing Minecraft command prompts in a live eval world",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to an E17 passing-prompts.ndjson artifact",
    )
    parser.add_argument(
        "--command",
        action="append",
        default=None,
        help="Command token filter. May be repeated; accepts move or !move.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="Scenario id filter. May be repeated.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Replay first N matches")
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help="Minecraft live eval profile name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force the deterministic fake bridge. Default unless MC_EVAL_LIVE_ENABLED=1.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--output", default=None, help="Write JSON summary artifact")
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Write summary.json, cases.ndjson, and report.md artifacts",
    )
    parser.add_argument("--verbose", action="store_true", help="Print per-action telemetry")
    return parser


async def _run_prompt(
    prompt: PassingPrompt,
    *,
    index: int,
    bridge: BridgeClient,
) -> CaseResult:
    case_id = prompt_to_case_id(prompt, index)
    command_text = build_command_text(prompt)
    action_id = case_id
    started_ms = _now_ms()
    events: list[ActionEvent] = [
        ActionEvent(
            action_id=action_id,
            kind="start",
            ts_ms=started_ms,
            payload={
                "args": list(prompt.args),
                "available_commands": list(prompt.available_commands),
                "case_id": case_id,
                "command": _display_command(prompt.command_token),
                "command_text": command_text,
                "command_token": prompt.command_token,
                "expected_constraints": [
                    dict(constraint) for constraint in prompt.expected_constraints
                ],
                "prompt_context": prompt.prompt_context,
                "raw_content": prompt.raw_content,
                "reasons": [dict(constraint) for constraint in prompt.expected_constraints],
                "scenario_id": prompt.scenario_id,
                "seed": prompt.seed,
            },
        )
    ]

    response: Mapping[str, Any]
    error: str | None = None
    try:
        response = await bridge.send_command(command_text)
    except TimeoutError as exc:
        response = {"status": "timeout", "error": str(exc), "final_state": {}}
        error = str(exc)
    except Exception as exc:
        response = {"status": "error", "error": str(exc), "final_state": {}}
        error = str(exc)

    events.extend(_coerce_action_events(response.get("action_events"), action_id))
    ended_ms = _now_ms()
    outcome_class = classify_bridge_status(
        response.get("status"),
        reason=response.get("reason") or response.get("outcome_class"),
        error=response.get("error"),
    )
    error = error or _case_error(outcome_class, response)
    final_state = response.get("final_state")
    if not isinstance(final_state, Mapping):
        final_state = {}
    display_command = _display_command(prompt.command_token)
    params = _params_for_prompt(prompt)
    eval_category = classify_eval_category(
        display_command,
        outcome_class,
        response.get("reason") or response.get("outcome_class") or error,
        final_state,
    )
    pathfinding = derive_pathfinding_signals(
        display_command,
        outcome_class,
        reason=response.get("reason") or response.get("outcome_class"),
        error=response.get("error") or error,
        final_state=final_state,
    )
    inventory = derive_inventory_delta(
        display_command,
        outcome_class,
        params=params,
        final_state=final_state,
    )
    block_mutation = derive_block_mutation(
        display_command,
        outcome_class,
        params=params,
        final_state=final_state,
    )
    events.append(
        ActionEvent(
            action_id=action_id,
            kind="end",
            ts_ms=ended_ms,
            payload={
                "case_id": case_id,
                "command": display_command,
                "outcome_class": outcome_class,
                "eval_category": eval_category,
                "pathfinding": pathfinding.to_dict() if pathfinding else None,
                "inventory": inventory.to_dict() if inventory else None,
                "block_mutation": block_mutation.to_dict() if block_mutation else None,
                "reason": response.get("reason"),
                "scenario_id": prompt.scenario_id,
                "status": response.get("status"),
                "latency_ms": max(0, ended_ms - started_ms),
            },
        )
    )

    return CaseResult(
        case_id=case_id,
        command_text=command_text,
        params=params,
        action_events=tuple(events),
        outcome_class=outcome_class,
        final_state=final_state,
        latency_ms=max(0, ended_ms - started_ms),
        error=error,
        eval_category=eval_category,
        pathfinding=pathfinding,
        inventory=inventory,
        block_mutation=block_mutation,
    )


def _dataset_replay_detail(
    prompts: Sequence[PassingPrompt],
    results: Sequence[CaseResult],
    *,
    dataset_path: str | Path | None,
    total_prompts: int,
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    command_counts = Counter(_display_command(prompt.command_token) for prompt in prompts)
    return {
        "command_counts": dict(sorted(command_counts.items())),
        "dataset_path": str(dataset_path) if dataset_path is not None else None,
        "filters": dict(filters),
        "per_category_outcome_counts": _per_category_outcome_counts(results),
        "per_command_block_mutation_match_counts": _per_command_match_counts(
            prompts,
            results,
            "block_mutation",
        ),
        "per_command_inventory_match_counts": _per_command_match_counts(
            prompts,
            results,
            "inventory",
        ),
        "per_command_outcome_counts": _per_command_outcome_counts(prompts, results),
        "selected_prompts": len(prompts),
        "total_prompts": total_prompts,
    }


def _per_command_outcome_counts(
    prompts: Sequence[PassingPrompt],
    results: Sequence[CaseResult],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for prompt, result in zip(prompts, results, strict=False):
        command = _display_command(prompt.command_token)
        bucket = counts.setdefault(command, {outcome: 0 for outcome in OutcomeClass.ALL})
        bucket[result.outcome_class] += 1
    return dict(sorted(counts.items()))


def _per_category_outcome_counts(
    results: Sequence[CaseResult],
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = counts.setdefault(
            result.eval_category, {outcome: 0 for outcome in OutcomeClass.ALL}
        )
        bucket[result.outcome_class] += 1
    return dict(sorted(counts.items()))


def _per_command_match_counts(
    prompts: Sequence[PassingPrompt],
    results: Sequence[CaseResult],
    field_name: str,
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for prompt, result in zip(prompts, results, strict=False):
        command = _display_command(prompt.command_token)
        bucket = counts.setdefault(command, {"match": 0, "mismatch": 0, "unknown": 0, "none": 0})
        detail = getattr(result, field_name)
        if detail is None:
            bucket["none"] += 1
        elif detail.matches_expected is True:
            bucket["match"] += 1
        elif detail.matches_expected is False:
            bucket["mismatch"] += 1
        else:
            bucket["unknown"] += 1
    return dict(sorted(counts.items()))


def _params_for_prompt(prompt: PassingPrompt) -> dict[str, Any]:
    params: dict[str, Any] = {
        "args": list(prompt.args),
        "available_commands": list(prompt.available_commands),
        "command_token": prompt.command_token,
        "expected_constraints": [dict(constraint) for constraint in prompt.expected_constraints],
        "raw_content": prompt.raw_content,
        "scenario_id": prompt.scenario_id,
        "seed": prompt.seed,
    }
    params.update(_mutation_expectations_from_constraints(prompt.expected_constraints))
    return params


def _mutation_expectations_from_constraints(
    constraints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    expected: dict[str, Any] = {}
    inventory_delta: dict[str, int] = {}
    expected_blocks: list[Mapping[str, Any]] = []

    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            continue
        inventory_raw = _constraint_value(
            constraint,
            ("expected_inventory_delta", "inventory_delta", "delta"),
            kinds=("inventory_delta", "expected_inventory_delta"),
        )
        if isinstance(inventory_raw, Mapping):
            for item, amount in inventory_raw.items():
                if isinstance(amount, bool):
                    continue
                try:
                    inventory_delta[str(item)] = int(amount)
                except (TypeError, ValueError):
                    continue

        blocks_raw = _constraint_value(
            constraint,
            ("expected_blocks", "placed_blocks", "blocks"),
            kinds=("expected_blocks", "placed_blocks", "block_mutation"),
        )
        if isinstance(blocks_raw, Sequence) and not isinstance(blocks_raw, (str, bytes)):
            expected_blocks.extend(
                dict(block) for block in blocks_raw if isinstance(block, Mapping)
            )

    if inventory_delta:
        expected["expected_inventory_delta"] = inventory_delta
    if expected_blocks:
        expected["expected_blocks"] = expected_blocks
    return expected


def _constraint_value(
    constraint: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    kinds: tuple[str, ...],
) -> object | None:
    wanted_keys = {key.casefold() for key in keys}
    for key, value in constraint.items():
        if str(key).casefold() in wanted_keys:
            return value

    kind = str(
        constraint.get("kind")
        or constraint.get("name")
        or constraint.get("type")
        or constraint.get("constraint")
        or ""
    ).casefold()
    if kind not in {value.casefold() for value in kinds}:
        return None
    for key in keys:
        value = constraint.get(key)
        if value is not None:
            return value
    return None


def _display_command(command_token: str) -> str:
    normalized = command_token.strip()
    if normalized.startswith("!"):
        normalized = normalized[1:]
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())

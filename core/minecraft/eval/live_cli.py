"""CLI for focused Minecraft live command smoke runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from core.minecraft.eval.live_profile import DEFAULT_PROFILE_NAME, EvalProfileError
from core.minecraft.eval.live_runner import (
    BridgeClient,
    FakeBridgeClient,
    run_live_command_smoke,
    supported_command_inputs,
)
from core.minecraft.eval.live_telemetry import CaseResult, LiveRunSummary

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LIVE_ENABLED_VALUES = frozenset(("1", "true", "yes", "on"))
_REQUIRED_LIVE_ENV = ("MC_EVAL_LIVE_BRIDGE_URL", "MINECRAFT_BRIDGE_TOKEN")


class LiveBridgeConfigError(ValueError):
    """Raised when the real live bridge mode is requested without configuration."""


class HttpBridgeClient:
    """Small HTTP command bridge for explicitly enabled live eval runs."""

    def __init__(self, url: str, token: str, *, timeout: float = 30.0) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout

    async def send_command(self, command_text: str) -> Mapping[str, Any]:
        return await asyncio.to_thread(self._post_command, command_text)

    def _post_command(self, command_text: str) -> Mapping[str, Any]:
        body = json.dumps({"command_text": command_text}).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OSError(f"live bridge request failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("live bridge response must be a JSON object")
        return payload


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    bridge: BridgeClient | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    load_env: bool = True,
) -> int:
    """Run the live command smoke CLI and return a process exit code."""

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
        selected_bridge, dry_run = (
            (bridge, False) if bridge is not None else _make_bridge_client(args, resolved_env)
        )
        summary = asyncio.run(
            run_live_command_smoke(
                args.command,
                args.cases,
                bridge=selected_bridge,
                verbose=args.verbose,
                profile=args.profile,
                seed=args.seed,
                env=resolved_env,
                project_root=PROJECT_ROOT,
                dry_run=dry_run,
            )
        )
        if args.report_dir:
            _write_report_artifacts(args.report_dir, summary)
        if args.output:
            _write_output(args.output, summary)
        _emit_summary(summary, json_mode=args.json, verbose=args.verbose, stdout=out)
    except (EvalProfileError, LiveBridgeConfigError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=err)
        return 1
    except Exception as exc:
        print(f"ERROR: Minecraft live eval failed: {exc}", file=err)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one Minecraft command family repeatedly with action telemetry",
    )
    parser.add_argument(
        "--command",
        required=True,
        help=(
            "Command family or command name. Supported: " + ", ".join(supported_command_inputs())
        ),
    )
    parser.add_argument("--cases", type=int, default=5, help="Number of cases to run")
    parser.add_argument("--verbose", action="store_true", help="Print per-action telemetry")
    parser.add_argument("--seed", type=int, default=0, help="Deterministic case seed")
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
    return parser


def _make_bridge_client(
    args: argparse.Namespace,
    env: Mapping[str, str],
) -> tuple[BridgeClient, bool]:
    if args.dry_run or not _live_enabled(env):
        return FakeBridgeClient(), True

    missing = [key for key in _REQUIRED_LIVE_ENV if not env.get(key)]
    if missing:
        required = ", ".join(_REQUIRED_LIVE_ENV)
        missing_text = ", ".join(missing)
        raise LiveBridgeConfigError(
            "live Minecraft eval is explicitly gated; "
            f"MC_EVAL_LIVE_ENABLED=1 requires {required}. "
            f"Missing: {missing_text}. Pass --dry-run for deterministic local smoke."
        )

    return HttpBridgeClient(env["MC_EVAL_LIVE_BRIDGE_URL"], env["MINECRAFT_BRIDGE_TOKEN"]), False


def _live_enabled(env: Mapping[str, str]) -> bool:
    return env.get("MC_EVAL_LIVE_ENABLED", "").strip().casefold() in _LIVE_ENABLED_VALUES


def _emit_summary(
    summary: LiveRunSummary,
    *,
    json_mode: bool,
    verbose: bool,
    stdout: TextIO,
) -> None:
    payload = summary.to_dict()
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True), file=stdout)
        return

    title = (
        "Minecraft dataset replay"
        if summary.command == "dataset-replay"
        else "Minecraft live command smoke"
    )
    print(title, file=stdout)
    print(f"command: {summary.command}", file=stdout)
    print(f"resolved_command: {summary.resolved_command}", file=stdout)
    print(f"profile: {summary.profile}", file=stdout)
    print(f"seed: {summary.seed}", file=stdout)
    print(f"dry_run: {str(summary.dry_run).lower()}", file=stdout)
    print(f"cases: {len(summary.case_results)}", file=stdout)
    print(f"passed: {summary.passed_count}/{len(summary.case_results)}", file=stdout)
    print(
        "outcomes: "
        + ", ".join(f"{outcome}={count}" for outcome, count in summary.outcome_counts.items()),
        file=stdout,
    )
    print(
        "categories: "
        + ", ".join(f"{category}={count}" for category, count in summary.category_counts.items()),
        file=stdout,
    )
    print(
        "pathfinding: "
        + ", ".join(f"{signal}={count}" for signal, count in summary.pathfinding_summary.items()),
        file=stdout,
    )
    print(
        "inventory: "
        + ", ".join(f"{signal}={count}" for signal, count in summary.inventory_summary.items()),
        file=stdout,
    )
    print(
        "block_mutation: "
        + ", ".join(
            f"{signal}={count}" for signal, count in summary.block_mutation_summary.items()
        ),
        file=stdout,
    )
    for result in summary.case_results:
        print(
            f"- {result.case_id}: {result.outcome_class} "
            f"category={result.eval_category} "
            f"latency_ms={result.latency_ms} command={result.command_text}",
            file=stdout,
        )
        if verbose:
            _emit_verbose_case(result, stdout)


def _emit_verbose_case(result: CaseResult, stdout: TextIO) -> None:
    print(f"  command_input {result.command_text}", file=stdout)
    for event in result.action_events:
        event_name = f"action_{event.kind}"
        payload = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
        print(
            f"  {event_name} action_id={event.action_id} ts_ms={event.ts_ms} payload={payload}",
            file=stdout,
        )
    print(f"  outcome {result.outcome_class}", file=stdout)
    final_state = json.dumps(result.final_state, sort_keys=True, separators=(",", ":"))
    print(f"  final_state {final_state}", file=stdout)
    print(f"  eval_category {result.eval_category}", file=stdout)
    if result.pathfinding:
        pathfinding = json.dumps(
            result.pathfinding.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        print(f"  pathfinding {pathfinding}", file=stdout)
    if result.inventory:
        inventory = json.dumps(
            result.inventory.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        print(f"  inventory {inventory}", file=stdout)
    if result.block_mutation:
        block_mutation = json.dumps(
            result.block_mutation.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        print(f"  block_mutation {block_mutation}", file=stdout)
    if result.error:
        print(f"  error {result.error}", file=stdout)


def _write_output(path_arg: str, summary: LiveRunSummary) -> None:
    path = _resolve_path(path_arg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_report_artifacts(path_arg: str, summary: LiveRunSummary) -> None:
    report_dir = _resolve_path(path_arg)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report_dir / "cases.ndjson").write_text(
        "".join(
            json.dumps(result.to_dict(), sort_keys=True) + "\n" for result in summary.case_results
        ),
        encoding="utf-8",
    )
    (report_dir / "report.md").write_text(_report_md(summary), encoding="utf-8")


def _report_md(summary: LiveRunSummary) -> str:
    title = (
        "Minecraft Dataset Replay"
        if summary.command == "dataset-replay"
        else "Minecraft Live Command Smoke"
    )
    lines = [
        f"# {title}",
        "",
        f"- command: `{summary.command}`",
        f"- resolved_command: `{summary.resolved_command}`",
        f"- profile: `{summary.profile}`",
        f"- seed: `{summary.seed}`",
        f"- dry_run: `{str(summary.dry_run).lower()}`",
        f"- cases: `{len(summary.case_results)}`",
        f"- passed: `{summary.passed_count}/{len(summary.case_results)}`",
        "",
    ]
    dataset_detail = summary.profile_detail.get("dataset_replay")
    if isinstance(dataset_detail, Mapping):
        lines.extend(_dataset_replay_report_lines(dataset_detail))
    lines.extend(("## Outcomes", ""))
    lines.extend(f"- {outcome}: {count}" for outcome, count in summary.outcome_counts.items())
    lines.extend(("", "## Categories", ""))
    lines.extend(f"- {category}: {count}" for category, count in summary.category_counts.items())
    lines.extend(("", "## Pathfinding", ""))
    pathfinding_lines = _pathfinding_report_lines(summary.case_results)
    lines.extend(pathfinding_lines if pathfinding_lines else ["None."])
    lines.extend(("", "## Inventory", ""))
    inventory_lines = _inventory_report_lines(summary.case_results)
    lines.extend(inventory_lines if inventory_lines else ["None."])
    lines.extend(("", "## Block Mutation", ""))
    block_mutation_lines = _block_mutation_report_lines(summary.case_results)
    lines.extend(block_mutation_lines if block_mutation_lines else ["None."])
    lines.extend(("", "## Cases", ""))
    for result in summary.case_results:
        lines.append(
            f"- `{result.case_id}` {result.outcome_class} "
            f"({result.eval_category}): `{result.command_text}`"
        )
    return "\n".join(lines) + "\n"


def _dataset_replay_report_lines(dataset_detail: Mapping[str, Any]) -> list[str]:
    lines = [
        "## Dataset Replay",
        "",
        f"- dataset: `{dataset_detail.get('dataset_path') or 'n/a'}`",
        f"- prompts_loaded: `{dataset_detail.get('total_prompts', 0)}`",
        f"- prompts_after_filter: `{dataset_detail.get('selected_prompts', 0)}`",
        "",
        "### Per-command Outcomes",
        "",
    ]
    per_command = dataset_detail.get("per_command_outcome_counts")
    if not isinstance(per_command, Mapping) or not per_command:
        lines.extend(("None.", ""))
        return lines

    for command, raw_counts in sorted(per_command.items()):
        if not isinstance(raw_counts, Mapping):
            continue
        counts = ", ".join(
            f"{outcome}={count}"
            for outcome, count in raw_counts.items()
            if isinstance(count, int) and count
        )
        lines.append(f"- `{command}`: {counts or 'none'}")
    lines.extend(("", "### Per-category Outcomes", ""))
    per_category = dataset_detail.get("per_category_outcome_counts")
    if isinstance(per_category, Mapping) and per_category:
        for category, raw_counts in sorted(per_category.items()):
            if not isinstance(raw_counts, Mapping):
                continue
            counts = ", ".join(
                f"{outcome}={count}"
                for outcome, count in raw_counts.items()
                if isinstance(count, int) and count
            )
            lines.append(f"- `{category}`: {counts or 'none'}")
    else:
        lines.append("None.")
    lines.append("")
    return lines


def _pathfinding_report_lines(results: Sequence[CaseResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        signals = result.pathfinding
        if signals is None:
            continue
        pose = (
            json.dumps(signals.final_pose, sort_keys=True, separators=(",", ":"))
            if signals.final_pose is not None
            else "n/a"
        )
        lines.append(
            f"- `{result.case_id}` {result.outcome_class}: "
            f"stuck={str(signals.stuck).lower()} "
            f"collision={str(signals.collision).lower()} "
            f"blocked_path={str(signals.blocked_path).lower()} "
            f"final_pose=`{pose}`"
        )
    return lines


def _inventory_report_lines(results: Sequence[CaseResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        inventory = result.inventory
        if inventory is None:
            continue
        net = json.dumps(inventory.net, sort_keys=True, separators=(",", ":"))
        final = json.dumps(inventory.final, sort_keys=True, separators=(",", ":"))
        missing = json.dumps(
            inventory.missing_expected,
            sort_keys=True,
            separators=(",", ":"),
        )
        unexpected = json.dumps(inventory.unexpected, sort_keys=True, separators=(",", ":"))
        lines.append(
            f"- `{result.case_id}` {result.outcome_class}: "
            f"matches_expected={_match_text(inventory.matches_expected)} "
            f"net=`{net}` final=`{final}` "
            f"missing_expected=`{missing}` unexpected=`{unexpected}`"
        )
    return lines


def _block_mutation_report_lines(results: Sequence[CaseResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        block_mutation = result.block_mutation
        if block_mutation is None:
            continue
        actual = json.dumps(
            [dict(block) for block in block_mutation.actual_placements],
            sort_keys=True,
            separators=(",", ":"),
        )
        final_blocks = json.dumps(
            [dict(block) for block in block_mutation.final_blocks],
            sort_keys=True,
            separators=(",", ":"),
        )
        missing = json.dumps(
            [dict(block) for block in block_mutation.missing_placements],
            sort_keys=True,
            separators=(",", ":"),
        )
        extra = json.dumps(
            [dict(block) for block in block_mutation.extra_placements],
            sort_keys=True,
            separators=(",", ":"),
        )
        lines.append(
            f"- `{result.case_id}` {result.outcome_class}: "
            f"matches_expected={_match_text(block_mutation.matches_expected)} "
            f"actual=`{actual}` final_blocks=`{final_blocks}` "
            f"missing=`{missing}` extra=`{extra}`"
        )
    return lines


def _match_text(value: bool | None) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def _resolve_path(path_arg: str) -> Path:
    path = Path(path_arg)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())

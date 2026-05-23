"""Artifact writers for focused Minecraft live eval runs."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.minecraft.eval.live_telemetry import (
    ActionEvent,
    CaseResult,
    LiveRunSummary,
    OutcomeClass,
    classify_timing_failure,
)

LIVE_GENERATIONS = "live-generations.ndjson"
LIVE_ACTIONS = "live-actions.ndjson"
LIVE_SCORES = "live-scores.json"
LIVE_REPORT = "live-report.md"
LIVE_TIMELINE = "timeline.ndjson"
TIMELINE_SOURCE = "live-eval"

_LIFECYCLE_EVENT_KINDS = frozenset(
    (
        "death",
        "died",
        "fatal",
        "killed",
        "recovery",
        "recovered",
        "respawn",
        "respawned",
        "safe_spawn",
        "stuck",
        "unsafe_spawn",
        "unstuck",
        "unstuck_attempt",
        "unstuck_failure",
        "unstuck_success",
    )
)
_ACTION_RESULT_KINDS = frozenset(
    (
        "dropped",
        "fanout",
        "interrupted",
        "preempted",
        "queued",
    )
)


def write_live_eval_artifacts(
    report_dir: str | Path,
    summary: LiveRunSummary,
    *,
    dataset_path: str | Path | None = None,
    traces: str | Path | None = None,
) -> dict[str, Path]:
    """Write live eval artifacts and return their paths by artifact name."""

    target_dir = Path(report_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    paths["summary"] = target_dir / "summary.json"
    paths["cases"] = target_dir / "cases.ndjson"
    paths["live_actions"] = target_dir / LIVE_ACTIONS
    paths["live_scores"] = target_dir / LIVE_SCORES
    paths["live_generations"] = target_dir / LIVE_GENERATIONS
    paths["timeline"] = target_dir / LIVE_TIMELINE
    paths["live_report"] = target_dir / LIVE_REPORT
    paths["report"] = target_dir / "report.md"

    _write_json(paths["summary"], summary.to_dict())
    _write_ndjson(paths["cases"], (result.to_dict() for result in summary.case_results))
    _write_ndjson(paths["live_actions"], live_action_records(summary))
    _write_json(paths["live_scores"], live_scores_dict(summary))
    _write_ndjson(
        paths["live_generations"],
        live_generation_records(summary, dataset_path=dataset_path),
    )
    _write_ndjson(paths["timeline"], live_timeline_records(summary))

    trace_links: list[dict[str, str]] = []
    if traces is not None:
        traces_dir = _resolve_traces_dir(target_dir, traces)
        trace_links = write_position_traces(traces_dir, summary, report_dir=target_dir)
        paths["traces"] = traces_dir

    report_text = live_report_md(summary, trace_links=trace_links)
    paths["live_report"].write_text(report_text, encoding="utf-8")
    paths["report"].write_text(report_text, encoding="utf-8")
    return paths


def live_action_records(summary: LiveRunSummary) -> list[dict[str, Any]]:
    """Return one flattened record per action event."""

    records: list[dict[str, Any]] = []
    for result in summary.case_results:
        for event in result.action_events:
            records.append(
                {
                    "case_id": result.case_id,
                    "agent_id": result.agent_id,
                    "action_id": event.action_id,
                    "kind": event.kind,
                    "ts_ms": event.ts_ms,
                    "payload": dict(event.payload),
                }
            )
    return records


def live_scores_dict(summary: LiveRunSummary) -> dict[str, Any]:
    """Return compact scoring data without full final-state payloads."""

    return {
        "command": summary.command,
        "resolved_command": summary.resolved_command,
        "profile": summary.profile,
        "seed": summary.seed,
        "dry_run": summary.dry_run,
        "cases": len(summary.case_results),
        "passed": summary.passed_count,
        "failed": summary.failed_count,
        "outcome_counts": summary.outcome_counts,
        "category_counts": summary.category_counts,
        "pathfinding_summary": summary.pathfinding_summary,
        "inventory_summary": summary.inventory_summary,
        "block_mutation_summary": summary.block_mutation_summary,
        "lifecycle_summary": summary.lifecycle_summary,
        "timing_summary": summary.timing_summary,
        "passed_cases": [result.case_id for result in summary.case_results if result.passed],
        "failed_cases": [result.case_id for result in summary.case_results if not result.passed],
        "case_results": [_case_score(result) for result in summary.case_results],
    }


def live_generation_records(
    summary: LiveRunSummary,
    *,
    dataset_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return generated command records or a replay dataset reference record."""

    if summary.command == "dataset-replay" or dataset_path is not None:
        dataset_detail = _dataset_replay_detail(summary)
        source_dataset = dataset_path or dataset_detail.get("dataset_path")
        selected_cases = [_dataset_case_reference(result) for result in summary.case_results]
        return [
            {
                "record_type": "dataset-reference",
                "dataset_path": str(source_dataset) if source_dataset else None,
                "filters": dict(dataset_detail.get("filters") or {}),
                "selected_count": len(summary.case_results),
                "total_prompts": dataset_detail.get("total_prompts"),
                "selected_scenario_ids": _unique_non_empty(
                    record.get("scenario_id") for record in selected_cases
                ),
                "selected_command_tokens": _unique_non_empty(
                    record.get("command_token") for record in selected_cases
                ),
                "selected_cases": selected_cases,
            }
        ]

    return [
        {
            "record_type": "generated-command",
            "case_id": result.case_id,
            "agent_id": result.agent_id,
            "command": summary.command,
            "resolved_command": summary.resolved_command,
            "command_text": result.command_text,
            "params": dict(result.params),
        }
        for result in summary.case_results
    ]


def live_timeline_records(summary: LiveRunSummary) -> list[dict[str, Any]]:
    """Return monitor-compatible timeline records for live eval action telemetry."""

    records: list[dict[str, Any]] = []
    for result in summary.case_results:
        for event in result.action_events:
            event_type = _timeline_event_type(result, event)
            records.append(_timeline_record(result, event, event_type))
        lifecycle_record = _lifecycle_timeline_record(result)
        if lifecycle_record is not None:
            records.append(lifecycle_record)

    for seq, record in enumerate(records, start=1):
        record["event_id"] = f"timeline-{seq:06d}"
        record["seq"] = seq
    return records


def write_position_traces(
    traces_dir: str | Path,
    summary: LiveRunSummary,
    *,
    report_dir: str | Path | None = None,
) -> list[dict[str, str]]:
    """Write cheap per-case position traces and return markdown link metadata."""

    target_dir = Path(traces_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    base_dir = Path(report_dir) if report_dir is not None else target_dir.parent
    links: list[dict[str, str]] = []
    for result in summary.case_results:
        trace = _case_position_trace(result)
        if trace is None:
            continue
        path = target_dir / f"{_safe_filename(result.case_id)}.json"
        _write_json(path, trace)
        links.append(
            {
                "case_id": result.case_id,
                "path": str(path),
                "href": _relative_link(path, base_dir),
            }
        )
    return links


def live_report_md(
    summary: LiveRunSummary,
    *,
    trace_links: Sequence[Mapping[str, str]] = (),
) -> str:
    """Return the human-readable live eval report markdown."""

    if summary.command == "dataset-replay":
        title = "Minecraft Dataset Replay"
    elif summary.command == "multi-agent-timing":
        title = "Minecraft Multi-agent Timing"
    else:
        title = "Minecraft Live Command Smoke"
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
        "## Artifacts",
        "",
        f"- [{LIVE_GENERATIONS}]({LIVE_GENERATIONS})",
        f"- [{LIVE_ACTIONS}]({LIVE_ACTIONS})",
        f"- [{LIVE_SCORES}]({LIVE_SCORES})",
        f"- [{LIVE_TIMELINE}]({LIVE_TIMELINE})",
        "",
    ]
    if trace_links:
        lines.extend(("### Position Traces", ""))
        for link in trace_links:
            case_id = link.get("case_id") or "case"
            href = link.get("href") or link.get("path") or ""
            lines.append(f"- `{case_id}`: [{href}]({href})")
        lines.append("")
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
    lines.extend(("", "## Lifecycle", ""))
    lifecycle_lines = _lifecycle_report_lines(summary.case_results)
    lines.extend(lifecycle_lines if lifecycle_lines else ["None."])
    lines.extend(("", "## Multi-agent timing", ""))
    timing_lines = _timing_report_lines(summary)
    lines.extend(timing_lines if timing_lines else ["None."])
    lines.extend(("", "## Cases", ""))
    for result in summary.case_results:
        agent_text = f" `{result.agent_id}`" if result.agent_id else ""
        lines.append(
            f"- `{result.case_id}`{agent_text} {result.outcome_class} "
            f"({result.eval_category}): `{result.command_text}`"
        )
    return "\n".join(lines) + "\n"


def _case_score(result: CaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "agent_id": result.agent_id,
        "command_text": result.command_text,
        "passed": result.passed,
        "outcome_class": result.outcome_class,
        "eval_category": result.eval_category,
        "latency_ms": result.latency_ms,
        "error": result.error,
        "pathfinding": result.pathfinding.to_dict() if result.pathfinding else None,
        "inventory": result.inventory.to_dict() if result.inventory else None,
        "block_mutation": result.block_mutation.to_dict() if result.block_mutation else None,
        "lifecycle": result.lifecycle.to_dict() if result.lifecycle else None,
        "timing": result.timing.to_dict() if result.timing else None,
    }


def _dataset_case_reference(result: CaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "scenario_id": result.params.get("scenario_id"),
        "command_token": result.params.get("command_token"),
        "command_text": result.command_text,
    }


def _timeline_record(
    result: CaseResult,
    event: ActionEvent,
    event_type: str,
) -> dict[str, Any]:
    payload = dict(event.payload)
    payload.update(
        {
            "action_event_kind": event.kind,
            "case_id": result.case_id,
            "command_text": result.command_text,
            "eval_category": result.eval_category,
            "outcome_class": result.outcome_class,
        }
    )
    if result.error and "error" not in payload:
        payload["error"] = result.error
    return {
        "ts": _isoformat_ms(event.ts_ms),
        "seq": 0,
        "event_type": event_type,
        "agent": _event_agent(result, event),
        "trace_id": event.action_id,
        "source": TIMELINE_SOURCE,
        "payload": payload,
    }


def _lifecycle_timeline_record(result: CaseResult) -> dict[str, Any] | None:
    lifecycle = result.lifecycle
    if lifecycle is None or not _has_lifecycle_signal(lifecycle.to_dict()):
        return None
    ts_ms = result.action_events[-1].ts_ms if result.action_events else 0
    trace_id = result.action_events[-1].action_id if result.action_events else result.case_id
    return {
        "ts": _isoformat_ms(ts_ms),
        "seq": 0,
        "event_type": "lifecycle",
        "agent": result.agent_id,
        "trace_id": trace_id,
        "source": TIMELINE_SOURCE,
        "payload": {
            "case_id": result.case_id,
            "command_text": result.command_text,
            "eval_category": result.eval_category,
            "outcome_class": result.outcome_class,
            "lifecycle": lifecycle.to_dict(),
            "text": _lifecycle_summary_text(result),
        },
    }


def _timeline_event_type(result: CaseResult, event: ActionEvent) -> str:
    if event.kind == "start":
        return "action.start"
    if event.kind == "end":
        if result.outcome_class == OutcomeClass.SUCCESS:
            return "action.completed"
        if result.outcome_class in (
            OutcomeClass.ERROR,
            OutcomeClass.MALFORMED,
            OutcomeClass.TIMEOUT,
        ):
            return "error"
        return "action.result"
    if event.kind in _LIFECYCLE_EVENT_KINDS:
        return "lifecycle"
    if event.kind in _ACTION_RESULT_KINDS:
        return "action.result"
    return "action.result"


def _event_agent(result: CaseResult, event: ActionEvent) -> str | None:
    agent_id = result.agent_id or event.payload.get("agent_id")
    if agent_id is None:
        return None
    agent_text = str(agent_id).strip()
    return agent_text or None


def _case_position_trace(result: CaseResult) -> dict[str, Any] | None:
    positions = []
    for event in result.action_events:
        pose = _extract_pose(event.payload)
        if pose is not None:
            positions.append({"ts_ms": event.ts_ms, "pose": pose})

    final_pose = _final_pose(result)
    if final_pose is None and not positions:
        return None
    if final_pose is not None and not positions:
        ts_ms = result.action_events[-1].ts_ms if result.action_events else 0
        positions.append({"ts_ms": ts_ms, "pose": final_pose})

    return {
        "case_id": result.case_id,
        "agent_id": result.agent_id,
        "command_text": result.command_text,
        "outcome_class": result.outcome_class,
        "eval_category": result.eval_category,
        "final_pose": final_pose,
        "positions": positions,
    }


def _final_pose(result: CaseResult) -> dict[str, Any] | None:
    if result.pathfinding is not None and result.pathfinding.final_pose is not None:
        return dict(result.pathfinding.final_pose)
    if result.lifecycle is not None and result.lifecycle.last_pose is not None:
        return dict(result.lifecycle.last_pose)
    return _extract_pose(result.final_state)


def _extract_pose(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    for key in ("final_pose", "pose", "position"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return None


def _resolve_traces_dir(report_dir: Path, traces: str | Path) -> Path:
    path = Path(traces)
    if path.is_absolute():
        return path
    return report_dir / path


def _relative_link(path: Path, base_dir: Path) -> str:
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return str(path)


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
    return safe or "case"


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_ndjson(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(dict(record), sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _isoformat_ms(ts_ms: int) -> str:
    return (
        datetime.fromtimestamp(max(0, int(ts_ms)) / 1000, tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _has_lifecycle_signal(lifecycle: Mapping[str, Any]) -> bool:
    return any(
        (
            bool(lifecycle.get("death_count")),
            bool(lifecycle.get("death_loop")),
            bool(lifecycle.get("respawns")),
            lifecycle.get("safe_spawn") is not None,
            bool(lifecycle.get("unsafe_spawn_count")),
            bool(lifecycle.get("stuck")),
            bool(lifecycle.get("stuck_events")),
            bool(lifecycle.get("unstuck_attempts")),
            lifecycle.get("unstuck_succeeded") is not None,
            bool(lifecycle.get("unstuck_failed")),
        )
    )


def _lifecycle_summary_text(result: CaseResult) -> str:
    lifecycle = result.lifecycle
    if lifecycle is None:
        return "lifecycle"
    parts: list[str] = []
    if lifecycle.death_count:
        parts.append(f"deaths={lifecycle.death_count}")
    if lifecycle.death_loop:
        parts.append("death_loop=true")
    if lifecycle.respawns:
        parts.append(f"respawns={lifecycle.respawns}")
    if lifecycle.safe_spawn is not None:
        parts.append(f"safe_spawn={str(lifecycle.safe_spawn).lower()}")
    if lifecycle.stuck or lifecycle.stuck_events:
        parts.append(f"stuck_events={lifecycle.stuck_events}")
    if lifecycle.unstuck_attempts:
        parts.append(f"unstuck_attempts={lifecycle.unstuck_attempts}")
    return ", ".join(parts) or "lifecycle"


def _dataset_replay_detail(summary: LiveRunSummary) -> Mapping[str, Any]:
    detail = summary.profile_detail.get("dataset_replay")
    return detail if isinstance(detail, Mapping) else {}


def _unique_non_empty(values: Any) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            seen.setdefault(text, None)
    return list(seen)


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


def _lifecycle_report_lines(results: Sequence[CaseResult]) -> list[str]:
    lines: list[str] = []
    for result in results:
        lifecycle = result.lifecycle
        if lifecycle is None:
            continue
        lines.append(
            f"- `{result.case_id}` {result.outcome_class}: "
            f"death_count={lifecycle.death_count} "
            f"death_loop={str(lifecycle.death_loop).lower()} "
            f"safe_spawn={_match_text(lifecycle.safe_spawn)} "
            f"stuck={str(lifecycle.stuck).lower()} "
            f"unstuck_attempts={lifecycle.unstuck_attempts} "
            f"unstuck_succeeded={_match_text(lifecycle.unstuck_succeeded)}"
        )
    return lines


def _timing_report_lines(summary: LiveRunSummary) -> list[str]:
    timing_summary = summary.timing_summary
    if timing_summary["cases"] == 0:
        return []
    lines = [
        "- aggregate: "
        + ", ".join(
            f"{signal}={_summary_value_text(count)}"
            for signal, count in timing_summary.items()
            if signal != "per_agent"
        )
    ]
    lines.append("")
    lines.append("### Per-agent")
    lines.append("")
    for agent_id, metrics in timing_summary["per_agent"].items():
        failure_classes = _summary_value_text(metrics.get("failure_classes", {}))
        lines.append(
            f"- `{agent_id}`: cases={metrics.get('cases', 0)} "
            f"contention={metrics.get('contention', 0)} "
            f"interruptions={metrics.get('interruptions', 0)} "
            f"fanouts={metrics.get('fanouts', 0)} "
            f"dropped={metrics.get('dropped', 0)} "
            f"command_loss={metrics.get('command_loss', 0)} "
            f"max_queue_depth={metrics.get('max_queue_depth', 0)} "
            f"failure_classes=`{failure_classes}`"
        )
    lines.append("")
    lines.append("### Cases")
    lines.append("")
    for result in summary.case_results:
        timing = result.timing
        if timing is None:
            continue
        failure_class = classify_timing_failure(timing, params=result.params)
        lines.append(
            f"- `{result.case_id}` `{timing.agent_id}`: "
            f"failure_class={failure_class} "
            f"queue_depth={timing.queue_depth} "
            f"contention={str(timing.queue_contention).lower()} "
            f"interruptions={timing.self_interruption_count} "
            f"fanouts={timing.director_fanout_count} "
            f"dropped={timing.dropped_commands} "
            f"command_loss={timing.command_loss_count} "
            f"conflicts={list(timing.conflicting_action_ids)}"
        )
    return lines


def _summary_value_text(value: object) -> str:
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _match_text(value: bool | None) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"

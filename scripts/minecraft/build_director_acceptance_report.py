#!/usr/bin/env python3
"""Build Director V2 acceptance-soak evidence and pass/fail report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_QUEUE_DEPTH_THRESHOLD = 16
DEFAULT_WARMUP_SECONDS = 300
DEFAULT_MAX_SELECTED_AGENT_RATIO = 0.5
DEFAULT_AGENTS = "alpha vera rex aurora pixel fork sentinel grok"

DIRECTOR_DECISION_EVENTS = {
    "director.gate.decision",
    "director.scene.opened",
    "director.scene.closed",
}
MEMORY_EVENTS = {"director.scene.digest", "director.memory.compaction"}
MACRO_EVENT_PREFIXES = ("build_plan.",)
MACRO_ACTION_HINTS = (
    "build",
    "buildfromplan",
    "planandbuild",
    "place",
    "placehere",
    "placeblock",
    "collectblocks",
    "collectallblocks",
    "consume",
    "equip",
    "smeltitem",
    "support",
    "clear",
    "guard",
)


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    status: str
    summary: str
    evidence: list[str]
    residual_gap: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.criterion_id,
            "status": self.status,
            "summary": self.summary,
            "evidence": self.evidence,
            "residual_gap": self.residual_gap,
        }


def parse_iso_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_no, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            data = json.loads(raw_line)
        except json.JSONDecodeError:
            rows.append(
                {
                    "event_type": "error",
                    "payload": {
                        "class": "malformed_acceptance_input",
                        "line": line_no,
                        "text": raw_line[:180],
                    },
                }
            )
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def event_agent(event: dict[str, Any]) -> str | None:
    raw = event.get("agent") or event.get("agent_id") or payload(event).get("agent_id")
    if raw is None:
        return None
    text = str(raw).strip().lower()
    return text or None


def event_scene_id(event: dict[str, Any]) -> str | None:
    raw = payload(event).get("scene_id") or event.get("scene_id") or event.get("trace_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def coerce_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "selected"}
    return bool(value)


def write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def total_agents(metadata: dict[str, str], events: list[dict[str, Any]]) -> int:
    configured = metadata.get("cost_agents") or os.environ.get("SOAK_COST_AGENTS") or DEFAULT_AGENTS
    agents = [item for item in configured.split() if item]
    if agents:
        return len(set(agents))
    observed = {agent for event in events if (agent := event_agent(event))}
    return max(1, len(observed))


def run_start(metadata: dict[str, str], events: list[dict[str, Any]]) -> datetime:
    parsed = parse_iso_ts(metadata.get("start_utc"))
    if parsed is not None:
        return parsed
    event_times = [ts for event in events if (ts := parse_iso_ts(event.get("ts")))]
    return min(event_times) if event_times else datetime.now(UTC).replace(microsecond=0)


def normalize_director_decision(event: dict[str, Any]) -> dict[str, Any]:
    data = payload(event)
    return {
        "ts": event.get("ts"),
        "event_type": event.get("event_type"),
        "scene_id": event_scene_id(event),
        "agent": event_agent(event),
        "selected": boolish(data.get("selected")),
        "turn_kind": data.get("turn_kind"),
        "reason_code": data.get("reason_code") or data.get("reason"),
        "suppression_reason": data.get("suppression_reason"),
        "queue_depth": coerce_int(data.get("queue_depth")),
        "selected_speaker": data.get("selected_speaker"),
        "selected_action_owner": data.get("selected_action_owner"),
        "build_plan_id": data.get("build_plan_id"),
        "build_role": data.get("build_role"),
        "llm_prompt_count": coerce_int(data.get("llm_prompt_count")),
        "avoided_prompt_count": coerce_int(data.get("avoided_prompt_count")),
    }


def normalize_tool_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_call_keys = {
        (event_scene_id(event), event_agent(event))
        for event in events
        if event.get("event_type") == "director.tool.call"
    }
    rows: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        data = payload(event)
        if event_type == "director.tool.call":
            rows.append(
                {
                    "ts": event.get("ts"),
                    "kind": "tool_call",
                    "scene_id": event_scene_id(event),
                    "agent": event_agent(event),
                    "tool_name": data.get("tool_name") or "unknown",
                    "classification": data.get("classification"),
                    "status": data.get("status")
                    or ("ok" if data.get("ok") is not False else "error"),
                    "ok": data.get("ok", True),
                    "latency_ms": coerce_int(data.get("latency_ms")),
                    "error_class": data.get("error_class"),
                }
            )
            continue

        if event_type != "director.gate.decision" or not boolish(data.get("selected")):
            continue
        key = (event_scene_id(event), event_agent(event))
        if key in tool_call_keys:
            continue
        available_tools = data.get("available_tools")
        rows.append(
            {
                "ts": event.get("ts"),
                "kind": "no_tool_decision",
                "scene_id": key[0],
                "agent": key[1],
                "tool_name": None,
                "classification": "documented_no_tool",
                "status": "documented",
                "ok": True,
                "available_tools": available_tools if isinstance(available_tools, list) else [],
                "reason_code": data.get("reason_code") or data.get("reason") or "speaker_turn",
                "no_tool_reason": data.get("no_tool_reason")
                or data.get("tool_decision")
                or "selected turn did not require a callable Director tool",
            }
        )
    return rows


def command_names_from_event(event: dict[str, Any]) -> list[str]:
    commands = payload(event).get("commands")
    names: list[str] = []
    if isinstance(commands, list):
        for item in commands:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("command") or item.get("text") or "")
            else:
                name = str(item)
            if name:
                names.append(name.strip().lstrip("!").split("(", 1)[0].lower())
    action = payload(event).get("action")
    if action:
        names.append(str(action).strip().lstrip("!").split(":", 1)[-1].lower())
    return names


def is_macro_action(event: dict[str, Any]) -> bool:
    names = command_names_from_event(event)
    return any(any(hint in name for hint in MACRO_ACTION_HINTS) for name in names)


def normalize_macro_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "")
        data = payload(event)
        if event_type.startswith(MACRO_EVENT_PREFIXES):
            rows.append(
                {
                    "ts": event.get("ts"),
                    "kind": event_type,
                    "scene_id": event_scene_id(event),
                    "agent": event_agent(event),
                    "owner": data.get("owner")
                    or data.get("build_plan_owner")
                    or data.get("active_build_owner")
                    or event_agent(event),
                    "plan_id": data.get("plan_id") or data.get("action_id"),
                    "provider": data.get("builder_provider") or data.get("provider"),
                    "model": data.get("builder_model") or data.get("model"),
                    "status": data.get("status") or data.get("reason") or data.get("outcome"),
                    "result": data.get("result"),
                    "structured_result": event_type.endswith(".completed")
                    or event_type.endswith(".skipped")
                    or event_type.endswith(".provider_failed")
                    or event_type.endswith(".budget_capped"),
                    "estimated_usd": coerce_float(data.get("estimated_usd")),
                }
            )
            continue
        if event_type == "director.gate.decision" and data.get("build_role"):
            rows.append(
                {
                    "ts": event.get("ts"),
                    "kind": "director_macro_assignment",
                    "scene_id": event_scene_id(event),
                    "agent": event_agent(event),
                    "owner": data.get("build_owner"),
                    "plan_id": data.get("build_plan_id"),
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "status": data.get("build_role"),
                    "result": data.get("build_role"),
                    "structured_result": bool(data.get("build_plan_id") and data.get("build_role")),
                    "estimated_usd": coerce_float(data.get("estimated_usd")),
                }
            )
            continue
        if event_type in {"action.intent", "action.result"} and is_macro_action(event):
            rows.append(
                {
                    "ts": event.get("ts"),
                    "kind": event_type,
                    "scene_id": event_scene_id(event),
                    "agent": event_agent(event),
                    "owner": event_agent(event),
                    "plan_id": data.get("plan_id") or data.get("action_id"),
                    "provider": None,
                    "model": None,
                    "status": data.get("outcome") or data.get("status") or "intended",
                    "result": data.get("detail") or data.get("result") or data.get("text"),
                    "structured_result": event_type == "action.result",
                    "commands": command_names_from_event(event),
                    "estimated_usd": 0.0,
                }
            )
    return rows


def useful_memory_digest(row: dict[str, Any]) -> bool:
    event_type = str(row.get("event_type") or "")
    entries = coerce_int(row.get("entries_count"))
    distributed = row.get("distributed_to")
    summary = str(row.get("summary") or "")
    if event_type == "director.scene.digest":
        return (
            entries > 0
            and bool(summary.strip())
            and isinstance(distributed, list)
            and bool(distributed)
        )
    return entries > 0 and row.get("ok") is not False


def normalize_memory_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") not in MEMORY_EVENTS:
            continue
        data = payload(event)
        row = {
            "ts": event.get("ts"),
            "event_type": event.get("event_type"),
            "scene_id": event_scene_id(event),
            "agent": event_agent(event),
            "participants": data.get("participants")
            if isinstance(data.get("participants"), list)
            else [],
            "distributed_to": data.get("distributed_to")
            if isinstance(data.get("distributed_to"), list)
            else [],
            "entries_count": coerce_int(data.get("entries_count")),
            "tokens": coerce_int(data.get("tokens")),
            "latency_ms": coerce_int(data.get("latency_ms")),
            "transcript_id": data.get("transcript_id"),
            "close_reason": data.get("close_reason"),
            "ok": data.get("ok", True),
            "summary": data.get("summary"),
        }
        row["useful"] = useful_memory_digest(row)
        rows.append(row)
    return rows


def queue_depth_after_warmup(
    events: list[dict[str, Any]], start: datetime, warmup_seconds: int
) -> tuple[int | None, int, int]:
    cutoff = start + timedelta(seconds=warmup_seconds)
    max_depth: int | None = None
    count = 0
    total_queue_events = 0
    for event in events:
        if not str(event.get("event_type") or "").startswith("llm.queue."):
            continue
        total_queue_events += 1
        ts = parse_iso_ts(event.get("ts"))
        if ts is None or ts < cutoff:
            continue
        data = payload(event)
        depth = max(
            coerce_int(data.get("queue_depth")),
            coerce_int(data.get("queued")),
            coerce_int(data.get("remaining_depth")),
        )
        max_depth = depth if max_depth is None else max(max_depth, depth)
        count += 1
    if max_depth is None and total_queue_events > 0:
        max_depth = 0
    return max_depth, count, total_queue_events


def selected_scene_metrics(
    events: list[dict[str, Any]], agent_count: int
) -> tuple[Counter[str], Counter[str], float, list[str]]:
    selected_by_scene: Counter[str] = Counter()
    selected_by_agent: Counter[str] = Counter()
    selected_agents_by_scene: dict[str, set[str]] = {}
    for event in events:
        if event.get("event_type") != "director.gate.decision":
            continue
        data = payload(event)
        if not boolish(data.get("selected")):
            continue
        scene_id = event_scene_id(event) or "unknown"
        agent_id = event_agent(event) or "unknown"
        selected_by_scene[scene_id] += 1
        selected_by_agent[agent_id] += 1
        selected_agents_by_scene.setdefault(scene_id, set()).add(agent_id)
    max_selected_in_scene = max(
        (len(agents) for agents in selected_agents_by_scene.values()), default=0
    )
    selected_agent_ratio = max_selected_in_scene / max(1, agent_count)
    multi_turn_scene_ids = [
        scene_id
        for scene_id, selected_count in sorted(selected_by_scene.items())
        if selected_count >= 2
    ]
    return selected_by_scene, selected_by_agent, selected_agent_ratio, multi_turn_scene_ids


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line
    )


def report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Director V2 Acceptance Report",
        "",
        f"Generated: {report['generated_at_utc']}",
        f"Run directory: `{report['run_dir']}`",
        f"Overall status: **{report['overall_status'].upper()}**",
        "",
        "## Criteria",
        "",
        "| Criterion | Status | Evidence | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for criterion in report["criteria"]:
        evidence = ", ".join(f"`{item}`" for item in criterion["evidence"])
        lines.append(
            f"| `{criterion['id']}` | {criterion['status']} | {evidence} | {criterion['summary']} |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            f"- Queue depth after warm-up max: `{report['metrics']['queue_depth_after_warmup_max']}`",
            f"- Queue events after warm-up: `{report['metrics']['queue_events_after_warmup']}`",
            f"- Queue events total: `{report['metrics']['queue_events_total']}`",
            f"- Max selected-agent scene ratio: `{report['metrics']['max_selected_agent_scene_ratio']}`",
            f"- Multi-turn collaboration scenes: `{', '.join(report['metrics']['multi_turn_collaboration_scene_ids']) or 'none'}`",
            f"- Useful memory digests: `{report['metrics']['useful_memory_digest_count']}`",
            f"- Tool calls: `{report['metrics']['tool_call_count']}`",
            f"- Documented no-tool decisions: `{report['metrics']['no_tool_decision_count']}`",
            f"- Macro attempts: `{report['metrics']['macro_attempt_count']}`",
            f"- Structured macro results: `{report['metrics']['structured_macro_result_count']}`",
            f"- Early bot exits: `{report['metrics']['early_bot_exits']}`",
            f"- Heartbeat halts: `{report['metrics']['heartbeat_halts']}`",
            f"- Restart recurrences: `{report['metrics']['restart_recurrences']}`",
            "",
            "## Evidence Files",
            "",
        ]
    )
    for name, path in report["evidence_files"].items():
        lines.append(f"- `{name}`: `{path}`")
    lines.extend(["", "## Residual Gaps", ""])
    if report["residual_gaps"]:
        for gap in report["residual_gaps"]:
            lines.append(f"- {gap}")
    else:
        lines.append("- None. Evidence is sufficient to unblock #511, #512, and #514.")
    lines.append("")
    return "\n".join(lines)


def build_report(
    run_dir: Path,
    *,
    queue_threshold: int,
    warmup_seconds: int,
    max_selected_agent_ratio: float,
) -> dict[str, Any]:
    timeline_path = run_dir / "timeline.ndjson"
    timeline = read_ndjson(timeline_path)
    metadata = read_env_file(run_dir / "metadata.env")
    behavior_totals = read_env_file(run_dir / "behavior-totals.env")
    start = run_start(metadata, timeline)
    agent_count = total_agents(metadata, timeline)

    director_rows = [
        normalize_director_decision(event)
        for event in timeline
        if event.get("event_type") in DIRECTOR_DECISION_EVENTS
    ]
    tool_rows = normalize_tool_rows(timeline)
    macro_rows = normalize_macro_rows(timeline)
    memory_rows = normalize_memory_rows(timeline)

    evidence_paths = {
        "director_decisions": run_dir / "director-decisions.ndjson",
        "tool_parity": run_dir / "tool-parity.ndjson",
        "macro_evidence": run_dir / "macro-evidence.ndjson",
        "memory_digest": run_dir / "memory-digest.ndjson",
    }
    write_ndjson(evidence_paths["director_decisions"], director_rows)
    write_ndjson(evidence_paths["tool_parity"], tool_rows)
    write_ndjson(evidence_paths["macro_evidence"], macro_rows)
    write_ndjson(evidence_paths["memory_digest"], memory_rows)

    queue_max, queue_events_after_warmup, queue_events_total = queue_depth_after_warmup(
        timeline, start, warmup_seconds
    )
    selected_by_scene, selected_by_agent, selected_agent_ratio, multi_turn_scene_ids = (
        selected_scene_metrics(timeline, agent_count)
    )

    useful_memory_count = sum(1 for row in memory_rows if row.get("useful"))
    tool_call_count = sum(1 for row in tool_rows if row.get("kind") == "tool_call")
    no_tool_decision_count = sum(1 for row in tool_rows if row.get("kind") == "no_tool_decision")
    structured_macro_result_count = sum(1 for row in macro_rows if row.get("structured_result"))
    restart_recurrences = coerce_int(behavior_totals.get("total_restart_recurrences"))
    early_exits = line_count(run_dir / "early-exits.tsv")
    heartbeat_halts = line_count(run_dir / "heartbeat-halts.tsv")

    criteria: list[Criterion] = []
    queue_pass = queue_events_total > 0 and queue_max is not None and queue_max < queue_threshold
    storm_pass = bool(director_rows) and selected_agent_ratio <= max_selected_agent_ratio
    criteria.append(
        Criterion(
            "bounded_queue_and_no_response_storm",
            "pass" if queue_pass and storm_pass else "fail",
            (
                f"queue_after_warmup_max={queue_max}; threshold<{queue_threshold}; "
                f"max_selected_scene_ratio={selected_agent_ratio:.4f}; "
                f"threshold<={max_selected_agent_ratio:.4f}"
            ),
            ["timeline.ndjson", "timeline-totals.json", "director-decisions.ndjson"],
            None
            if queue_pass and storm_pass
            else "Director V2 smoke still needs bounded LM queue telemetry and selected-turn fanout below the configured ratio.",
        )
    )
    criteria.append(
        Criterion(
            "multi_turn_collaboration_scene",
            "pass" if multi_turn_scene_ids else "fail",
            f"scenes_with_at_least_two_selected_turns={len(multi_turn_scene_ids)}",
            ["director-decisions.ndjson", "timeline.ndjson"],
            None
            if multi_turn_scene_ids
            else "No scene proved multi-turn collaboration; #511 dreams/journals should wait for richer scene continuity.",
        )
    )
    criteria.append(
        Criterion(
            "useful_memory_digest",
            "pass" if useful_memory_count >= 1 else "fail",
            f"useful_memory_digest_count={useful_memory_count}",
            ["memory-digest.ndjson", "timeline.ndjson"],
            None
            if useful_memory_count >= 1
            else "No useful scene digest was captured; #511 and #512 still need a memory-digest blocker documented.",
        )
    )
    criteria.append(
        Criterion(
            "tool_or_documented_no_tool_decision",
            "pass" if tool_call_count + no_tool_decision_count >= 1 else "fail",
            f"tool_calls={tool_call_count}; documented_no_tool_decisions={no_tool_decision_count}",
            ["tool-parity.ndjson", "timeline.ndjson"],
            None
            if tool_call_count + no_tool_decision_count >= 1
            else "No callable tool or documented no-tool Director decision appeared; #512 cannot score tool parity from this run.",
        )
    )
    criteria.append(
        Criterion(
            "macro_attempt_with_structured_result",
            "pass" if macro_rows and structured_macro_result_count >= 1 else "fail",
            f"macro_attempts={len(macro_rows)}; structured_results={structured_macro_result_count}",
            ["macro-evidence.ndjson", "timeline.ndjson"],
            None
            if macro_rows and structured_macro_result_count >= 1
            else "No build/gather/support macro reached a structured result; #514 should keep run-mode blockers explicit.",
        )
    )
    criteria.append(
        Criterion(
            "llm_queue_depth_after_warmup",
            "pass" if queue_pass else "fail",
            f"queue_events_after_warmup={queue_events_after_warmup}; max_depth={queue_max}",
            ["timeline-raw/llm-queue.ndjson", "timeline.ndjson"],
            None
            if queue_pass
            else "LM Studio queue telemetry is missing after warm-up or exceeded the configured threshold.",
        )
    )
    criteria.append(
        Criterion(
            "no_unrecovered_bot_restart_loop",
            "pass"
            if early_exits == 0 and heartbeat_halts == 0 and restart_recurrences == 0
            else "fail",
            (
                f"early_exits={early_exits}; heartbeat_halts={heartbeat_halts}; "
                f"restart_recurrences={restart_recurrences}"
            ),
            ["early-exits.tsv", "heartbeat-halts.tsv", "behavior-totals.env"],
            None
            if early_exits == 0 and heartbeat_halts == 0 and restart_recurrences == 0
            else "One or more restart-loop indicators remain; downstream epics stay blocked until the run recovers cleanly.",
        )
    )

    residual_gaps = [criterion.residual_gap for criterion in criteria if criterion.residual_gap]
    if not residual_gaps:
        residual_gaps = []
    overall_status = "pass" if all(criterion.status == "pass" for criterion in criteria) else "fail"

    report = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "generated_at_utc": isoformat_z(datetime.now(UTC)),
        "profile": "director_v2",
        "overall_status": overall_status,
        "thresholds": {
            "queue_depth_after_warmup": queue_threshold,
            "warmup_seconds": warmup_seconds,
            "max_selected_agent_ratio": max_selected_agent_ratio,
            "total_agents": agent_count,
        },
        "evidence_files": {key: str(path) for key, path in evidence_paths.items()},
        "metrics": {
            "timeline_event_count": len(timeline),
            "director_decision_count": len(director_rows),
            "queue_depth_after_warmup_max": queue_max,
            "queue_events_after_warmup": queue_events_after_warmup,
            "queue_events_total": queue_events_total,
            "selected_by_scene": dict(sorted(selected_by_scene.items())),
            "selected_by_agent": dict(sorted(selected_by_agent.items())),
            "max_selected_agent_scene_ratio": round(selected_agent_ratio, 6),
            "multi_turn_collaboration_scene_ids": multi_turn_scene_ids,
            "useful_memory_digest_count": useful_memory_count,
            "tool_call_count": tool_call_count,
            "no_tool_decision_count": no_tool_decision_count,
            "macro_attempt_count": len(macro_rows),
            "structured_macro_result_count": structured_macro_result_count,
            "early_bot_exits": early_exits,
            "heartbeat_halts": heartbeat_halts,
            "restart_recurrences": restart_recurrences,
            "behavior_gate_status": behavior_totals.get("behavior_gate_status"),
        },
        "criteria": [criterion.to_json() for criterion in criteria],
        "residual_gaps": residual_gaps
        or ["None. Evidence is sufficient to unblock #511, #512, and #514."],
        "downstream_epics": {
            "#511": "Dreams/journals can consume useful scene digests when the memory criterion passes.",
            "#512": "Evals/reporting can score Director monitor, timeline, tool, macro, and queue evidence when evidence criteria pass.",
            "#514": "Run-mode/start-condition work can use this profile and residual-gap report as acceptance input.",
        },
    }
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Director V2 acceptance-soak evidence files plus "
            "acceptance-report.json and acceptance-report.md."
        )
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Soak evidence directory")
    parser.add_argument(
        "--queue-threshold",
        type=int,
        default=int(
            os.environ.get("SOAK_ACCEPTANCE_QUEUE_DEPTH_THRESHOLD", DEFAULT_QUEUE_DEPTH_THRESHOLD)
        ),
        help=f"Maximum allowed LM queue depth after warm-up, exclusive. Default: {DEFAULT_QUEUE_DEPTH_THRESHOLD}",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=int,
        default=int(os.environ.get("SOAK_ACCEPTANCE_WARMUP_SECONDS", DEFAULT_WARMUP_SECONDS)),
        help=f"Seconds ignored before queue-depth assertion. Default: {DEFAULT_WARMUP_SECONDS}",
    )
    parser.add_argument(
        "--max-selected-agent-ratio",
        type=float,
        default=float(
            os.environ.get(
                "SOAK_ACCEPTANCE_MAX_SELECTED_AGENT_RATIO",
                DEFAULT_MAX_SELECTED_AGENT_RATIO,
            )
        ),
        help=(
            "Maximum selected agents per scene divided by tracked agents. "
            f"Default: {DEFAULT_MAX_SELECTED_AGENT_RATIO}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = build_report(
            args.run_dir,
            queue_threshold=max(1, args.queue_threshold),
            warmup_seconds=max(0, args.warmup_seconds),
            max_selected_agent_ratio=max(0.01, args.max_selected_agent_ratio),
        )
    except Exception as exc:  # noqa: BLE001 - report generation should fail closed
        print(f"director acceptance report failed: {exc}", file=sys.stderr)
        return 2

    json_path = args.run_dir / "acceptance-report.json"
    md_path = args.run_dir / "acceptance-report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(report_markdown(report), encoding="utf-8")
    print(f"ok director acceptance report {report['overall_status']}; see {json_path}")
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

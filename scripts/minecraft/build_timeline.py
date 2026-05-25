#!/usr/bin/env python3
"""Build a structured timeline for embodied Minecraft soak evidence.

The exporter is intentionally tolerant: it normalizes the best available
signals from Mindcraft bot stdout/stderr, bridge traces, Paper logs, and raw
timeline NDJSON into one canonical `timeline.ndjson` without treating malformed
lines as fatal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minecraft_log_patterns import (
    ACTION_CONTEXT_RE,
    ACTION_TRACE_RE,
    CHAT_RE,
    COMMAND_CALL_RE,
    COMMAND_RE,
    CRASH_ERROR_RE,
    EXECUTION_FAILURE_RE,
    EXECUTION_SUCCESS_RE,
    LIFECYCLE_RE,
    POSITION_RE,
    TRACE_RE,
    XYZ_RE,
)
from analyze_action_reliability import (
    classify_execution,
    classify_parser_failure,
    excerpt,
    should_count_parser_failure,
)
from bot_log_parser import ParsedCommand, parse_bot_log_lines

EVENT_TYPES = frozenset(
    {
        "behavior.event",
        "bridge.action.start",
        "bridge.action.result",
        "chat.public",
        "llm.request",
        "llm.response",
        "llm.queue.enqueued",
        "llm.queue.started",
        "llm.queue.completed",
        "llm.queue.failed",
        "action.intent",
        "action.start",
        "action.queued",
        "action.started",
        "action.completed",
        "action.rejected_busy",
        "action.result",
        "inbox.queued",
        "inbox.turn_started",
        "inbox.turn_completed",
        "inbox.telemetry_ignored",
        "inbox.immediate_command",
        "build_plan.generation.started",
        "build_plan.generation.completed",
        "build_plan.generation.rejected",
        "build_plan.generation.provider_failed",
        "build_plan.generation.budget_capped",
        "build_plan.generation.skipped",
        "build_plan.execution.started",
        "build_plan.execution.completed",
        "director.gate.decision",
        "director.scene.opened",
        "director.scene.closed",
        "director.scene.digest",
        "director.memory.compaction",
        "director.tool.call",
        "memory_context.startup",
        "memory_context.fetched",
        "memory_context.skipped",
        "memory_context.error",
        "heartbeat.fired",
        "heartbeat.skipped",
        "heartbeat.outcome",
        "heartbeat.halted",
        "state.sample",
        "error",
        "lifecycle",
    }
)
BEHAVIOR_STATUS_RE = re.compile(r"\[(?P<kind>behavior-status|mode-status)\]\s*(?P<message>.*)")
SETUP_NOISE_RE = re.compile(
    r"Skipping this -> .*kicked with 'not whitelisted'"
    r"|^Error getting server: TypeError: Cannot read properties of null \(reading 'version'\)"
    r"|^Attempting to connect anyway"
    r"|^Timeout pinging server\b"
)

DEFAULT_STATE_SAMPLE_INTERVAL_SECONDS = 30
DEFAULT_BASE_TS = datetime(1970, 1, 1, tzinfo=UTC)

ISO_TS_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)
TIME_ONLY_RE = re.compile(r"^\[?(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\b")
KEY_VALUE_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)=(?P<value>[^ ]*)")
PAPER_CHAT_RE = re.compile(
    r"(?:\[[^\]]+\]\s*)?(?:\[[^\]]+\]:\s*)?<(?P<agent>[^>]+)>\s*(?P<message>.+)"
)
BRIDGE_EMIT_JSON_RE = re.compile(r"bridge_emit_event\s+(?P<body>\{.*\})")


@dataclass
class TimelineEvent:
    ts: datetime
    seq: int
    event_type: str
    agent: str | None
    trace_id: str | None
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "event_id": self.event_id,
            "ts": isoformat_z(self.ts),
            "seq": self.seq,
            "event_type": self.event_type,
            "agent": self.agent,
            "trace_id": self.trace_id,
            "source": self.source,
            "payload": self.payload,
        }
        return data


@dataclass
class TimelineResult:
    events: list[TimelineEvent]
    totals: dict[str, Any]


def isoformat_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    if value.microsecond:
        text = value.isoformat(timespec="milliseconds")
    else:
        text = value.isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")


def parse_iso_ts(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    match = re.match(r"^(.*[+-]\d{2})(\d{2})$", raw)
    if match and ":" not in match.group(2):
        raw = f"{match.group(1)}:{match.group(2)}"
    try:
        parsed = datetime.fromisoformat(raw.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def local_log_timezone() -> Any:
    configured = os.environ.get("SOAK_LOCAL_TIMEZONE") or os.environ.get("TZ")
    if configured:
        try:
            return ZoneInfo(configured)
        except ZoneInfoNotFoundError:
            pass
    return datetime.now().astimezone().tzinfo or UTC


def parse_local_time_only(parsed_time: time, *, base_date: datetime) -> datetime:
    local_tz = local_log_timezone()
    local_base = base_date.astimezone(local_tz)
    candidate = datetime.combine(
        local_base.date(),
        parsed_time.replace(tzinfo=None),
        tzinfo=local_tz,
    ).astimezone(UTC)
    while candidate < base_date - timedelta(hours=1):
        candidate += timedelta(days=1)
    while candidate > base_date + timedelta(hours=36):
        candidate -= timedelta(days=1)
    return candidate


def parse_metadata_start(run_dir: Path) -> datetime:
    metadata = run_dir / "metadata.env"
    if not metadata.exists():
        return DEFAULT_BASE_TS
    for line in metadata.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("start_utc="):
            return parse_iso_ts(line.split("=", 1)[1]) or DEFAULT_BASE_TS
    return DEFAULT_BASE_TS


def parse_line_ts(
    line: str,
    *,
    base_date: datetime,
    fallback_seq: int,
    fallback_ts: datetime | None = None,
) -> datetime:
    match = ISO_TS_RE.search(line)
    if match:
        parsed = parse_iso_ts(match.group("ts"))
        if parsed is not None:
            return parsed

    time_match = TIME_ONLY_RE.search(line.strip())
    if time_match:
        parsed_time = time(
            int(time_match.group("h")),
            int(time_match.group("m")),
            int(time_match.group("s")),
        )
        return parse_local_time_only(parsed_time, base_date=base_date)

    return fallback_ts or base_date + timedelta(milliseconds=fallback_seq)


def rel_source(path: Path, run_dir: Path) -> str:
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return str(path)


def read_json_line(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def first_int(*values: Any) -> int | None:
    for value in values:
        coerced = coerce_int(value)
        if coerced is not None:
            return coerced
    return None


def estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            text = str(value)
    return max(1, (len(text) + 3) // 4) if text else 0


def normalize_usage(payload: dict[str, Any], *, event_type: str) -> dict[str, Any]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = first_int(payload.get("prompt_tokens"), usage.get("prompt_tokens"))
    completion_tokens = first_int(payload.get("completion_tokens"), usage.get("completion_tokens"))
    completion_details = usage.get("completion_tokens_details")
    if not isinstance(completion_details, dict):
        completion_details = {}
    reasoning_tokens = first_int(
        payload.get("reasoning_tokens"),
        usage.get("reasoning_tokens"),
        completion_details.get("reasoning_tokens"),
    )
    total_tokens = first_int(payload.get("total_tokens"), usage.get("total_tokens"))
    billable_total_tokens = first_int(payload.get("billable_total_tokens"))

    reported = prompt_tokens is not None and (
        total_tokens is not None or completion_tokens is not None or event_type == "llm.request"
    )
    estimated = bool(payload.get("estimated", False))

    if prompt_tokens is None:
        prompt_tokens = estimate_tokens(
            payload.get("prompt")
            or payload.get("messages")
            or payload.get("input")
            or payload.get("request")
            or ""
        )
        estimated = True
    if completion_tokens is None:
        completion_tokens = estimate_tokens(
            payload.get("completion")
            or payload.get("response_text")
            or payload.get("output")
            or payload.get("choices")
            or ""
        )
        if event_type == "llm.response":
            estimated = True
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
        estimated = True
    if reasoning_tokens is None:
        reasoning_tokens = 0
    if billable_total_tokens is None:
        billable_total_tokens = total_tokens + reasoning_tokens

    payload["prompt_tokens"] = int(prompt_tokens)
    payload["completion_tokens"] = int(completion_tokens)
    payload["reasoning_tokens"] = int(reasoning_tokens)
    payload["total_tokens"] = int(total_tokens)
    payload["billable_total_tokens"] = int(billable_total_tokens)
    payload["estimated"] = bool(estimated or not reported)
    payload["usage_source"] = "estimated" if payload["estimated"] else "provider_reported"
    if event_type == "llm.request":
        payload.setdefault("latency_ms", 0)
        payload.setdefault("outcome", "started")
    return payload


def trace_from_text(line: str) -> str | None:
    match = TRACE_RE.search(line)
    return match.group("trace_id") if match else None


def parse_position(line: str) -> dict[str, float] | None:
    match = POSITION_RE.search(line) or XYZ_RE.search(line)
    if not match:
        return None
    return {
        "x": float(match.group("x")),
        "y": float(match.group("y")),
        "z": float(match.group("z")),
    }


def commands_from_line(line: str) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for match in COMMAND_CALL_RE.finditer(line):
        commands.append(
            {
                "name": match.group("name"),
                "text": excerpt(match.group(0), limit=180),
                "args": excerpt(match.group("args") or "", limit=180),
            }
        )
    return commands


def command_payload(command: ParsedCommand) -> dict[str, str]:
    return {
        "name": command.name.lstrip("!"),
        "text": command.text,
        "args": command.args,
        "source": command.source,
    }


def parse_kv_line(line: str) -> dict[str, str]:
    return {match.group("key"): match.group("value") for match in KEY_VALUE_RE.finditer(line)}


def bridge_event_type(fields: dict[str, str]) -> str:
    service = fields.get("service", "")
    method = fields.get("method", "")
    phase = fields.get("phase", "")
    ok = fields.get("ok", "")
    if ok == "false":
        return "error"
    if service == "action" and method == "result":
        return "bridge.action.start" if phase == "start" else "bridge.action.result"
    if service == "perception" and method == "report":
        return "state.sample"
    return "lifecycle"


def event_from_bridge_line(
    *,
    line: str,
    ts: datetime,
    seq: int,
    source: str,
    default_agent: str | None,
) -> TimelineEvent | None:
    if "bridge_event " not in line and "bridge_inbound_event " not in line:
        return None

    fields = parse_kv_line(line)
    if not fields:
        return None

    inbound_type = fields.get("event_type", "")
    if "bridge_inbound_event " in line:
        if inbound_type.endswith("BRIDGE_ACTION_RESULT") or inbound_type.endswith(
            "bridge_action_result"
        ):
            event_type = "bridge.action.result"
        elif inbound_type.endswith("BRIDGE_PERCEPTION") or inbound_type.endswith(
            "bridge_perception"
        ):
            event_type = "state.sample"
        else:
            event_type = "lifecycle"
    else:
        event_type = bridge_event_type(fields)

    payload: dict[str, Any] = {
        "bridge": fields,
        "line": excerpt(line),
    }
    return TimelineEvent(
        ts=ts,
        seq=seq,
        event_type=event_type,
        agent=(fields.get("agent_id") if fields.get("agent_id") != "-" else None) or default_agent,
        trace_id=(fields.get("trace_id") if fields.get("trace_id") != "-" else None),
        source=source,
        payload=payload,
    )


def event_from_bridge_emit_json(
    *,
    line: str,
    ts: datetime,
    seq: int,
    source: str,
    default_agent: str | None,
) -> TimelineEvent | None:
    match = BRIDGE_EMIT_JSON_RE.search(line)
    if not match:
        return None
    data = read_json_line(match.group("body"))
    if not data:
        return None
    event_type = str(data.get("event_type") or data.get("type") or "")
    if event_type not in EVENT_TYPES:
        raw = event_type.lower()
        if "action" in raw:
            event_type = "action.result"
        elif "perception" in raw or "state" in raw:
            event_type = "state.sample"
        else:
            event_type = "lifecycle"
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else dict(data)
    return TimelineEvent(
        ts=parse_iso_ts(str(data.get("ts") or data.get("timestamp") or "")) or ts,
        seq=seq,
        event_type=event_type,
        agent=str(data.get("agent") or data.get("agent_id") or default_agent or "").lower() or None,
        trace_id=data.get("trace_id") or data.get("traceId") or trace_from_text(line),
        source=source,
        payload=payload,
    )


def parse_raw_timeline_file(
    path: Path, run_dir: Path, base_ts: datetime, start_seq: int
) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    source = rel_source(path, run_dir)
    default_agent = path.stem.lower() if path.stem else None
    for line_no, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        data = read_json_line(raw_line)
        seq = start_seq + line_no
        if not data:
            events.append(
                TimelineEvent(
                    ts=base_ts + timedelta(milliseconds=seq),
                    seq=seq,
                    event_type="error",
                    agent=default_agent,
                    trace_id=None,
                    source=source,
                    payload={
                        "class": "malformed_ndjson",
                        "line": line_no,
                        "text": excerpt(raw_line),
                    },
                )
            )
            continue

        event_type = str(data.get("event_type") or data.get("type") or "")
        if event_type not in EVENT_TYPES:
            continue
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        payload = {**payload}
        for key, value in data.items():
            if key not in {
                "event_id",
                "seq",
                "ts",
                "timestamp",
                "event_type",
                "type",
                "agent",
                "agent_id",
                "trace_id",
                "traceId",
                "source",
                "payload",
            }:
                payload.setdefault(key, value)
        if event_type in {"llm.request", "llm.response"}:
            payload = normalize_usage(payload, event_type=event_type)
        if event_type.startswith("llm.queue."):
            agent = data.get("agent") or data.get("agent_id") or payload.get("agent")
        else:
            agent = (
                data.get("agent") or data.get("agent_id") or payload.get("agent") or default_agent
            )
        trace_id = (
            data.get("trace_id")
            or data.get("traceId")
            or payload.get("trace_id")
            or payload.get("traceId")
        )
        events.append(
            TimelineEvent(
                ts=parse_iso_ts(str(data.get("ts") or data.get("timestamp") or ""))
                or base_ts + timedelta(milliseconds=seq),
                seq=seq,
                event_type=event_type,
                agent=str(agent).lower() if agent else None,
                trace_id=str(trace_id) if trace_id else None,
                source=str(data.get("source") or source),
                payload=payload,
            )
        )
    return events


def parse_bot_log(
    path: Path,
    run_dir: Path,
    base_ts: datetime,
    start_seq: int,
    *,
    state_sample_interval_seconds: int,
    infer_llm_from_bot_log: bool = True,
) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    source = rel_source(path, run_dir)
    agent = path.stem.lower()
    last_state_ts: datetime | None = None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    interpolate_fallback = file_mtime > base_ts and len(lines) > 1

    def fallback_ts(line_no: int, seq: int) -> datetime:
        if interpolate_fallback:
            ratio = (line_no - 1) / max(1, len(lines) - 1)
            elapsed_seconds = (file_mtime - base_ts).total_seconds()
            return base_ts + timedelta(seconds=elapsed_seconds * ratio)
        return base_ts + timedelta(milliseconds=seq)

    parsed_bot_log = parse_bot_log_lines(lines)
    generations_by_line = {generation.line: generation for generation in parsed_bot_log.generations}
    llm_requests_by_line: dict[int, list[Any]] = defaultdict(list)
    trace_by_generation_line = {
        generation.line: f"trace-llm-{agent}-{generation.line}"
        for generation in parsed_bot_log.generations
    }
    for generation in parsed_bot_log.generations:
        if generation.request_line is not None:
            llm_requests_by_line[generation.request_line].append(generation)
    commands_by_line: dict[int, list[ParsedCommand]] = defaultdict(list)
    for command in parsed_bot_log.accepted_commands:
        commands_by_line[command.line].append(command)
    executions_by_line = {execution.line: execution for execution in parsed_bot_log.executions}
    execution_lines = {
        line_no
        for execution in parsed_bot_log.executions
        for line_no in range(execution.line, execution.end_line + 1)
    }
    for line_no, line in enumerate(lines, start=1):
        seq = start_seq + line_no
        ts = parse_line_ts(
            line,
            base_date=base_ts,
            fallback_seq=seq,
            fallback_ts=fallback_ts(line_no, seq),
        )
        trace_id = trace_from_text(line)
        line_trace_id = trace_id

        bridge = event_from_bridge_line(
            line=line, ts=ts, seq=seq, source=source, default_agent=agent
        )
        if bridge is not None:
            events.append(bridge)

        if infer_llm_from_bot_log:
            for generation in llm_requests_by_line.get(line_no, []):
                inferred_trace_id = trace_by_generation_line[generation.line]
                events.append(
                    TimelineEvent(
                        ts=ts,
                        seq=seq,
                        event_type="llm.request",
                        agent=agent,
                        trace_id=inferred_trace_id,
                        source=source,
                        payload={
                            "line": line_no,
                            "model": generation.model,
                            "purpose": "mindcraft_chat",
                            "reason": "bot_log_inferred",
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                            "estimated": True,
                            "usage_source": "bot_log_inferred",
                            "outcome": "started",
                            "prompt_unavailable": True,
                        },
                    )
                )

            generation = generations_by_line.get(line_no)
            if generation:
                response_text = generation.response_text
                inferred_trace_id = trace_by_generation_line[generation.line]
                request_ts = None
                if generation.request_line is not None:
                    request_seq = start_seq + generation.request_line
                    request_ts = parse_line_ts(
                        lines[generation.request_line - 1],
                        base_date=base_ts,
                        fallback_seq=request_seq,
                        fallback_ts=fallback_ts(generation.request_line, request_seq),
                    )
                latency_ms = None
                if isinstance(request_ts, datetime):
                    latency_ms = max(0, int((ts - request_ts).total_seconds() * 1000))
                completion_tokens = estimate_tokens(response_text)
                line_trace_id = inferred_trace_id
                accepted_command_count = sum(
                    1
                    for command in parsed_bot_log.accepted_commands
                    if command.generation_line == generation.line
                )
                events.append(
                    TimelineEvent(
                        ts=ts,
                        seq=seq,
                        event_type="llm.response",
                        agent=agent,
                        trace_id=inferred_trace_id,
                        source=source,
                        payload={
                            "line": line_no,
                            "model": generation.model,
                            "purpose": "mindcraft_chat",
                            "reason": "bot_log_inferred",
                            "latency_ms": latency_ms,
                            "latency_estimated": True,
                            "prompt_tokens": 0,
                            "completion_tokens": completion_tokens,
                            "total_tokens": completion_tokens,
                            "estimated": True,
                            "usage_source": "bot_log_inferred",
                            "outcome": (
                                "discarded_stale"
                                if generation.stale
                                else ("ok" if response_text else "blank")
                            ),
                            "response_text": response_text,
                            "completion": response_text,
                            "prompt_unavailable": True,
                            "contains_command": generation.command_count > 0,
                            "generated_commands": generation.command_count,
                            "discarded_commands": generation.command_count
                            if generation.stale
                            else 0,
                            "accepted_commands": accepted_command_count,
                        },
                    )
                )

        parser_failure = (
            classify_parser_failure(line)
            if line_no not in execution_lines and should_count_parser_failure(line)
            else None
        )
        if parser_failure:
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="error",
                    agent=agent,
                    trace_id=line_trace_id,
                    source=source,
                    payload={
                        "class": parser_failure,
                        "line": line_no,
                        "text": excerpt(line),
                    },
                )
            )
            continue

        accepted_commands = commands_by_line.get(line_no, [])
        commands = [command_payload(command) for command in accepted_commands]
        if commands:
            command_trace_id = line_trace_id
            generation_line = accepted_commands[0].generation_line
            if generation_line is not None:
                command_trace_id = trace_by_generation_line.get(generation_line, command_trace_id)
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="action.intent",
                    agent=agent,
                    trace_id=command_trace_id,
                    source=source,
                    payload={
                        "line": line_no,
                        "text": excerpt(line),
                        "commands": commands,
                        "accepted": True,
                    },
                )
            )
        action_match = ACTION_TRACE_RE.search(line)
        if (
            action_match
            and line_no not in execution_lines
            and not EXECUTION_SUCCESS_RE.search(line)
            and not EXECUTION_FAILURE_RE.search(line)
        ):
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="action.start",
                    agent=agent,
                    trace_id=action_match.group("trace_id"),
                    source=source,
                    payload={
                        "line": line_no,
                        "action": action_match.group("action"),
                        "detail": excerpt(action_match.group("detail")),
                    },
                )
            )

        execution = executions_by_line.get(line_no)
        if execution:
            event_trace = line_trace_id
            if execution.generation_line is not None:
                event_trace = trace_by_generation_line.get(execution.generation_line, event_trace)
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="action.result",
                    agent=agent,
                    trace_id=event_trace,
                    source=source,
                    payload={
                        "line": line_no,
                        "action": execution.action,
                        "outcome": execution.outcome,
                        "outcome_class": execution.outcome_class,
                        "verified": execution.verified,
                        "detail": excerpt(execution.detail),
                    },
                )
            )
        elif not parsed_bot_log.executions:
            execution_kind, verified = classify_execution(line)
            if execution_kind:
                event_trace = line_trace_id
                action_name = None
                detail = line
                if action_match:
                    event_trace = action_match.group("trace_id")
                    action_name = action_match.group("action")
                    detail = action_match.group("detail")
                events.append(
                    TimelineEvent(
                        ts=ts,
                        seq=seq,
                        event_type="action.result",
                        agent=agent,
                        trace_id=event_trace,
                        source=source,
                        payload={
                            "line": line_no,
                            "action": action_name,
                            "outcome": execution_kind,
                            "verified": verified,
                            "detail": excerpt(detail),
                        },
                    )
                )

        position = parse_position(line)
        if position is not None:
            if (
                last_state_ts is None
                or (ts - last_state_ts).total_seconds() >= state_sample_interval_seconds
            ):
                last_state_ts = ts
                events.append(
                    TimelineEvent(
                        ts=ts,
                        seq=seq,
                        event_type="state.sample",
                        agent=agent,
                        trace_id=line_trace_id,
                        source=source,
                        payload={
                            "line": line_no,
                            "position": position,
                            "sample_interval_seconds": state_sample_interval_seconds,
                        },
                    )
                )

        chat_match = CHAT_RE.search(line)
        if chat_match and not COMMAND_RE.search(line):
            speaker = chat_match.group("angle") or chat_match.group("name")
            message = chat_match.group("message").strip()
            if speaker and speaker.lower() == agent and message:
                events.append(
                    TimelineEvent(
                        ts=ts,
                        seq=seq,
                        event_type="chat.public",
                        agent=agent,
                        trace_id=line_trace_id,
                        source=source,
                        payload={"line": line_no, "speaker": speaker, "message": message},
                    )
                )

        setup_noise = SETUP_NOISE_RE.search(line) is not None
        generated_response_line = line.strip().startswith("Generated response:")
        if LIFECYCLE_RE.search(line) and not setup_noise and not generated_response_line:
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="lifecycle",
                    agent=agent,
                    trace_id=line_trace_id,
                    source=source,
                    payload={"line": line_no, "text": excerpt(line)},
                )
            )
        behavior_match = BEHAVIOR_STATUS_RE.search(line)
        if behavior_match:
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="behavior.event",
                    agent=agent,
                    trace_id=line_trace_id,
                    source=source,
                    payload={
                        "line": line_no,
                        "kind": behavior_match.group("kind"),
                        "text": excerpt(behavior_match.group("message")),
                    },
                )
            )
        elif CRASH_ERROR_RE.search(line) and not ACTION_CONTEXT_RE.search(line) and not setup_noise:
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="error",
                    agent=agent,
                    trace_id=line_trace_id,
                    source=source,
                    payload={"class": "runtime_error", "line": line_no, "text": excerpt(line)},
                )
            )
    return events


def parse_log_file(
    path: Path, run_dir: Path, base_ts: datetime, start_seq: int
) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    source = rel_source(path, run_dir)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_no, line in enumerate(lines, start=1):
        seq = start_seq + line_no
        ts = parse_line_ts(line, base_date=base_ts, fallback_seq=seq)

        for maybe in (
            event_from_bridge_line(line=line, ts=ts, seq=seq, source=source, default_agent=None),
            event_from_bridge_emit_json(
                line=line, ts=ts, seq=seq, source=source, default_agent=None
            ),
        ):
            if maybe is not None:
                events.append(maybe)

        paper_chat = PAPER_CHAT_RE.search(line)
        if paper_chat and not COMMAND_RE.search(paper_chat.group("message")):
            agent = paper_chat.group("agent").strip()
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="chat.public",
                    agent=agent.lower(),
                    trace_id=trace_from_text(line),
                    source=source,
                    payload={
                        "line": line_no,
                        "speaker": agent,
                        "message": paper_chat.group("message").strip(),
                    },
                )
            )
        elif CRASH_ERROR_RE.search(line):
            events.append(
                TimelineEvent(
                    ts=ts,
                    seq=seq,
                    event_type="error",
                    agent=None,
                    trace_id=trace_from_text(line),
                    source=source,
                    payload={"class": "runtime_error", "line": line_no, "text": excerpt(line)},
                )
            )
    return events


def raw_timeline_paths(run_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for root in (run_dir / "timeline-raw", run_dir / "logs"):
        if root.is_dir():
            candidates.extend(sorted(root.glob("*.ndjson")))
    candidates.extend(sorted(run_dir.glob("*lmstudio*.ndjson")))
    candidates.extend(sorted(run_dir.glob("*timeline*.ndjson")))
    return [
        path
        for path in dict.fromkeys(candidates)
        if path.name not in {"timeline.ndjson"} and path.is_file()
    ]


def has_raw_llm_events(run_dir: Path) -> bool:
    for path in raw_timeline_paths(run_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if '"llm.request"' in text or '"llm.response"' in text:
            return True
    return False


def correlate_events(events: list[TimelineEvent]) -> list[TimelineEvent]:
    ordered = sorted(
        events, key=lambda event: (event.ts, event.seq, event.source, event.event_type)
    )
    last_llm_trace: dict[str, str] = {}
    last_intent_trace: dict[str, str] = {}
    last_action_trace: dict[str, str] = {}

    for event in ordered:
        agent = event.agent or ""
        if event.event_type == "llm.response" and event.trace_id and agent:
            last_llm_trace[agent] = event.trace_id
            continue

        if event.event_type == "action.intent" and agent:
            if not event.trace_id:
                event.trace_id = last_llm_trace.get(agent)
            if event.trace_id:
                last_intent_trace[agent] = event.trace_id
            continue

        if event.event_type == "action.start" and agent:
            if not event.trace_id:
                event.trace_id = last_intent_trace.get(agent) or last_llm_trace.get(agent)
            if event.trace_id:
                last_action_trace[agent] = event.trace_id
            continue

        if event.event_type == "action.result" and agent:
            if not event.trace_id:
                event.trace_id = (
                    last_action_trace.get(agent)
                    or last_intent_trace.get(agent)
                    or last_llm_trace.get(agent)
                )
            if event.trace_id:
                last_action_trace[agent] = event.trace_id

    for index, event in enumerate(ordered, start=1):
        event.seq = index
        event.event_id = f"timeline-{index:06d}"
    return ordered


def dedupe_director_gate_decisions(events: list[TimelineEvent]) -> list[TimelineEvent]:
    preferred_index_by_key: dict[tuple[Any, ...], int] = {}
    key_by_index: dict[int, tuple[Any, ...]] = {}

    for index, event in enumerate(events):
        if event.event_type != "director.gate.decision" or not event.trace_id:
            continue
        key = (
            event.trace_id,
            event.agent,
            event.payload.get("scene_id"),
            bool(event.payload.get("selected")),
            event.payload.get("turn_kind"),
            event.payload.get("reason_code") or event.payload.get("reason"),
            event.payload.get("build_plan_id"),
        )
        key_by_index[index] = key
        previous = preferred_index_by_key.get(key)
        if previous is None or (
            event.source == "director_v2" and events[previous].source != "director_v2"
        ):
            preferred_index_by_key[key] = index

    if not key_by_index:
        return events
    return [
        event
        for index, event in enumerate(events)
        if index not in key_by_index or preferred_index_by_key.get(key_by_index[index]) == index
    ]


def summarize_events(events: list[TimelineEvent], run_dir: Path) -> dict[str, Any]:
    by_event_type = Counter(event.event_type for event in events)
    by_agent = Counter(event.agent for event in events if event.agent)
    by_model = Counter(
        str(event.payload.get("model"))
        for event in events
        if event.event_type in {"llm.request", "llm.response"} and event.payload.get("model")
    )

    usage_by_request: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type not in {"llm.request", "llm.response"}:
            continue
        key = f"{event.agent or 'unknown'}:{event.trace_id or event.event_id}"
        if event.event_type == "llm.response" or key not in usage_by_request:
            usage_by_request[key] = {
                "agent": event.agent or "unknown",
                "model": str(event.payload.get("model") or "unknown"),
                "prompt_tokens": int(event.payload.get("prompt_tokens") or 0),
                "completion_tokens": int(event.payload.get("completion_tokens") or 0),
                "reasoning_tokens": int(event.payload.get("reasoning_tokens") or 0),
                "total_tokens": int(event.payload.get("total_tokens") or 0),
                "billable_total_tokens": int(
                    event.payload.get("billable_total_tokens")
                    or event.payload.get("total_tokens")
                    or 0
                ),
                "estimated": bool(event.payload.get("estimated", True)),
                "usage_source": event.payload.get("usage_source") or "estimated",
            }

    token_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "billable_total_tokens": 0,
        "requests": 0,
        "provider_reported": {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "billable_total_tokens": 0,
        },
        "estimated": {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "billable_total_tokens": 0,
        },
    }
    tokens_by_agent: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "billable_total_tokens": 0,
        }
    )
    tokens_by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "billable_total_tokens": 0,
        }
    )

    for usage in usage_by_request.values():
        bucket_name = "estimated" if usage["estimated"] else "provider_reported"
        token_totals["requests"] += 1
        for token_key in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
            "billable_total_tokens",
        ):
            token_totals[token_key] += usage[token_key]
            token_totals[bucket_name][token_key] += usage[token_key]
        token_totals[bucket_name]["requests"] += 1

        agent_target = tokens_by_agent[usage["agent"]]
        model_target = tokens_by_model[usage["model"]]
        for target in (agent_target, model_target):
            target["requests"] += 1
            target["prompt_tokens"] += usage["prompt_tokens"]
            target["completion_tokens"] += usage["completion_tokens"]
            target["reasoning_tokens"] += usage["reasoning_tokens"]
            target["total_tokens"] += usage["total_tokens"]
            target["billable_total_tokens"] += usage["billable_total_tokens"]

    tokens = {
        "requests": token_totals["requests"],
        "prompt": token_totals["prompt_tokens"],
        "completion": token_totals["completion_tokens"],
        "reasoning": token_totals["reasoning_tokens"],
        "total": token_totals["total_tokens"],
        "billable_total": token_totals["billable_total_tokens"],
        "provider_reported": token_totals["provider_reported"]["total_tokens"],
        "provider_reported_requests": token_totals["provider_reported"]["requests"],
        "provider_reported_billable_total": token_totals["provider_reported"][
            "billable_total_tokens"
        ],
        "estimated": token_totals["estimated"]["total_tokens"],
        "estimated_requests": token_totals["estimated"]["requests"],
        "estimated_billable_total": token_totals["estimated"]["billable_total_tokens"],
    }

    builder_usage: dict[str, Any] = {
        "paid_calls": 0,
        "local_calls": 0,
        "estimated_usd": 0.0,
        "failures": 0,
        "fallbacks": 0,
        "by_provider": defaultdict(
            lambda: {
                "calls": 0,
                "paid_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "billable_total_tokens": 0,
                "estimated_usd": 0.0,
            }
        ),
    }
    builder_usage_by_agent: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "paid_calls": 0,
            "local_calls": 0,
            "estimated_usd": 0.0,
            "failures": 0,
            "fallbacks": 0,
        }
    )
    for event in events:
        if not event.event_type.startswith("build_plan.generation."):
            continue
        payload = event.payload
        agent = event.agent or "unknown"
        agent_bucket = builder_usage_by_agent[agent]
        if event.event_type in {
            "build_plan.generation.provider_failed",
            "build_plan.generation.budget_capped",
        }:
            builder_usage["failures"] += 1
            agent_bucket["failures"] += 1
            if payload.get("fallback_reason"):
                builder_usage["fallbacks"] += 1
                agent_bucket["fallbacks"] += 1
            continue
        if event.event_type != "build_plan.generation.completed":
            continue
        provider = str(payload.get("builder_provider") or payload.get("provider") or "unknown")
        paid = bool(payload.get("paid") or provider == "openrouter")
        prompt_tokens = int(payload.get("prompt_tokens") or 0)
        completion_tokens = int(payload.get("completion_tokens") or 0)
        reasoning_tokens = int(payload.get("reasoning_tokens") or 0)
        total_tokens = int(payload.get("total_tokens") or prompt_tokens + completion_tokens)
        billable_total_tokens = int(payload.get("billable_total_tokens") or total_tokens)
        estimated_usd = coerce_float(payload.get("estimated_usd")) or 0.0
        provider_bucket = builder_usage["by_provider"][provider]
        provider_bucket["calls"] += 1
        provider_bucket["prompt_tokens"] += prompt_tokens
        provider_bucket["completion_tokens"] += completion_tokens
        provider_bucket["reasoning_tokens"] += reasoning_tokens
        provider_bucket["total_tokens"] += total_tokens
        provider_bucket["billable_total_tokens"] += billable_total_tokens
        provider_bucket["estimated_usd"] += estimated_usd
        builder_usage["estimated_usd"] += estimated_usd
        agent_bucket["estimated_usd"] += estimated_usd
        if paid:
            builder_usage["paid_calls"] += 1
            provider_bucket["paid_calls"] += 1
            agent_bucket["paid_calls"] += 1
        else:
            builder_usage["local_calls"] += 1
            agent_bucket["local_calls"] += 1
        if payload.get("fallback_reason"):
            builder_usage["fallbacks"] += 1
            agent_bucket["fallbacks"] += 1

    builder_usage["estimated_usd"] = round(float(builder_usage["estimated_usd"]), 8)
    builder_usage["by_provider"] = {
        provider: {
            **bucket,
            "estimated_usd": round(float(bucket["estimated_usd"]), 8),
        }
        for provider, bucket in sorted(builder_usage["by_provider"].items())
    }
    builder_usage_by_agent = {
        agent: {
            **bucket,
            "estimated_usd": round(float(bucket["estimated_usd"]), 8),
        }
        for agent, bucket in sorted(builder_usage_by_agent.items())
    }

    director_events = [event for event in events if event.event_type.startswith("director.")]
    gate_decisions = [
        event for event in director_events if event.event_type == "director.gate.decision"
    ]
    selected_turns = [event for event in gate_decisions if bool(event.payload.get("selected"))]
    suppressed_turns = [
        event for event in gate_decisions if not bool(event.payload.get("selected"))
    ]
    suppressed_by_reason = Counter(
        str(
            event.payload.get("suppression_reason") or event.payload.get("reason_code") or "unknown"
        )
        for event in suppressed_turns
    )
    stale_discarded = sum(
        1
        for event in events
        if event.event_type == "llm.response"
        and str(event.payload.get("outcome") or "") == "discarded_stale"
    )
    memory_compactions = [
        event for event in director_events if event.event_type == "director.memory.compaction"
    ]
    tool_calls = [event for event in director_events if event.event_type == "director.tool.call"]
    tool_calls_by_tool = Counter(
        str(event.payload.get("tool_name") or "unknown") for event in tool_calls
    )
    build_macros_by_owner: Counter[str] = Counter()
    build_plan_ids: set[str] = set()
    for event in events:
        if event.event_type.startswith("build_plan.generation."):
            owner = (
                event.payload.get("owner")
                or event.payload.get("build_plan_owner")
                or event.payload.get("active_build_owner")
            )
            if owner:
                build_macros_by_owner[str(owner).lower()] += 1
            plan_id = event.payload.get("plan_id") or event.payload.get("action_id")
            if plan_id:
                build_plan_ids.add(str(plan_id))
            continue
        if event.event_type == "director.gate.decision":
            owner = event.payload.get("build_owner")
            plan_id = event.payload.get("build_plan_id")
            if owner and plan_id and event.payload.get("build_role") == "planner_owner":
                build_macros_by_owner[str(owner).lower()] += 1
                build_plan_ids.add(str(plan_id))

    selected_by_agent = Counter(str(event.agent or "unknown") for event in selected_turns)
    suppressed_by_agent = Counter(str(event.agent or "unknown") for event in suppressed_turns)
    llm_prompt_count = sum(
        int(event.payload.get("llm_prompt_count") or 0) for event in gate_decisions
    )
    if not gate_decisions:
        llm_prompt_count = token_totals["requests"]
    scene_turn_count = len(selected_turns)
    director_summary = {
        "scenes_opened": sum(
            1 for event in director_events if event.event_type == "director.scene.opened"
        ),
        "scenes_closed": sum(
            1 for event in director_events if event.event_type == "director.scene.closed"
        ),
        "selected_turns": scene_turn_count,
        "suppressed_count": len(suppressed_turns),
        "suppressed_by_reason": dict(sorted(suppressed_by_reason.items())),
        "queue_depth_max": max(
            (coerce_int(event.payload.get("queue_depth")) or 0 for event in director_events),
            default=0,
        ),
        "stale_discarded": stale_discarded,
        "memory_compactions": sum(
            1 for event in memory_compactions if event.payload.get("ok") is not False
        ),
        "memory_compaction_failures": sum(
            1 for event in memory_compactions if event.payload.get("ok") is False
        ),
        "tool_calls_by_tool": dict(sorted(tool_calls_by_tool.items())),
        "tool_failures": sum(1 for event in tool_calls if event.payload.get("ok") is False),
        "build_macros_by_owner": dict(sorted(build_macros_by_owner.items())),
        "build_plan_ids": sorted(build_plan_ids),
        "llm_prompts_total": llm_prompt_count,
        "avoided_llm_prompts": sum(
            int(event.payload.get("avoided_prompt_count") or 0) for event in gate_decisions
        ),
        "ratio_prompts_per_scene_turn": round(llm_prompt_count / scene_turn_count, 4)
        if scene_turn_count
        else 0.0,
        "selected_by_agent": dict(sorted(selected_by_agent.items())),
        "suppressed_by_agent": dict(sorted(suppressed_by_agent.items())),
    }

    return {
        "run_dir": str(run_dir),
        "generated_at_utc": isoformat_z(datetime.now(UTC).replace(microsecond=0)),
        "event_count": len(events),
        "counts_by_event_type": dict(sorted(by_event_type.items())),
        "counts_by_agent": dict(sorted(by_agent.items())),
        "counts_by_model": dict(sorted(by_model.items())),
        "tokens": tokens,
        "token_totals": token_totals,
        "tokens_by_agent": dict(sorted(tokens_by_agent.items())),
        "tokens_by_model": dict(sorted(tokens_by_model.items())),
        "builder_usage": builder_usage,
        "builder_usage_by_agent": builder_usage_by_agent,
        "director": director_summary,
    }


def build_timeline(
    run_dir: Path,
    *,
    state_sample_interval_seconds: int = DEFAULT_STATE_SAMPLE_INTERVAL_SECONDS,
) -> TimelineResult:
    base_ts = parse_metadata_start(run_dir)
    events: list[TimelineEvent] = []
    seq_base = 0
    infer_llm_from_bot_log = not has_raw_llm_events(run_dir)

    for path in sorted((run_dir / "bots").glob("*.log")) if (run_dir / "bots").is_dir() else []:
        parsed = parse_bot_log(
            path,
            run_dir,
            base_ts,
            seq_base,
            state_sample_interval_seconds=state_sample_interval_seconds,
            infer_llm_from_bot_log=infer_llm_from_bot_log,
        )
        events.extend(parsed)
        seq_base += max(100000, len(parsed) + 1000)

    for path in sorted((run_dir / "logs").glob("*.log")) if (run_dir / "logs").is_dir() else []:
        parsed = parse_log_file(path, run_dir, base_ts, seq_base)
        events.extend(parsed)
        seq_base += max(100000, len(parsed) + 1000)

    for path in raw_timeline_paths(run_dir):
        parsed = parse_raw_timeline_file(path, run_dir, base_ts, seq_base)
        events.extend(parsed)
        seq_base += max(100000, len(parsed) + 1000)

    ordered = dedupe_director_gate_decisions(correlate_events(events))
    totals = summarize_events(ordered, run_dir)
    return TimelineResult(events=ordered, totals=totals)


def write_artifacts(
    run_dir: Path,
    result: TimelineResult,
    *,
    output_path: Path | None = None,
    totals_path: Path | None = None,
) -> tuple[Path, Path]:
    timeline_path = output_path or run_dir / "timeline.ndjson"
    totals_path = totals_path or run_dir / "timeline-totals.json"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    totals_path.parent.mkdir(parents=True, exist_ok=True)
    with timeline_path.open("w", encoding="utf-8") as handle:
        for event in result.events:
            handle.write(json.dumps(event.to_json(), sort_keys=True, separators=(",", ":")) + "\n")
    totals_path.write_text(
        json.dumps(result.totals, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return timeline_path, totals_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export a canonical Minecraft soak timeline as timeline.ndjson and "
            "timeline-totals.json."
        )
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Soak evidence directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Timeline NDJSON output path. Default: <run-dir>/timeline.ndjson",
    )
    parser.add_argument(
        "--totals",
        type=Path,
        default=None,
        help="Timeline totals JSON output path. Default: <run-dir>/timeline-totals.json",
    )
    parser.add_argument(
        "--state-sample-interval-seconds",
        type=int,
        default=DEFAULT_STATE_SAMPLE_INTERVAL_SECONDS,
        help=(
            "Minimum seconds between per-agent state.sample events parsed from high-frequency "
            f"position logs. Default: {DEFAULT_STATE_SAMPLE_INTERVAL_SECONDS}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = build_timeline(
            args.run_dir,
            state_sample_interval_seconds=args.state_sample_interval_seconds,
        )
        timeline_path, totals_path = write_artifacts(
            args.run_dir,
            result,
            output_path=args.output,
            totals_path=args.totals,
        )
    except Exception as exc:
        print(f"timeline export failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"ok timeline exported {len(result.events)} events; see {timeline_path}; totals {totals_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

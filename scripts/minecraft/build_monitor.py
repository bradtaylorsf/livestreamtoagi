#!/usr/bin/env python3
"""Render a local cohort monitor for embodied Minecraft soak evidence."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_STALL_SECONDS = 120
DEFAULT_REPEAT_BLANK_COUNT = 3
DEFAULT_REPEAT_COMMAND_COUNT = 3
DEFAULT_RESTART_RECENT_SECONDS = 300
DEFAULT_STUCK_LOOP_COUNT = 3
DEFAULT_LLM_IDLE_SECONDS = 120
DEFAULT_FEED_LIMIT = 80
FIXTURE_PATH_SUFFIX = ("tests", "backend", "fixtures", "minecraft_timeline")

ACTIVE_EVENT_TYPES = {
    "chat.public",
    "llm.request",
    "llm.response",
    "llm.queue.enqueued",
    "llm.queue.started",
    "llm.queue.completed",
    "llm.queue.failed",
    "inbox.queued",
    "inbox.turn_started",
    "inbox.turn_completed",
    "action.intent",
    "action.start",
    "action.queued",
    "action.started",
    "action.completed",
    "action.rejected_busy",
    "action.result",
    "build_plan.generation.started",
    "build_plan.generation.completed",
    "build_plan.generation.skipped",
    "build_plan.generation.provider_failed",
    "build_plan.generation.budget_capped",
    "build_plan.execution.started",
    "build_plan.execution.completed",
}
COMMAND_RE = re.compile(r"!\w+\s*(?:\([^)]*\))?", re.DOTALL)
RESTART_RE = re.compile(
    r"\b(?:restart(?:ed|ing)?|reconnect(?:ed|ing)?|disconnect(?:ed)?|exited|"
    r"shutdown|kicked|crash(?:ed)?|terminated)\b",
    re.IGNORECASE,
)
STUCK_RE = re.compile(
    r"\b(?:blocked|unreachable|stuck|path(?:finding)? failed|path not found|timeout|timed out)\b",
    re.IGNORECASE,
)
BLANK_RE = re.compile(r"\b(?:blank|empty)\b", re.IGNORECASE)


@dataclass(frozen=True)
class WarningThresholds:
    stall_seconds: int = DEFAULT_STALL_SECONDS
    repeated_blank_count: int = DEFAULT_REPEAT_BLANK_COUNT
    repeated_command_count: int = DEFAULT_REPEAT_COMMAND_COUNT
    restart_recent_seconds: int = DEFAULT_RESTART_RECENT_SECONDS
    stuck_loop_count: int = DEFAULT_STUCK_LOOP_COUNT
    llm_idle_seconds: int = DEFAULT_LLM_IDLE_SECONDS


def isoformat_z(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def parse_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def thresholds_from_env() -> WarningThresholds:
    return WarningThresholds(
        stall_seconds=parse_int_env("SOAK_MONITOR_STALL_SECONDS", DEFAULT_STALL_SECONDS),
        repeated_blank_count=parse_int_env(
            "SOAK_MONITOR_REPEAT_BLANK_COUNT", DEFAULT_REPEAT_BLANK_COUNT
        ),
        repeated_command_count=parse_int_env(
            "SOAK_MONITOR_REPEAT_COMMAND_COUNT", DEFAULT_REPEAT_COMMAND_COUNT
        ),
        restart_recent_seconds=parse_int_env(
            "SOAK_MONITOR_RESTART_RECENT_SECONDS", DEFAULT_RESTART_RECENT_SECONDS
        ),
        stuck_loop_count=parse_int_env("SOAK_MONITOR_STUCK_LOOP_COUNT", DEFAULT_STUCK_LOOP_COUNT),
        llm_idle_seconds=parse_int_env("SOAK_MONITOR_LLM_IDLE_SECONDS", DEFAULT_LLM_IDLE_SECONDS),
    )


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            events.append(
                {
                    "ts": None,
                    "seq": line_no,
                    "event_type": "error",
                    "agent": None,
                    "source": str(path),
                    "payload": {
                        "class": "malformed_monitor_input",
                        "line": line_no,
                        "text": clip(line),
                    },
                }
            )
            continue
        if isinstance(data, dict):
            events.append(data)
    return events


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_metadata_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    metadata: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def parse_summary_fields(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    fields: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip()
        if key in {"start_utc", "end_utc", "planned_duration_hours"}:
            fields[key] = value.strip()
    return fields


def ensure_timeline_artifacts(run_dir: Path, *, rebuild: bool = False) -> tuple[Path, Path]:
    timeline_path = run_dir / "timeline.ndjson"
    totals_path = run_dir / "timeline-totals.json"
    if timeline_path.exists() and not rebuild:
        return timeline_path, totals_path

    has_sources = any((run_dir / name).is_dir() for name in ("bots", "logs", "timeline-raw"))
    if not has_sources:
        if timeline_path.exists():
            return timeline_path, totals_path
        raise FileNotFoundError(
            f"{timeline_path} does not exist and no raw soak evidence is present"
        )

    import build_timeline

    result = build_timeline.build_timeline(run_dir)
    return build_timeline.write_artifacts(run_dir, result)


def is_committed_fixture_run_dir(run_dir: Path) -> bool:
    return tuple(run_dir.resolve().parts[-len(FIXTURE_PATH_SUFFIX) :]) == FIXTURE_PATH_SUFFIX


def default_output_path(run_dir: Path) -> Path:
    if is_committed_fixture_run_dir(run_dir):
        digest = hashlib.sha1(str(run_dir.resolve()).encode("utf-8")).hexdigest()[:12]
        return (
            Path(tempfile.gettempdir())
            / "minecraft-cohort-monitor-fixtures"
            / digest
            / "monitor.html"
        )
    return run_dir / "monitor.html"


def event_ts(event: dict[str, Any]) -> datetime | None:
    return parse_iso_ts(event.get("ts") or event.get("timestamp"))


def event_agent(event: dict[str, Any]) -> str | None:
    raw = event.get("agent") or event.get("agent_id")
    if raw is None:
        payload = event.get("payload")
        if isinstance(payload, dict):
            raw = payload.get("agent") or payload.get("agent_id")
    if raw is None:
        return None
    text = str(raw).strip().lower()
    return text or None


def payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("payload")
    return value if isinstance(value, dict) else {}


def event_category(event_type: str) -> str:
    if event_type == "chat.public":
        return "chat"
    if event_type.startswith("llm."):
        return "llm"
    if event_type.startswith("inbox."):
        return "inbox"
    if event_type.startswith("action."):
        return "action"
    if event_type.startswith("build_plan."):
        return "build"
    if event_type == "state.sample":
        return "movement"
    if event_type.startswith("bridge.") or event_type == "behavior.event":
        return "lifecycle"
    if event_type == "error":
        return "error"
    if event_type == "lifecycle":
        return "lifecycle"
    return "lifecycle"


def display_agent(agent: str | None) -> str:
    if not agent:
        return "Cohort"
    return "-".join(part.capitalize() for part in agent.split("-"))


def clip(value: Any, limit: int = 180) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def human_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "n/a"
    remaining = max(0, int(seconds))
    hours, remaining = divmod(remaining, 3600)
    minutes, secs = divmod(remaining, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def payload_int(event: dict[str, Any], key: str, default: int = 0) -> int:
    value = payload(event).get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return default
    return default


def payload_float(event: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = payload(event).get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def parse_duration_seconds(
    metadata: dict[str, str], start: datetime | None, planned_end: datetime | None
) -> int | None:
    raw_seconds = metadata.get("duration_seconds")
    if raw_seconds:
        try:
            return int(float(raw_seconds))
        except ValueError:
            pass
    raw_hours = metadata.get("duration_hours") or metadata.get("planned_duration_hours")
    if raw_hours:
        try:
            return int(float(raw_hours) * 3600)
        except ValueError:
            pass
    if start and planned_end:
        return max(0, int((planned_end - start).total_seconds()))
    return None


def event_sort_key(event: dict[str, Any]) -> tuple[datetime, int, str]:
    ts = event_ts(event) or datetime(1970, 1, 1, tzinfo=UTC)
    seq = event.get("seq")
    try:
        seq_value = int(seq)
    except (TypeError, ValueError):
        seq_value = 0
    return ts, seq_value, str(event.get("event_id") or "")


def token_bucket(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        "requests": int(source.get("requests") or 0),
        "prompt_tokens": int(source.get("prompt_tokens") or 0),
        "completion_tokens": int(source.get("completion_tokens") or 0),
        "total_tokens": int(source.get("total_tokens") or source.get("total") or 0),
    }


def tokens_from_events(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_request: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type not in {"llm.request", "llm.response"}:
            continue
        agent = event_agent(event) or "unknown"
        event_payload = payload(event)
        key = f"{agent}:{event.get('trace_id') or event.get('event_id') or event_sort_key(event)}"
        if event_type == "llm.response" or key not in by_request:
            by_request[key] = {
                "agent": agent,
                "prompt_tokens": int(event_payload.get("prompt_tokens") or 0),
                "completion_tokens": int(event_payload.get("completion_tokens") or 0),
                "total_tokens": int(event_payload.get("total_tokens") or 0),
            }

    totals: dict[str, dict[str, int]] = {}
    for usage in by_request.values():
        agent = str(usage["agent"])
        target = totals.setdefault(
            agent,
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        target["requests"] += 1
        target["prompt_tokens"] += int(usage["prompt_tokens"])
        target["completion_tokens"] += int(usage["completion_tokens"])
        target["total_tokens"] += int(usage["total_tokens"])
    return totals


def command_signature(event: dict[str, Any]) -> str | None:
    event_payload = payload(event)
    commands = event_payload.get("commands")
    if isinstance(commands, list) and commands:
        return " | ".join(
            normalize_command(command) for command in commands if command_text(command)
        )
    if isinstance(commands, str) and commands.strip():
        return normalize_command(commands)
    for key in ("command", "text", "detail"):
        value = event_payload.get(key)
        if not isinstance(value, str):
            continue
        matches = COMMAND_RE.findall(value)
        if matches:
            return " | ".join(normalize_command(match) for match in matches)
    return None


def command_text(value: Any) -> str:
    if isinstance(value, dict):
        text = value.get("text") or value.get("command")
        if text:
            return str(text)
        name = value.get("name")
        args = value.get("args")
        if name:
            prefix = str(name)
            if not prefix.startswith("!"):
                prefix = f"!{prefix}"
            return f"{prefix}({args})" if args not in (None, "") else prefix
    return str(value).strip()


def normalize_command(value: Any) -> str:
    return re.sub(r"\s+", " ", command_text(value))


def is_blank_llm_response(event: dict[str, Any]) -> bool:
    event_payload = payload(event)
    outcome_text = " ".join(
        str(event_payload.get(key) or "") for key in ("outcome", "class", "error", "reason")
    )
    if BLANK_RE.search(outcome_text):
        return True

    response_keys = [
        key
        for key in ("completion", "response", "response_text", "output", "text", "message")
        if key in event_payload
    ]
    if response_keys:
        return all(not str(event_payload.get(key) or "").strip() for key in response_keys)
    return False


def is_restart_lifecycle(event: dict[str, Any]) -> bool:
    if str(event.get("event_type") or "") != "lifecycle":
        return False
    return RESTART_RE.search(json.dumps(payload(event), sort_keys=True, default=str)) is not None


def is_stuck_action_result(event: dict[str, Any]) -> bool:
    if str(event.get("event_type") or "") != "action.result":
        return False
    event_payload = payload(event)
    text = " ".join(
        str(event_payload.get(key) or "")
        for key in ("outcome", "status", "class", "detail", "text")
    )
    return STUCK_RE.search(text) is not None


def format_position(event_payload: dict[str, Any]) -> str:
    position = (
        event_payload.get("position") or event_payload.get("pos") or event_payload.get("location")
    )
    if isinstance(position, dict):
        x = position.get("x")
        y = position.get("y")
        z = position.get("z")
        if x is not None and y is not None and z is not None:
            return f"x={x}, y={y}, z={z}"
    return clip(position or event_payload.get("text") or "state sample")


def event_summary(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "")
    event_payload = payload(event)
    if event_type == "chat.public":
        speaker = event_payload.get("speaker") or event_agent(event)
        return clip(f"{speaker}: {event_payload.get('message', '')}")
    if event_type == "action.intent":
        signature = command_signature(event)
        return clip(signature or event_payload.get("text") or "intended action")
    if event_type == "action.start":
        return clip(
            f"{event_payload.get('action') or 'action'} started {event_payload.get('detail') or ''}"
        )
    if event_type == "action.queued":
        return clip(
            f"{event_payload.get('action') or 'action'} queued; depth {event_payload.get('queue_depth', 0)}"
        )
    if event_type == "action.started":
        source = event_payload.get("source") or "direct"
        return clip(
            f"{event_payload.get('action') or 'action'} started from {source}; depth {event_payload.get('queue_depth', 0)}"
        )
    if event_type == "action.completed":
        outcome = "success" if event_payload.get("success") else "done"
        if event_payload.get("interrupted"):
            outcome = "interrupted"
        if event_payload.get("timedout"):
            outcome = "timed out"
        return clip(
            f"{event_payload.get('action') or 'action'} {outcome}; depth {event_payload.get('queue_depth', 0)}"
        )
    if event_type == "action.rejected_busy":
        return clip(
            f"{event_payload.get('action') or 'action'} rejected busy: {event_payload.get('reason') or 'busy'}"
        )
    if event_type == "action.result":
        outcome = event_payload.get("outcome") or event_payload.get("status") or "result"
        action = event_payload.get("action") or "action"
        return clip(f"{action}: {outcome} {event_payload.get('detail') or ''}")
    if event_type == "inbox.queued":
        source = event_payload.get("source") or "unknown"
        preview = event_payload.get("message_preview") or ""
        return clip(
            f"{source} queued; depth {event_payload.get('queue_depth', 0)}; {preview}"
        )
    if event_type == "inbox.turn_started":
        return clip(
            f"turn started with {event_payload.get('batch_size', 0)} message(s) from {event_payload.get('source') or 'batch'}"
        )
    if event_type == "inbox.turn_completed":
        return clip(
            f"turn {event_payload.get('outcome') or 'completed'}; batch {event_payload.get('batch_size', 0)}; remaining {event_payload.get('remaining_depth', 0)}"
        )
    if event_type == "inbox.telemetry_ignored":
        return clip(f"telemetry ignored from {event_payload.get('source')}: {event_payload.get('message')}")
    if event_type == "inbox.immediate_command":
        return clip(
            f"immediate command from {event_payload.get('source')}: {event_payload.get('command')}"
        )
    if event_type == "llm.request":
        model = event_payload.get("model") or "unknown model"
        purpose = event_payload.get("purpose") or event_payload.get("reason") or "request"
        tokens = event_payload.get("prompt_tokens") or event_payload.get("total_tokens") or 0
        return clip(f"{model} {purpose}; prompt tokens {tokens}")
    if event_type == "llm.response":
        model = event_payload.get("model") or "unknown model"
        outcome = event_payload.get("outcome") or "response"
        latency = event_payload.get("latency_ms")
        tokens = event_payload.get("total_tokens") or 0
        latency_text = f"; {latency}ms" if latency not in (None, "") else ""
        output = event_payload.get("response_text") or event_payload.get("completion") or ""
        output_text = f"; {output}" if output else ""
        return clip(f"{model} {outcome}{latency_text}; {tokens} tokens{output_text}")
    if event_type == "llm.queue.enqueued":
        return clip(
            f"{event_payload.get('model') or 'unknown model'} enqueued; depth {event_payload.get('queued', 0)}"
        )
    if event_type == "llm.queue.started":
        return clip(
            f"{event_payload.get('model') or 'unknown model'} running; waited {event_payload.get('wait_ms', 0)}ms; active {event_payload.get('running', 0)}"
        )
    if event_type == "llm.queue.completed":
        tokens = event_payload.get("tokens") if isinstance(event_payload.get("tokens"), dict) else {}
        total = tokens.get("total_tokens") if isinstance(tokens, dict) else None
        token_text = f"; {total} tokens" if total is not None else ""
        return clip(
            f"{event_payload.get('model') or 'unknown model'} completed {event_payload.get('status') or ''}; wait {event_payload.get('wait_ms', 0)}ms; latency {event_payload.get('latency_ms', 0)}ms{token_text}"
        )
    if event_type == "llm.queue.failed":
        return clip(
            f"{event_payload.get('model') or 'unknown model'} failed after {event_payload.get('wait_ms', 0)}ms wait: {event_payload.get('error') or ''}"
        )
    if event_type == "build_plan.generation.started":
        return clip(
            f"planning {event_payload.get('description') or 'build'} at {event_payload.get('origin')}; max {event_payload.get('max_steps')} steps"
        )
    if event_type == "build_plan.generation.completed":
        plan = event_payload.get("plan")
        blocks = len(plan.get("blocks") or []) if isinstance(plan, dict) else 0
        clear = len(plan.get("clear") or []) if isinstance(plan, dict) else 0
        provider = event_payload.get("builder_provider") or event_payload.get("provider") or "builder"
        model = event_payload.get("builder_model") or event_payload.get("model")
        model_text = f" {model}" if model else ""
        paid = " paid" if event_payload.get("paid") else ""
        usd = event_payload.get("estimated_usd")
        usd_text = f"; ${usd}" if usd not in (None, "", 0, 0.0) else ""
        return clip(
            f"plan generated from {provider}{model_text}{paid}; {blocks + clear} step(s){usd_text}"
        )
    if event_type == "build_plan.generation.rejected":
        return clip(f"plan rejected: {event_payload.get('error') or 'invalid plan'}")
    if event_type == "build_plan.generation.skipped":
        reason = event_payload.get("reason") or "skipped"
        cooldown = event_payload.get("cooldown_remaining_sec") or 0
        cooldown_text = f"; cooldown {cooldown}s" if cooldown else ""
        cache_text = "; cache hit" if event_payload.get("cache_hit") else ""
        active = event_payload.get("active_build") if isinstance(event_payload.get("active_build"), dict) else {}
        plan_text = f"; active {active.get('plan_id')}" if active.get("plan_id") else ""
        return clip(f"plan skipped: {reason}{cache_text}{cooldown_text}{plan_text}")
    if event_type == "build_plan.generation.provider_failed":
        return clip(
            f"builder provider failed: {event_payload.get('reason') or 'provider_failed'} "
            f"{event_payload.get('fallback_reason') or ''}"
        )
    if event_type == "build_plan.generation.budget_capped":
        return clip(
            f"builder budget capped: {event_payload.get('reason') or 'budget_capped'} "
            f"{event_payload.get('fallback_reason') or ''}"
        )
    if event_type == "build_plan.execution.started":
        return clip(
            f"build {event_payload.get('action_id') or ''} started; {event_payload.get('step_count', 0)} step(s)"
        )
    if event_type == "build_plan.execution.completed":
        return clip(
            f"build {event_payload.get('action_id') or ''} completed: {event_payload.get('result') or ''}"
        )
    if event_type == "state.sample":
        return format_position(event_payload)
    if event_type == "error":
        return clip(
            f"{event_payload.get('class') or 'error'}: {event_payload.get('text') or event_payload.get('message') or ''}"
        )
    if event_type == "lifecycle":
        return clip(event_payload.get("text") or event_payload.get("status") or "lifecycle")
    if event_type == "behavior.event":
        kind = event_payload.get("kind") or "behavior"
        return clip(f"{kind}: {event_payload.get('text') or ''}")
    if event_type.startswith("bridge."):
        bridge = event_payload.get("bridge") if isinstance(event_payload.get("bridge"), dict) else {}
        return clip(
            f"{event_type} {bridge.get('phase') or ''} ok={bridge.get('ok') or ''}"
        )
    return clip(event_payload)


def latest_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_type") == event_type:
            return event
    return None


def count_consecutive(items: list[Any], predicate) -> int:  # type: ignore[no-untyped-def]
    count = 0
    for item in reversed(items):
        if not predicate(item):
            break
        count += 1
    return count


def warning(code: str, label: str, detail: str) -> dict[str, str]:
    return {"code": code, "label": label, "detail": detail}


def build_llm_feed(events: list[dict[str, Any]], feed_limit: int) -> list[dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    responses: dict[str, dict[str, Any]] = {}
    actions_by_trace: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        event_type = str(event.get("event_type") or "")
        agent = event_agent(event) or "unknown"
        key = f"{agent}:{event.get('trace_id') or event.get('event_id') or event_sort_key(event)}"
        if event_type in {"action.intent", "action.start", "action.result"} and event.get(
            "trace_id"
        ):
            actions_by_trace[key].append(event)
        if not event_type.startswith("llm."):
            continue
        if event_type == "llm.request":
            requests[key] = event
        elif event_type == "llm.response":
            responses[key] = event

    keys = set(requests) | set(responses)
    rows: list[dict[str, Any]] = []
    for key in keys:
        request = requests.get(key)
        response = responses.get(key)
        source = response or request
        if source is None:
            continue
        request_payload = payload(request or {})
        response_payload = payload(response or {})
        source_payload = payload(source)
        ts = event_ts(source)
        linked_actions = actions_by_trace.get(key, [])
        latest_intent = latest_event(linked_actions, "action.intent")
        latest_result = latest_event(linked_actions, "action.result")
        effect_parts: list[str] = []
        if latest_intent:
            effect_parts.append(command_signature(latest_intent) or event_summary(latest_intent))
        if latest_result:
            effect_parts.append(event_summary(latest_result))
        elif latest_intent:
            effect_parts.append("pending")
        rows.append(
            {
                "ts": isoformat_z(ts) if ts else "",
                "agent": display_agent(event_agent(source)),
                "model": str(
                    response_payload.get("model") or request_payload.get("model") or "unknown"
                ),
                "purpose": str(
                    request_payload.get("purpose")
                    or request_payload.get("reason")
                    or response_payload.get("purpose")
                    or response_payload.get("reason")
                    or "request"
                ),
                "latency_ms": response_payload.get("latency_ms"),
                "tokens": int(
                    response_payload.get("total_tokens")
                    or source_payload.get("total_tokens")
                    or request_payload.get("prompt_tokens")
                    or 0
                ),
                "outcome": str(
                    response_payload.get("outcome") or request_payload.get("outcome") or "started"
                ),
                "output": clip(
                    response_payload.get("response_text")
                    or response_payload.get("completion")
                    or response_payload.get("output")
                    or "",
                    limit=260,
                ),
                "effect": clip(" -> ".join(effect_parts), limit=260),
                "category": "llm",
            }
        )
    return sorted(rows, key=lambda row: row.get("ts") or "", reverse=True)[:feed_limit]


def command_count(event: dict[str, Any]) -> int:
    commands = payload(event).get("commands")
    if isinstance(commands, list):
        return len([command for command in commands if command_text(command)])
    if isinstance(commands, str) and commands.strip():
        return 1
    return 0


def plan_block_count(plan: Any) -> int:
    if not isinstance(plan, dict):
        return 0
    blocks = plan.get("blocks")
    return len(blocks) if isinstance(blocks, list) else 0


def first_int(*values: Any) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def verified_blocks_from_payload(event_payload: dict[str, Any]) -> int:
    metric = event_payload.get("metric")
    if isinstance(metric, dict):
        parsed = first_int(metric.get("steps_verified"), metric.get("blocks_present"))
        if parsed is not None:
            return parsed
    parsed = first_int(event_payload.get("verified_blocks"), event_payload.get("blocks_verified"))
    if parsed is not None:
        return parsed
    result = str(event_payload.get("result") or event_payload.get("detail") or "")
    match = re.search(r"\bverified=(?P<count>\d+)\b", result)
    if match:
        return int(match.group("count"))
    return 0


def is_dedupe_plan_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    event_payload = payload(event)
    text = " ".join(
        str(event_payload.get(key) or "")
        for key in ("reason", "error", "status", "source", "detail")
    ).lower()
    return (
        event_type.endswith(".skipped")
        or "dedupe" in text
        or "duplicate" in text
        or "cache" in text
        or bool(event_payload.get("deduped"))
        or bool(event_payload.get("cache_hit"))
    )


def build_pipeline_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    llm_responses = [event for event in events if event.get("event_type") == "llm.response"]
    llm_queue_events = [
        event for event in events if str(event.get("event_type") or "").startswith("llm.queue.")
    ]
    action_intents = [event for event in events if event.get("event_type") == "action.intent"]
    action_results = [event for event in events if event.get("event_type") == "action.result"]
    action_queue_events = [
        event
        for event in events
        if event.get("event_type")
        in {"action.queued", "action.started", "action.completed", "action.rejected_busy"}
    ]
    inbox_events = [
        event for event in events if str(event.get("event_type") or "").startswith("inbox.")
    ]
    discarded_responses = [
        event
        for event in llm_responses
        if str(payload(event).get("outcome") or "") == "discarded_stale"
    ]
    outcome_classes: dict[str, int] = defaultdict(int)
    for event in action_results:
        event_payload = payload(event)
        key = str(
            event_payload.get("outcome_class")
            or event_payload.get("outcome")
            or "unknown"
        )
        outcome_classes[key] += 1

    build_generation_completed = [
        event for event in events if event.get("event_type") == "build_plan.generation.completed"
    ]
    build_execution_completed = [
        event for event in events if event.get("event_type") == "build_plan.execution.completed"
    ]
    build_plan_ids = {
        str(payload(event).get("action_id") or event.get("trace_id") or "")
        for event in [*build_generation_completed, *build_execution_completed]
        if str(payload(event).get("action_id") or event.get("trace_id") or "")
    }
    builder_plan_intended_blocks = sum(
        plan_block_count(payload(event).get("plan")) for event in build_generation_completed
    )
    builder_plan_verified_blocks = sum(
        verified_blocks_from_payload(payload(event)) for event in build_execution_completed
    )
    builder_plan_completion_rate = (
        round(builder_plan_verified_blocks / builder_plan_intended_blocks, 4)
        if builder_plan_intended_blocks
        else (1.0 if not build_generation_completed else 0.0)
    )
    builder_paid_calls = 0
    builder_local_calls = 0
    builder_estimated_usd = 0.0
    builder_provider_counts: dict[str, int] = defaultdict(int)
    for event in build_generation_completed:
        event_payload = payload(event)
        provider = str(
            event_payload.get("builder_provider") or event_payload.get("provider") or "unknown"
        )
        builder_provider_counts[provider] += 1
        if event_payload.get("paid") or provider == "openrouter":
            builder_paid_calls += 1
        else:
            builder_local_calls += 1
        builder_estimated_usd += payload_float(event, "estimated_usd")
    builder_provider_failures = [
        event
        for event in events
        if event.get("event_type")
        in {"build_plan.generation.provider_failed", "build_plan.generation.budget_capped"}
    ]
    builder_skipped_events = [
        event for event in events if event.get("event_type") == "build_plan.generation.skipped"
    ]
    builder_skip_reasons: dict[str, int] = defaultdict(int)
    for event in builder_skipped_events:
        builder_skip_reasons[str(payload(event).get("reason") or "unknown")] += 1

    accepted_commands = sum(command_count(event) for event in action_intents)
    executed_actions = len(action_results)
    verified_actions = sum(1 for event in action_results if payload(event).get("verified"))
    llm_waits = [
        payload_int(event, "wait_ms")
        for event in llm_queue_events
        if event.get("event_type") in {"llm.queue.started", "llm.queue.completed", "llm.queue.failed"}
    ]
    latest_lm_queue = llm_queue_events[-1] if llm_queue_events else {}
    action_depths = [
        max(payload_int(event, "queue_depth"), payload_int(event, "remaining_depth"))
        for event in action_queue_events
    ]
    inbox_depths = [
        max(payload_int(event, "queue_depth"), payload_int(event, "remaining_depth"))
        for event in inbox_events
    ]
    return {
        "llm_requests": sum(1 for event in events if event.get("event_type") == "llm.request"),
        "llm_responses": len(llm_responses),
        "llm_queue_enqueued": sum(
            1 for event in events if event.get("event_type") == "llm.queue.enqueued"
        ),
        "llm_queue_running": payload_int(latest_lm_queue, "running"),
        "llm_queue_completed": sum(
            1 for event in events if event.get("event_type") == "llm.queue.completed"
        ),
        "llm_queue_failed": sum(
            1 for event in events if event.get("event_type") == "llm.queue.failed"
        ),
        "llm_queue_wait_ms_max": max(llm_waits or [0]),
        "discarded_stale_responses": len(discarded_responses),
        "discarded_commands": sum(
            int(payload(event).get("discarded_commands") or 0)
            for event in discarded_responses
        ),
        "inbox_queued_messages": sum(
            1 for event in events if event.get("event_type") == "inbox.queued"
        ),
        "inbox_turns": sum(
            1 for event in events if event.get("event_type") == "inbox.turn_completed"
        ),
        "inbox_queue_depth_max": max(inbox_depths or [0]),
        "accepted_commands": accepted_commands,
        "executed_actions": executed_actions,
        "verified_actions": verified_actions,
        "actions_queued": sum(
            1 for event in events if event.get("event_type") == "action.queued"
        ),
        "actions_rejected_busy": sum(
            1 for event in events if event.get("event_type") == "action.rejected_busy"
        ),
        "action_queue_depth_max": max(action_depths or [0]),
        "build_plans_generated": sum(
            1 for event in events if event.get("event_type") == "build_plan.generation.completed"
        ),
        "build_plans_rejected": sum(
            1 for event in events if event.get("event_type") == "build_plan.generation.rejected"
        ),
        "build_plans_executed": sum(
            1 for event in events if event.get("event_type") == "build_plan.execution.completed"
        ),
        "builder_plan_generated": len(build_generation_completed),
        "builder_plan_unique": len(build_plan_ids),
        "builder_plan_skipped_dedupe": sum(
            1
            for event in events
            if str(event.get("event_type") or "").startswith("build_plan.generation.")
            and is_dedupe_plan_event(event)
        ),
        "builder_plan_intended_blocks": builder_plan_intended_blocks,
        "builder_plan_verified_blocks": builder_plan_verified_blocks,
        "builder_plan_completion_rate": builder_plan_completion_rate,
        "builder_paid_calls": builder_paid_calls,
        "builder_local_calls": builder_local_calls,
        "builder_estimated_usd": round(builder_estimated_usd, 8),
        "builder_provider_failures": len(builder_provider_failures),
        "builder_provider_breakdown": dict(sorted(builder_provider_counts.items())),
        "builder_plan_skipped_active": builder_skip_reasons.get("active_build_exists", 0),
        "builder_plan_skipped_cooldown": builder_skip_reasons.get("cooldown", 0),
        "builder_plan_skipped_per_agent_cap": builder_skip_reasons.get("per_agent_cap", 0),
        "builder_plan_cache_hits": sum(
            1
            for event in builder_skipped_events
            if str(payload(event).get("reason") or "") == "cache_hit"
            or payload(event).get("cache_hit")
        ),
        "execution_rate": round(executed_actions / accepted_commands, 4)
        if accepted_commands
        else 1.0,
        "verified_rate": round(verified_actions / executed_actions, 4)
        if executed_actions
        else 1.0,
        "outcome_classes": dict(sorted(outcome_classes.items())),
    }


def row_from_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("event_type") or "unknown")
    ts = event_ts(event)
    return {
        "ts": isoformat_z(ts) if ts else "",
        "agent": display_agent(event_agent(event)),
        "event_type": event_type,
        "category": event_category(event_type),
        "summary": event_summary(event),
    }


def build_monitor_model(
    run_dir: Path,
    events: list[dict[str, Any]],
    totals: dict[str, Any] | None = None,
    metadata: dict[str, str] | None = None,
    *,
    now: datetime | None = None,
    thresholds: WarningThresholds | None = None,
    feed_limit: int = DEFAULT_FEED_LIMIT,
) -> dict[str, Any]:
    totals = totals or {}
    metadata = metadata or {}
    thresholds = thresholds or thresholds_from_env()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    sorted_events = sorted(events, key=event_sort_key)

    summary_fields = parse_summary_fields(run_dir / "summary.txt")
    start = parse_iso_ts(metadata.get("start_utc") or summary_fields.get("start_utc"))
    planned_end = parse_iso_ts(metadata.get("planned_end_utc"))
    actual_end = parse_iso_ts(metadata.get("end_utc") or summary_fields.get("end_utc"))
    planned_seconds = parse_duration_seconds({**summary_fields, **metadata}, start, planned_end)
    reference_time = actual_end or now
    elapsed_seconds = int((reference_time - start).total_seconds()) if start else None

    tokens_by_agent = {
        str(agent).lower(): token_bucket(bucket)
        for agent, bucket in (
            totals.get("tokens_by_agent") if isinstance(totals.get("tokens_by_agent"), dict) else {}
        ).items()
    }
    event_tokens_by_agent = tokens_from_events(sorted_events)
    for agent, bucket in event_tokens_by_agent.items():
        if bucket["total_tokens"] > tokens_by_agent.get(agent, {}).get("total_tokens", -1):
            tokens_by_agent[agent] = bucket

    metadata_agents = [
        item.strip().lower()
        for item in (metadata.get("cost_agents") or metadata.get("bots") or "").split()
        if item.strip()
    ]
    agents = sorted(
        {
            *(agent for agent in metadata_agents if agent != "bridge"),
            *(agent for agent in (event_agent(event) for event in sorted_events) if agent),
            *(agent for agent in tokens_by_agent if agent and agent != "unknown"),
        }
    )

    per_agent_events: dict[str, list[dict[str, Any]]] = {agent: [] for agent in agents}
    for event in sorted_events:
        agent = event_agent(event)
        if agent:
            per_agent_events.setdefault(agent, []).append(event)
    agents = sorted(per_agent_events)

    cards: list[dict[str, Any]] = []
    total_warnings = 0
    for agent in agents:
        agent_events = per_agent_events[agent]
        last_activity: datetime | None = None
        last_llm: datetime | None = None
        latest_chat = latest_event(agent_events, "chat.public")
        latest_state = latest_event(agent_events, "state.sample")
        latest_result = latest_event(agent_events, "action.result")
        latest_intent = latest_event(agent_events, "action.intent")
        latest_action = latest_result or latest_intent
        latest_inbox_event = next(
            (
                event
                for event in reversed(agent_events)
                if str(event.get("event_type") or "").startswith("inbox.")
            ),
            None,
        )
        latest_build_event = next(
            (
                event
                for event in reversed(agent_events)
                if str(event.get("event_type") or "").startswith("build_plan.")
            ),
            None,
        )
        latest_llm_event: dict[str, Any] | None = None
        restart_events: list[dict[str, Any]] = []
        error_count = 0
        llm_responses: list[dict[str, Any]] = []
        action_intents: list[dict[str, Any]] = []
        action_results: list[dict[str, Any]] = []
        discarded_command_count = 0
        interrupted_count = 0
        undefined_count = 0
        verified_count = 0
        inbox_queued_count = 0
        inbox_depth_latest = 0
        action_queued_count = 0
        action_rejected_count = 0
        action_depth_latest = 0
        build_plan_count = 0
        build_plan_ids: set[str] = set()
        build_plan_intended_blocks = 0
        build_plan_verified_blocks = 0
        build_plan_skipped_dedupe = 0
        builder_paid_calls = 0
        builder_local_calls = 0
        builder_estimated_usd = 0.0
        builder_provider_counts: dict[str, int] = defaultdict(int)
        builder_failure_count = 0
        builder_fallback_count = 0
        builder_last_fallback_reason = ""
        builder_skipped_active = 0
        builder_skipped_cooldown = 0
        builder_skipped_per_agent_cap = 0
        builder_cache_hits = 0
        builder_cooldown_remaining_sec = 0
        build_active_state: dict[str, Any] | None = None

        for event in agent_events:
            event_type = str(event.get("event_type") or "")
            ts = event_ts(event)
            event_payload = payload(event)
            if event_type in ACTIVE_EVENT_TYPES and ts:
                last_activity = ts
            if event_type in {"llm.request", "llm.response"} and ts:
                last_llm = ts
                latest_llm_event = event
            if event_type == "llm.response":
                llm_responses.append(event)
                if str(event_payload.get("outcome") or "") == "discarded_stale":
                    discarded_command_count += int(event_payload.get("discarded_commands") or 0)
            elif event_type == "action.intent":
                action_intents.append(event)
            elif event_type == "action.result":
                action_results.append(event)
                outcome_class = str(event_payload.get("outcome_class") or "")
                if event_payload.get("verified"):
                    verified_count += 1
                if outcome_class == "interrupted":
                    interrupted_count += 1
                if outcome_class == "undefined_result":
                    undefined_count += 1
            elif event_type == "inbox.queued":
                inbox_queued_count += 1
            elif event_type == "action.queued":
                action_queued_count += 1
            elif event_type == "action.rejected_busy":
                action_rejected_count += 1
            elif event_type in {"build_plan.generation.started", "build_plan.execution.started"}:
                if isinstance(event_payload.get("active_build"), dict):
                    build_active_state = event_payload["active_build"]
            elif event_type == "build_plan.generation.completed":
                build_plan_count += 1
                if isinstance(event_payload.get("active_build"), dict):
                    build_active_state = event_payload["active_build"]
                plan_id = str(event_payload.get("action_id") or event.get("trace_id") or "")
                if plan_id:
                    build_plan_ids.add(plan_id)
                build_plan_intended_blocks += plan_block_count(event_payload.get("plan"))
                provider = str(
                    event_payload.get("builder_provider")
                    or event_payload.get("provider")
                    or "unknown"
                )
                builder_provider_counts[provider] += 1
                if event_payload.get("paid") or provider == "openrouter":
                    builder_paid_calls += 1
                else:
                    builder_local_calls += 1
                builder_estimated_usd += payload_float(event, "estimated_usd")
                if event_payload.get("fallback_reason"):
                    builder_fallback_count += 1
                    builder_last_fallback_reason = str(event_payload.get("fallback_reason"))
            elif event_type in {"build_plan.generation.rejected", "build_plan.generation.skipped"}:
                if is_dedupe_plan_event(event):
                    build_plan_skipped_dedupe += 1
                if event_type == "build_plan.generation.skipped":
                    reason = str(event_payload.get("reason") or "")
                    if reason == "active_build_exists":
                        builder_skipped_active += 1
                    elif reason == "cooldown":
                        builder_skipped_cooldown += 1
                    elif reason == "per_agent_cap":
                        builder_skipped_per_agent_cap += 1
                    if reason == "cache_hit" or event_payload.get("cache_hit"):
                        builder_cache_hits += 1
                    builder_cooldown_remaining_sec = max(
                        builder_cooldown_remaining_sec,
                        payload_int(event, "cooldown_remaining_sec"),
                    )
                    if isinstance(event_payload.get("active_build"), dict):
                        build_active_state = event_payload["active_build"]
            elif event_type in {
                "build_plan.generation.provider_failed",
                "build_plan.generation.budget_capped",
            }:
                builder_failure_count += 1
                if event_payload.get("fallback_reason"):
                    builder_fallback_count += 1
                    builder_last_fallback_reason = str(event_payload.get("fallback_reason"))
            elif event_type == "build_plan.execution.completed":
                if isinstance(event_payload.get("active_build"), dict):
                    build_active_state = event_payload["active_build"]
                elif event_payload.get("status") == "completed":
                    build_active_state = {
                        "plan_id": event_payload.get("plan_id") or event_payload.get("action_id"),
                        "status": "completed",
                    }
                builder_cooldown_remaining_sec = max(
                    builder_cooldown_remaining_sec,
                    payload_int(event, "cooldown_remaining_sec"),
                )
                plan_id = str(event_payload.get("action_id") or event.get("trace_id") or "")
                if plan_id:
                    build_plan_ids.add(plan_id)
                build_plan_verified_blocks += verified_blocks_from_payload(event_payload)
            elif event_type == "error":
                error_count += 1
            if event_type.startswith("inbox."):
                inbox_depth_latest = max(
                    payload_int(event, "queue_depth"),
                    payload_int(event, "remaining_depth"),
                )
            if event_type in {"action.queued", "action.started", "action.completed", "action.rejected_busy"}:
                action_depth_latest = max(
                    payload_int(event, "queue_depth"),
                    payload_int(event, "remaining_depth"),
                )
            if is_restart_lifecycle(event):
                restart_events.append(event)

        idle_seconds: int | None = None
        if last_activity:
            idle_seconds = int((reference_time - last_activity).total_seconds())
        elif start:
            idle_seconds = int((reference_time - start).total_seconds())

        agent_warnings: list[dict[str, str]] = []
        if idle_seconds is not None and idle_seconds > thresholds.stall_seconds:
            agent_warnings.append(
                warning(
                    "stalled",
                    "Stalled",
                    f"No chat, action, or LLM activity for {human_duration(idle_seconds)}",
                )
            )

        blank_count = count_consecutive(llm_responses, is_blank_llm_response)
        if blank_count >= thresholds.repeated_blank_count:
            agent_warnings.append(
                warning(
                    "repeated_blank_response",
                    "Blank responses",
                    f"{blank_count} consecutive blank LLM responses",
                )
            )

        signatures = [
            signature
            for signature in (command_signature(event) for event in action_intents)
            if signature
        ]
        repeated_command_count = 0
        if signatures:
            last_signature = signatures[-1]
            for signature in reversed(signatures):
                if signature != last_signature:
                    break
                repeated_command_count += 1
        if repeated_command_count >= thresholds.repeated_command_count:
            agent_warnings.append(
                warning(
                    "repeated_command",
                    "Repeated command",
                    f"{repeated_command_count} consecutive {clip(signatures[-1], 80)} intents",
                )
            )

        recent_restart = any(
            event_ts(event)
            and (reference_time - event_ts(event)).total_seconds()
            <= thresholds.restart_recent_seconds
            for event in restart_events
        )
        if restart_events:
            label = "Crash/restart" if not recent_restart else "Recent restart"
            detail = f"{len(restart_events)} lifecycle disconnect/restart event(s)"
            agent_warnings.append(warning("crash_restart", label, detail))

        if undefined_count:
            agent_warnings.append(
                warning(
                    "undefined_action_result",
                    "Undefined result",
                    f"{undefined_count} action execution(s) returned undefined",
                )
            )

        if interrupted_count >= thresholds.stuck_loop_count:
            agent_warnings.append(
                warning(
                    "interrupted_actions",
                    "Interrupted actions",
                    f"{interrupted_count} interrupted action result(s)",
                )
            )

        stuck_count = count_consecutive(action_results, is_stuck_action_result)
        if stuck_count >= thresholds.stuck_loop_count:
            agent_warnings.append(
                warning(
                    "stuck_loop",
                    "Stuck loop",
                    f"{stuck_count} consecutive blocked or unreachable action results",
                )
            )

        if last_llm is None:
            if (
                start
                and elapsed_seconds is not None
                and elapsed_seconds > thresholds.llm_idle_seconds
            ):
                agent_warnings.append(
                    warning("no_recent_llm", "No recent LLM", "No LLM request or response seen")
                )
        elif (reference_time - last_llm).total_seconds() > thresholds.llm_idle_seconds:
            agent_warnings.append(
                warning(
                    "no_recent_llm",
                    "No recent LLM",
                    f"Last LLM activity {human_duration((reference_time - last_llm).total_seconds())} ago",
                )
            )

        total_warnings += len(agent_warnings)
        token_totals = tokens_by_agent.get(
            agent,
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

        cards.append(
            {
                "agent": agent,
                "name": display_agent(agent),
                "status": "warn" if agent_warnings else "ok",
                "warnings": agent_warnings,
                "latest_chat": row_from_event(latest_chat) if latest_chat else None,
                "latest_action": row_from_event(latest_action) if latest_action else None,
                "latest_llm": row_from_event(latest_llm_event) if latest_llm_event else None,
                "latest_inbox": row_from_event(latest_inbox_event) if latest_inbox_event else None,
                "latest_build": row_from_event(latest_build_event) if latest_build_event else None,
                "current_state": row_from_event(latest_state) if latest_state else None,
                "idle_seconds": idle_seconds,
                "idle": human_duration(idle_seconds),
                "restart_count": len(restart_events),
                "error_count": error_count,
                "discarded_commands": discarded_command_count,
                "interrupted_count": interrupted_count,
                "undefined_count": undefined_count,
                "verified_count": verified_count,
                "executed_count": len(action_results),
                "inbox_queued_count": inbox_queued_count,
                "inbox_depth_latest": inbox_depth_latest,
                "action_queued_count": action_queued_count,
                "action_rejected_count": action_rejected_count,
                "action_depth_latest": action_depth_latest,
                "build_plan_count": build_plan_count,
                "build_plan_unique": len(build_plan_ids),
                "build_plan_skipped_dedupe": build_plan_skipped_dedupe,
                "build_plan_intended_blocks": build_plan_intended_blocks,
                "build_plan_verified_blocks": build_plan_verified_blocks,
                "build_plan_completion_rate": (
                    round(build_plan_verified_blocks / build_plan_intended_blocks, 4)
                    if build_plan_intended_blocks
                    else (1.0 if build_plan_count == 0 else 0.0)
                ),
                "builder_paid_calls": builder_paid_calls,
                "builder_local_calls": builder_local_calls,
                "builder_estimated_usd": round(builder_estimated_usd, 8),
                "builder_provider_breakdown": dict(sorted(builder_provider_counts.items())),
                "builder_failure_count": builder_failure_count,
                "builder_fallback_count": builder_fallback_count,
                "builder_last_fallback_reason": builder_last_fallback_reason,
                "builder_skipped_active": builder_skipped_active,
                "builder_skipped_cooldown": builder_skipped_cooldown,
                "builder_skipped_per_agent_cap": builder_skipped_per_agent_cap,
                "builder_cache_hits": builder_cache_hits,
                "builder_cooldown_remaining_sec": builder_cooldown_remaining_sec,
                "active_build": build_active_state,
                "tokens": token_totals,
            }
        )

    all_rows = [row_from_event(event) for event in sorted_events]
    chat_feed = [row for row in all_rows if row["event_type"] == "chat.public"][-feed_limit:]
    action_feed = [row for row in all_rows if row["category"] == "action"][-feed_limit:]
    queue_feed = [
        row
        for row in all_rows
        if row["category"] == "inbox"
        or row["event_type"].startswith("llm.queue.")
        or row["event_type"] in {"action.queued", "action.rejected_busy"}
    ][-feed_limit:]
    build_feed = [row for row in all_rows if row["category"] == "build"][-feed_limit:]
    timeline_feed = all_rows[-feed_limit:]

    status = "completed" if actual_end else "in progress"
    if not actual_end and planned_end and now > planned_end:
        status = "past planned end"

    return {
        "run": {
            "run_dir": str(run_dir),
            "status": status,
            "generated_at_utc": isoformat_z(now),
            "start_utc": isoformat_z(start) if start else "",
            "planned_end_utc": isoformat_z(planned_end) if planned_end else "",
            "end_utc": isoformat_z(actual_end) if actual_end else "",
            "elapsed": human_duration(elapsed_seconds),
            "planned": human_duration(planned_seconds),
            "event_count": len(sorted_events),
            "agent_count": len(cards),
            "warning_count": total_warnings,
        },
        "pipeline": build_pipeline_summary(sorted_events),
        "thresholds": thresholds.__dict__,
        "agents": cards,
        "feeds": {
            "chat": list(reversed(chat_feed)),
            "action": list(reversed(action_feed)),
            "llm": build_llm_feed(sorted_events, feed_limit),
            "queue": list(reversed(queue_feed)),
            "build": list(reversed(build_feed)),
            "timeline": list(reversed(timeline_feed)),
        },
    }


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_badges(warnings: list[dict[str, str]]) -> str:
    if not warnings:
        return '<span class="badge badge-ok">Clear</span>'
    return "".join(
        f'<span class="badge badge-warn" data-warning="{esc(item["code"])}" title="{esc(item["detail"])}">{esc(item["label"])}</span>'
        for item in warnings
    )


def render_card_line(label: str, item: dict[str, Any] | None, empty: str) -> str:
    value = item["summary"] if item else empty
    return f'<div class="card-line"><dt>{esc(label)}</dt><dd>{esc(value)}</dd></div>'


def render_builder_route(agent: dict[str, Any]) -> str:
    providers = agent.get("builder_provider_breakdown") or {}
    if providers:
        provider_text = ", ".join(f"{key}:{value}" for key, value in providers.items())
    else:
        provider_text = "none"
    parts = [
        f"providers {provider_text}",
        f"paid {agent.get('builder_paid_calls', 0)}",
        f"local {agent.get('builder_local_calls', 0)}",
        f"usd {agent.get('builder_estimated_usd', 0)}",
    ]
    if agent.get("builder_last_fallback_reason"):
        parts.append(f"fallback {agent['builder_last_fallback_reason']}")
    return f'<div class="card-line"><dt>Builder route</dt><dd>{esc("; ".join(parts))}</dd></div>'


def render_active_build(agent: dict[str, Any]) -> str:
    active = agent.get("active_build") if isinstance(agent.get("active_build"), dict) else {}
    if active:
        value = (
            f"{active.get('plan_id') or 'plan'} "
            f"{active.get('status') or 'active'}"
        ).strip()
    else:
        value = "No active build"
    cooldown = agent.get("builder_cooldown_remaining_sec") or 0
    if cooldown:
        value = f"{value}; cooldown {cooldown}s"
    return f'<div class="card-line"><dt>Active build</dt><dd>{esc(value)}</dd></div>'


def render_agent_cards(agents: list[dict[str, Any]]) -> str:
    if not agents:
        return '<p class="empty">No agent events found in the timeline.</p>'
    cards: list[str] = []
    for agent in agents:
        tokens = agent["tokens"]
        cards.append(
            f"""
            <article class="agent-card status-{esc(agent["status"])}">
              <div class="agent-card-head">
                <h2>{esc(agent["name"])}</h2>
                <span class="status-pill">{esc(agent["status"])}</span>
              </div>
              <div class="badges">{render_badges(agent["warnings"])}</div>
              <dl>
                {render_card_line("Latest chat", agent["latest_chat"], "No public chat")}
                {render_card_line("Latest action", agent["latest_action"], "No action result")}
                {render_card_line("Latest LLM", agent["latest_llm"], "No LLM activity")}
                {render_card_line("Inbox", agent["latest_inbox"], "No inbox telemetry")}
                {render_card_line("Build plan", agent["latest_build"], "No build plan")}
                {render_active_build(agent)}
                {render_builder_route(agent)}
                {render_card_line("State", agent["current_state"], "No state sample")}
              </dl>
              <div class="metrics">
                <div><strong>{esc(agent["idle"])}</strong><span>idle</span></div>
                <div><strong>{agent["restart_count"]}</strong><span>restarts</span></div>
                <div><strong>{agent["error_count"]}</strong><span>errors</span></div>
                <div><strong>{tokens["total_tokens"]}</strong><span>tokens</span></div>
                <div><strong>{agent["executed_count"]}</strong><span>executed</span></div>
                <div><strong>{agent["verified_count"]}</strong><span>verified</span></div>
                <div><strong>{agent["interrupted_count"]}</strong><span>interrupted</span></div>
                <div><strong>{agent["discarded_commands"]}</strong><span>discarded</span></div>
                <div><strong>{agent["inbox_queued_count"]}</strong><span>inbox queued</span></div>
                <div><strong>{agent["inbox_depth_latest"]}</strong><span>inbox depth</span></div>
                <div><strong>{agent["action_queued_count"]}</strong><span>action queued</span></div>
                <div><strong>{agent["action_depth_latest"]}</strong><span>action depth</span></div>
                <div><strong>{agent["action_rejected_count"]}</strong><span>busy rejects</span></div>
                <div><strong>{agent["build_plan_count"]}</strong><span>plans</span></div>
                <div><strong>{agent["builder_paid_calls"]}</strong><span>paid builder</span></div>
                <div><strong>{agent["builder_local_calls"]}</strong><span>local builder</span></div>
                <div><strong>{agent["builder_failure_count"]}</strong><span>builder fails</span></div>
                <div><strong>{agent["builder_cache_hits"]}</strong><span>cache hits</span></div>
                <div><strong>{agent["builder_skipped_active"]}</strong><span>active skips</span></div>
                <div><strong>{agent["builder_skipped_cooldown"]}</strong><span>cooldowns</span></div>
                <div><strong>{agent["build_plan_intended_blocks"]}</strong><span>intended blocks</span></div>
                <div><strong>{agent["build_plan_verified_blocks"]}</strong><span>verified blocks</span></div>
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def render_pipeline(pipeline: dict[str, Any]) -> str:
    labels = [
        ("llm_requests", "LLM requests"),
        ("llm_responses", "LLM responses"),
        ("llm_queue_enqueued", "LLM queued"),
        ("llm_queue_running", "LLM running"),
        ("llm_queue_completed", "LLM queue done"),
        ("llm_queue_failed", "LLM queue failed"),
        ("llm_queue_wait_ms_max", "Max LLM wait ms"),
        ("discarded_stale_responses", "Discarded stale"),
        ("discarded_commands", "Discarded commands"),
        ("inbox_queued_messages", "Inbox queued"),
        ("inbox_turns", "Inbox turns"),
        ("inbox_queue_depth_max", "Max inbox depth"),
        ("accepted_commands", "Accepted commands"),
        ("executed_actions", "Executed actions"),
        ("verified_actions", "Verified actions"),
        ("actions_queued", "Actions queued"),
        ("actions_rejected_busy", "Busy rejects"),
        ("action_queue_depth_max", "Max action depth"),
        ("build_plans_generated", "Plans generated"),
        ("build_plans_rejected", "Plans rejected"),
        ("build_plans_executed", "Plans executed"),
        ("builder_plan_unique", "Unique plans"),
        ("builder_plan_skipped_dedupe", "Plan skips"),
        ("builder_plan_intended_blocks", "Intended blocks"),
        ("builder_plan_verified_blocks", "Verified blocks"),
        ("builder_plan_completion_rate", "Plan completion"),
        ("builder_paid_calls", "Paid builder"),
        ("builder_local_calls", "Local builder"),
        ("builder_estimated_usd", "Builder USD"),
        ("builder_provider_failures", "Builder failures"),
        ("builder_plan_cache_hits", "Cache hits"),
        ("builder_plan_skipped_active", "Active skips"),
        ("builder_plan_skipped_cooldown", "Cooldown skips"),
        ("builder_plan_skipped_per_agent_cap", "Cap skips"),
        ("execution_rate", "Execution rate"),
        ("verified_rate", "Verified rate"),
    ]
    return "\n".join(
        f'<div><strong>{esc(pipeline.get(key))}</strong><span>{esc(label)}</span></div>'
        for key, label in labels
    )


def render_feed_rows(
    rows: list[dict[str, Any]], *, columns: tuple[str, ...] = ("ts", "agent", "summary")
) -> str:
    if not rows:
        return '<tr><td class="empty-row" colspan="4">No events</td></tr>'
    html_rows: list[str] = []
    for row in rows:
        category = row.get("category") or "lifecycle"
        if columns == (
            "ts",
            "agent",
            "model",
            "purpose",
            "latency_ms",
            "tokens",
            "outcome",
            "output",
            "effect",
        ):
            latency = "" if row.get("latency_ms") in (None, "") else f"{row.get('latency_ms')}ms"
            html_rows.append(
                f"""
                <tr data-category="{esc(category)}">
                  <td>{esc(row.get("ts"))}</td>
                  <td>{esc(row.get("agent"))}</td>
                  <td>{esc(row.get("model"))}</td>
                  <td>{esc(row.get("purpose"))}</td>
                  <td>{esc(latency)}</td>
                  <td>{esc(row.get("tokens"))}</td>
                  <td>{esc(row.get("outcome"))}</td>
                  <td>{esc(row.get("output"))}</td>
                  <td>{esc(row.get("effect"))}</td>
                </tr>
                """
            )
        elif columns == ("ts", "category", "agent", "event_type", "summary"):
            html_rows.append(
                f"""
                <tr data-category="{esc(category)}">
                  <td>{esc(row.get("ts"))}</td>
                  <td><span class="category-tag">{esc(category)}</span></td>
                  <td>{esc(row.get("agent"))}</td>
                  <td>{esc(row.get("event_type"))}</td>
                  <td>{esc(row.get("summary"))}</td>
                </tr>
                """
            )
        else:
            html_rows.append(
                f"""
                <tr data-category="{esc(category)}">
                  <td>{esc(row.get("ts"))}</td>
                  <td>{esc(row.get("agent"))}</td>
                  <td>{esc(row.get("summary"))}</td>
                </tr>
                """
            )
    return "\n".join(html_rows)


def render_monitor_html(model: dict[str, Any]) -> str:
    run = model["run"]
    data_blob = json.dumps(model, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Minecraft Cohort Monitor</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1d2430;
      --muted: #617085;
      --line: #d7dde6;
      --ok: #1b7f4c;
      --warn: #b04700;
      --warn-bg: #fff0df;
      --ok-bg: #e8f6ef;
      --accent: #255ea8;
      --accent-bg: #e8f0fb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.45;
    }}
    header {{
      padding: 24px clamp(16px, 4vw, 44px) 18px;
      background: #172033;
      color: #ffffff;
    }}
    h1, h2, h3 {{ margin: 0; letter-spacing: 0; }}
    h1 {{ font-size: clamp(28px, 4vw, 42px); font-weight: 760; }}
    h2 {{ font-size: 20px; }}
    h3 {{ font-size: 17px; }}
    main {{ padding: 22px clamp(16px, 4vw, 44px) 44px; }}
    .run-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
      color: #d9e3f4;
    }}
    .run-meta span, .filterbar label, .badge, .status-pill, .category-tag {{
      border-radius: 999px;
      padding: 5px 9px;
      white-space: nowrap;
    }}
    .run-meta span {{ background: rgba(255,255,255,.12); }}
    .run-path {{ margin-top: 12px; color: #c8d4e5; word-break: break-all; }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin: 26px 0 12px;
    }}
    .agent-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }}
    .agent-card, .feed-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(20, 31, 48, .05);
    }}
    .agent-card {{ padding: 16px; }}
    .status-warn {{ border-color: #e7b37f; }}
    .agent-card-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .status-pill {{ background: var(--accent-bg); color: var(--accent); font-weight: 700; text-transform: uppercase; font-size: 12px; }}
    .status-warn .status-pill {{ background: var(--warn-bg); color: var(--warn); }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; min-height: 27px; }}
    .badge {{ font-size: 12px; font-weight: 700; }}
    .badge-ok {{ background: var(--ok-bg); color: var(--ok); }}
    .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
    dl {{ margin: 0; }}
    .card-line {{
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 10px;
      padding: 7px 0;
      border-top: 1px solid #edf0f4;
    }}
    .card-line dt {{ color: var(--muted); }}
    .card-line dd {{ margin: 0; overflow-wrap: anywhere; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .pipeline-metrics {{
      margin-top: 0;
      padding: 14px;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    }}
    .metrics div {{
      background: #f3f5f8;
      border-radius: 7px;
      padding: 8px;
      min-width: 0;
    }}
    .metrics strong {{ display: block; font-size: 16px; overflow-wrap: anywhere; }}
    .metrics span {{ color: var(--muted); font-size: 12px; }}
    .filterbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 8px 0 14px;
    }}
    .filterbar label {{
      background: var(--panel);
      border: 1px solid var(--line);
      color: var(--text);
      cursor: pointer;
    }}
    .filterbar input {{ margin-right: 6px; }}
    .feed-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
      gap: 14px;
    }}
    .feed-panel {{ overflow: hidden; }}
    .feed-panel h3 {{ padding: 13px 14px; border-bottom: 1px solid var(--line); }}
    .table-scroll {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 520px;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 9px 12px;
      border-bottom: 1px solid #edf0f4;
    }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; background: #fafbfc; }}
    td {{ overflow-wrap: anywhere; }}
    .category-tag {{ background: #edf4ef; color: #286243; font-size: 12px; font-weight: 700; }}
    .timeline-panel {{ margin-top: 14px; }}
    .empty, .empty-row {{ color: var(--muted); }}
    [hidden] {{ display: none !important; }}
    @media (max-width: 640px) {{
      .card-line {{ grid-template-columns: 1fr; gap: 2px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      table {{ min-width: 620px; }}
    }}
  </style>
</head>
<body class="cohort-monitor">
  <header>
    <h1>Minecraft Cohort Monitor</h1>
    <div class="run-meta">
      <span>Status: {esc(run["status"])}</span>
      <span>Elapsed: {esc(run["elapsed"])}</span>
      <span>Planned: {esc(run["planned"])}</span>
      <span>Agents: {esc(run["agent_count"])}</span>
      <span>Events: {esc(run["event_count"])}</span>
      <span>Warnings: {esc(run["warning_count"])}</span>
      <span>Generated: {esc(run["generated_at_utc"])}</span>
    </div>
    <div class="run-path">{esc(run["run_dir"])}</div>
  </header>
  <main>
    <section>
      <div class="section-head"><h2>Action Pipeline</h2></div>
      <article class="feed-panel">
        <div class="metrics pipeline-metrics">
          {render_pipeline(model["pipeline"])}
        </div>
      </article>
    </section>

    <section>
      <div class="section-head"><h2>Agents</h2></div>
      <div class="agent-grid">
        {render_agent_cards(model["agents"])}
      </div>
    </section>

    <section>
      <div class="section-head"><h2>Feeds</h2></div>
      <div class="filterbar" aria-label="Timeline filters">
        <label><input type="checkbox" data-filter="chat" checked>Chat</label>
        <label><input type="checkbox" data-filter="llm" checked>LLM</label>
        <label><input type="checkbox" data-filter="inbox" checked>Inbox</label>
        <label><input type="checkbox" data-filter="action" checked>Action</label>
        <label><input type="checkbox" data-filter="build" checked>Build</label>
        <label><input type="checkbox" data-filter="movement" checked>Movement</label>
        <label><input type="checkbox" data-filter="error" checked>Error</label>
        <label><input type="checkbox" data-filter="lifecycle" checked>Lifecycle</label>
      </div>
      <div class="feed-grid">
        <article class="feed-panel">
          <h3>Public Chat</h3>
          <div class="table-scroll">
            <table>
              <thead><tr><th>Time</th><th>Agent</th><th>Message</th></tr></thead>
              <tbody>{render_feed_rows(model["feeds"]["chat"])}</tbody>
            </table>
          </div>
        </article>
        <article class="feed-panel">
          <h3>Actions</h3>
          <div class="table-scroll">
            <table>
              <thead><tr><th>Time</th><th>Agent</th><th>Result</th></tr></thead>
              <tbody>{render_feed_rows(model["feeds"]["action"])}</tbody>
            </table>
          </div>
        </article>
        <article class="feed-panel">
          <h3>Queues</h3>
          <div class="table-scroll">
            <table>
              <thead><tr><th>Time</th><th>Agent</th><th>Status</th></tr></thead>
              <tbody>{render_feed_rows(model["feeds"]["queue"])}</tbody>
            </table>
          </div>
        </article>
        <article class="feed-panel">
          <h3>Build Plans</h3>
          <div class="table-scroll">
            <table>
              <thead><tr><th>Time</th><th>Agent</th><th>Progress</th></tr></thead>
              <tbody>{render_feed_rows(model["feeds"]["build"])}</tbody>
            </table>
          </div>
        </article>
        <article class="feed-panel">
          <h3>LLM Requests</h3>
          <div class="table-scroll">
            <table>
              <thead><tr><th>Time</th><th>Agent</th><th>Model</th><th>Purpose</th><th>Latency</th><th>Tokens</th><th>Outcome</th><th>Output</th><th>Game effect</th></tr></thead>
              <tbody>{render_feed_rows(model["feeds"]["llm"], columns=("ts", "agent", "model", "purpose", "latency_ms", "tokens", "outcome", "output", "effect"))}</tbody>
            </table>
          </div>
        </article>
      </div>
      <article class="feed-panel timeline-panel">
        <h3>Filtered Timeline</h3>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Time</th><th>Kind</th><th>Agent</th><th>Event</th><th>Summary</th></tr></thead>
            <tbody>{render_feed_rows(model["feeds"]["timeline"], columns=("ts", "category", "agent", "event_type", "summary"))}</tbody>
          </table>
        </div>
      </article>
    </section>
  </main>
  <script id="data" type="application/json">{data_blob}</script>
  <script>
    (() => {{
      const boxes = Array.from(document.querySelectorAll("[data-filter]"));
      const apply = () => {{
        const active = new Set(boxes.filter((box) => box.checked).map((box) => box.dataset.filter));
        document.querySelectorAll("[data-category]").forEach((row) => {{
          row.hidden = !active.has(row.dataset.category);
        }});
      }};
      boxes.forEach((box) => box.addEventListener("change", apply));
      apply();
    }})();
  </script>
</body>
</html>
"""


def build(
    run_dir: Path,
    *,
    output: Path | None = None,
    now: datetime | None = None,
    thresholds: WarningThresholds | None = None,
    feed_limit: int = DEFAULT_FEED_LIMIT,
    rebuild_timeline: bool = False,
) -> Path:
    run_dir = run_dir.resolve()
    timeline_path, totals_path = ensure_timeline_artifacts(run_dir, rebuild=rebuild_timeline)
    events = read_ndjson(timeline_path)
    totals = load_json(totals_path)
    metadata = parse_metadata_env(run_dir / "metadata.env")
    model = build_monitor_model(
        run_dir,
        events,
        totals,
        metadata,
        now=now,
        thresholds=thresholds,
        feed_limit=max(1, feed_limit),
    )
    output_path = output or default_output_path(run_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_monitor_html(model), encoding="utf-8")
    return output_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a self-contained local HTML monitor for Minecraft soak timeline evidence."
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Soak evidence directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "HTML output path. Default: <run-dir>/monitor.html, except the committed "
            "test fixture renders to a temp file to avoid dirtying the repo."
        ),
    )
    parser.add_argument(
        "--feed-limit",
        type=int,
        default=parse_int_env("SOAK_MONITOR_FEED_LIMIT", DEFAULT_FEED_LIMIT),
        help=f"Maximum rows per feed. Default: {DEFAULT_FEED_LIMIT}",
    )
    parser.add_argument(
        "--rebuild-timeline",
        action="store_true",
        help="Rebuild timeline.ndjson from raw soak evidence before rendering.",
    )
    parser.add_argument(
        "--stall-seconds",
        type=int,
        default=None,
        help=f"Seconds without chat/action/LLM before the stalled badge. Default: {DEFAULT_STALL_SECONDS}",
    )
    parser.add_argument(
        "--llm-idle-seconds",
        type=int,
        default=None,
        help=f"Seconds without LLM activity before the no-recent-LLM badge. Default: {DEFAULT_LLM_IDLE_SECONDS}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    thresholds = thresholds_from_env()
    if args.stall_seconds is not None or args.llm_idle_seconds is not None:
        thresholds = WarningThresholds(
            stall_seconds=max(1, args.stall_seconds or thresholds.stall_seconds),
            repeated_blank_count=thresholds.repeated_blank_count,
            repeated_command_count=thresholds.repeated_command_count,
            restart_recent_seconds=thresholds.restart_recent_seconds,
            stuck_loop_count=thresholds.stuck_loop_count,
            llm_idle_seconds=max(1, args.llm_idle_seconds or thresholds.llm_idle_seconds),
        )
    try:
        output_path = build(
            args.run_dir,
            output=args.output,
            thresholds=thresholds,
            feed_limit=args.feed_limit,
            rebuild_timeline=args.rebuild_timeline,
        )
    except Exception as exc:
        print(f"monitor render failed: {exc}", file=sys.stderr)
        return 2
    print(f"ok monitor rendered {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

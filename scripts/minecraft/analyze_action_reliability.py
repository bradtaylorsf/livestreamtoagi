#!/usr/bin/env python3
"""Analyze Minecraft bot logs for intent-to-command reliability.

The analyzer is intentionally heuristic: Mindcraft logs are not a stable
machine contract, so this script looks for conservative action-command,
parser, execution, and verification markers in per-bot stdout/stderr logs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minecraft_log_patterns import (
    ACTION_CONTEXT_RE,
    COMMAND_RE,
    EXECUTION_FAILURE_RE,
    EXECUTION_SUCCESS_RE,
    INSTRUCTION_RE,
    INTENT_PROMISE_RE,
    INTENT_VERB_RE,
    PARSER_FAILURE_PATTERNS,
    UTTERANCE_RE,
    VERIFICATION_RE,
)
from bot_log_parser import ParsedExecution, parse_bot_log_file

DEFAULT_MIN_INTENT_TO_COMMAND = 0.6
DEFAULT_MIN_PARSE_SUCCESS = 0.8
DEFAULT_MIN_EXECUTION_RATE = 0.7
DEFAULT_MIN_VERIFIED_SUCCESS = 0.5
DEFAULT_MIN_INTENTS = 5
DEFAULT_TOP_N = 3


@dataclass
class Example:
    line: int
    text: str
    klass: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"line": self.line, "text": self.text}
        if self.klass:
            data["class"] = self.klass
        return data


@dataclass
class AgentStats:
    agent: str
    log_file: str
    intent_utterances: int = 0
    emitted_commands: int = 0
    generated_commands: int = 0
    discarded_commands: int = 0
    stale_generations: int = 0
    parser_failures: Counter[str] = field(default_factory=Counter)
    command_buckets: dict[str, Counter[str]] = field(default_factory=dict)
    execution_successes: int = 0
    execution_failures: int = 0
    execution_unknowns: int = 0
    verified_actions: int = 0
    execution_failure_classes: Counter[str] = field(default_factory=Counter)
    failed_parse_examples: list[Example] = field(default_factory=list)
    verified_success_examples: list[Example] = field(default_factory=list)
    intent_examples: list[Example] = field(default_factory=list)
    execution_failure_examples: list[Example] = field(default_factory=list)
    builder_plan_generated: int = 0
    builder_plan_unique_ids: set[str] = field(default_factory=set)
    builder_plan_skipped_dedupe: int = 0
    builder_plan_skipped_active: int = 0
    builder_plan_skipped_cooldown: int = 0
    builder_plan_skipped_per_agent_cap: int = 0
    builder_plan_cache_hits: int = 0
    builder_plan_max_per_agent: int = 0
    builder_plan_paid_calls: int = 0
    builder_plan_local_calls: int = 0
    builder_plan_estimated_usd: float = 0.0
    builder_plan_prompt_tokens: int = 0
    builder_plan_completion_tokens: int = 0
    builder_plan_total_tokens: int = 0
    builder_plan_failures: int = 0
    builder_plan_fallbacks: int = 0
    builder_plan_provider_counts: Counter[str] = field(default_factory=Counter)
    builder_plan_intended_blocks: int = 0
    builder_plan_verified_blocks: int = 0
    build_plan_event_keys: set[str] = field(default_factory=set, repr=False)

    @property
    def parse_failures(self) -> int:
        return sum(self.parser_failures.values())

    @property
    def intended_action_events(self) -> int:
        return max(self.intent_utterances, self.emitted_commands)

    @property
    def command_executions(self) -> int:
        return self.execution_successes + self.execution_failures + self.execution_unknowns

    @property
    def parse_successes(self) -> int:
        return max(0, self.emitted_commands - self.parse_failures)

    @property
    def builder_plan_unique(self) -> int:
        return len(self.builder_plan_unique_ids)

    @property
    def builder_plan_completion_rate(self) -> float:
        if self.builder_plan_intended_blocks <= 0:
            return 1.0 if self.builder_plan_generated == 0 else 0.0
        return round(self.builder_plan_verified_blocks / self.builder_plan_intended_blocks, 4)

    def metrics(self) -> dict[str, float]:
        if self.intent_utterances > 0:
            intent_to_command = min(1.0, self.emitted_commands / self.intent_utterances)
        elif self.emitted_commands > 0:
            intent_to_command = 1.0
        else:
            intent_to_command = 1.0

        parse_total = self.parse_successes + self.parse_failures
        if parse_total > 0:
            parse_success_rate = self.parse_successes / parse_total
        else:
            parse_success_rate = 0.0 if self.intended_action_events else 1.0

        if self.emitted_commands > 0:
            command_execution_rate = min(1.0, self.command_executions / self.emitted_commands)
        else:
            command_execution_rate = 0.0 if self.intended_action_events else 1.0

        if self.execution_successes > 0:
            verified_success_rate = self.verified_actions / self.execution_successes
        else:
            verified_success_rate = 0.0 if self.intended_action_events else 1.0

        return {
            "intent_to_command_ratio": round(intent_to_command, 4),
            "parse_success_rate": round(parse_success_rate, 4),
            "command_execution_rate": round(command_execution_rate, 4),
            "verified_success_rate": round(verified_success_rate, 4),
        }

    def counts(self) -> dict[str, int | float]:
        return {
            "intent_utterances": self.intent_utterances,
            "generated_commands": self.generated_commands,
            "discarded_commands": self.discarded_commands,
            "discarded_stale": self.stale_generations,
            "stale_generations": self.stale_generations,
            "emitted_commands": self.emitted_commands,
            "intended_action_events": self.intended_action_events,
            "parse_successes": self.parse_successes,
            "parse_failures": self.parse_failures,
            "malformed_accepted": self.parse_failures,
            "command_executions": self.command_executions,
            "execution_successes": self.execution_successes,
            "execution_failures": self.execution_failures,
            "execution_unknowns": self.execution_unknowns,
            "verified_actions": self.verified_actions,
            "builder_plan_generated": self.builder_plan_generated,
            "builder_plan_unique": self.builder_plan_unique,
            "builder_plan_skipped_dedupe": self.builder_plan_skipped_dedupe,
            "builder_plan_skipped_active": self.builder_plan_skipped_active,
            "builder_plan_skipped_cooldown": self.builder_plan_skipped_cooldown,
            "builder_plan_skipped_per_agent_cap": self.builder_plan_skipped_per_agent_cap,
            "builder_plan_cache_hits": self.builder_plan_cache_hits,
            "builder_plan_max_per_agent": self.builder_plan_max_per_agent,
            "builder_plan_paid_calls": self.builder_plan_paid_calls,
            "builder_plan_local_calls": self.builder_plan_local_calls,
            "builder_plan_estimated_usd": round(self.builder_plan_estimated_usd, 8),
            "builder_plan_prompt_tokens": self.builder_plan_prompt_tokens,
            "builder_plan_completion_tokens": self.builder_plan_completion_tokens,
            "builder_plan_total_tokens": self.builder_plan_total_tokens,
            "builder_plan_failures": self.builder_plan_failures,
            "builder_plan_fallbacks": self.builder_plan_fallbacks,
            "builder_plan_intended_blocks": self.builder_plan_intended_blocks,
            "builder_plan_verified_blocks": self.builder_plan_verified_blocks,
            "builder_plan_completion_rate": self.builder_plan_completion_rate,
        }

    def to_json(self, top_n: int) -> dict[str, Any]:
        return {
            "log_file": self.log_file,
            "counts": self.counts(),
            "metrics": self.metrics(),
            "parser_failure_classes": [
                {"class": klass, "count": count}
                for klass, count in self.parser_failures.most_common(top_n)
            ],
            "execution_failure_classes": [
                {"class": klass, "count": count}
                for klass, count in self.execution_failure_classes.most_common(top_n)
            ],
            "command_buckets": {
                bucket: dict(counts)
                for bucket, counts in sorted(self.command_buckets.items())
            },
            "builder_plan_metrics": {
                "builder_plan_generated": self.builder_plan_generated,
                "builder_plan_unique": self.builder_plan_unique,
                "builder_plan_skipped_dedupe": self.builder_plan_skipped_dedupe,
                "builder_plan_skipped_active": self.builder_plan_skipped_active,
                "builder_plan_skipped_cooldown": self.builder_plan_skipped_cooldown,
                "builder_plan_skipped_per_agent_cap": self.builder_plan_skipped_per_agent_cap,
                "builder_plan_cache_hits": self.builder_plan_cache_hits,
                "builder_plan_max_per_agent": self.builder_plan_max_per_agent,
                "builder_plan_paid_calls": self.builder_plan_paid_calls,
                "builder_plan_local_calls": self.builder_plan_local_calls,
                "builder_plan_estimated_usd": round(self.builder_plan_estimated_usd, 8),
                "builder_plan_prompt_tokens": self.builder_plan_prompt_tokens,
                "builder_plan_completion_tokens": self.builder_plan_completion_tokens,
                "builder_plan_total_tokens": self.builder_plan_total_tokens,
                "builder_plan_failures": self.builder_plan_failures,
                "builder_plan_fallbacks": self.builder_plan_fallbacks,
                "builder_provider_breakdown": dict(sorted(self.builder_plan_provider_counts.items())),
                "builder_plan_intended_blocks": self.builder_plan_intended_blocks,
                "builder_plan_verified_blocks": self.builder_plan_verified_blocks,
                "builder_plan_completion_rate": self.builder_plan_completion_rate,
            },
            "examples": {
                "failed_parses": [example.to_json() for example in self.failed_parse_examples[:top_n]],
                "verified_successes": [
                    example.to_json() for example in self.verified_success_examples[:top_n]
                ],
                "intent_without_command": [example.to_json() for example in self.intent_examples[:top_n]],
                "execution_failures": [
                    example.to_json() for example in self.execution_failure_examples[:top_n]
                ],
            },
        }


def excerpt(line: str, limit: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", line.strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def classify_parser_failure(line: str) -> str | None:
    for klass, patterns in PARSER_FAILURE_PATTERNS:
        if any(pattern.search(line) for pattern in patterns):
            return klass
    return None


def is_incoming_chat_or_memory(line: str) -> bool:
    lower = line.lower()
    if "received message from" in lower:
        return True
    stripped = line.strip()
    skipped_prefixes = (
        "Saved memory to:",
        "Memory updated to:",
        "Storing memories",
        "selected examples:",
    )
    return stripped.startswith(skipped_prefixes)


def should_count_parser_failure(line: str) -> bool:
    if not classify_parser_failure(line):
        return False
    if INSTRUCTION_RE.search(line):
        return False
    if is_incoming_chat_or_memory(line):
        return False
    lower = line.lower()
    if "agent executed:" in lower or "action.result" in lower or "perception.report" in lower:
        return False
    if "full response" in lower and "error parsing" not in lower and "could not parse" not in lower:
        return False
    diagnostic_markers = (
        "empty parsed response",
        "blank llm response",
        "no commands found",
        "no command",
        "does not exist",
        "unknown command",
        "could not parse",
        "error parsing",
        "parse error",
        "invalid command syntax",
        "malformed command",
        "expected",
        "too many",
        "too few",
    )
    return any(marker in lower for marker in diagnostic_markers)


def command_bucket(command_name: str) -> str:
    name = str(command_name or "").lstrip("!").lower()
    if name in {"place", "placehere", "placeblock"}:
        return "placement"
    if name == "buildfromplan":
        return "buildFromPlan"
    if name == "planandbuild":
        return "planAndBuild"
    return "other"


def bucket_counts(stats: AgentStats, bucket: str) -> Counter[str]:
    if bucket not in stats.command_buckets:
        stats.command_buckets[bucket] = Counter()
    return stats.command_buckets[bucket]


def record_accepted_command(stats: AgentStats, command_name: str) -> None:
    bucket_counts(stats, command_bucket(command_name))["accepted"] += 1


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


def first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def verified_blocks_from_payload(payload: dict[str, Any]) -> int:
    metric = payload.get("metric")
    if isinstance(metric, dict):
        parsed = first_int(metric.get("steps_verified"), metric.get("blocks_present"))
        if parsed is not None:
            return parsed
    parsed = first_int(payload.get("verified_blocks"), payload.get("blocks_verified"))
    if parsed is not None:
        return parsed
    result = str(payload.get("result") or payload.get("detail") or "")
    match = re.search(r"\bverified=(?P<count>\d+)\b", result)
    if match:
        return int(match.group("count"))
    return 0


def extract_json_event(line: str) -> dict[str, Any] | None:
    start = line.find("{")
    end = line.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(line[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def is_dedupe_plan_event(event_type: str, payload: dict[str, Any]) -> bool:
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("reason", "error", "status", "source", "detail")
    ).lower()
    return (
        "dedupe" in text
        or "duplicate" in text
        or "cache" in text
        or bool(payload.get("deduped"))
        or bool(payload.get("cache_hit"))
        or event_type.endswith(".skipped")
    )


def apply_build_plan_event(
    stats: AgentStats,
    event: dict[str, Any],
    *,
    source: str,
) -> None:
    event_type = str(event.get("event_type") or event.get("type") or "")
    if not event_type.startswith("build_plan."):
        return
    payload = event.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    action_id = str(payload.get("action_id") or event.get("trace_id") or source)
    key = "|".join(
        [
            event_type,
            action_id,
            str(event.get("ts") or ""),
            str(event.get("seq") or ""),
            source,
        ]
    )
    if key in stats.build_plan_event_keys:
        return
    stats.build_plan_event_keys.add(key)

    if event_type == "build_plan.generation.completed":
        stats.builder_plan_generated += 1
        stats.builder_plan_unique_ids.add(action_id)
        stats.builder_plan_intended_blocks += plan_block_count(payload.get("plan"))
        stats.builder_plan_max_per_agent = max(
            stats.builder_plan_max_per_agent,
            first_int(payload.get("max_builder_calls_per_agent")) or 0,
        )
        provider = str(payload.get("builder_provider") or payload.get("provider") or "unknown")
        stats.builder_plan_provider_counts[provider] += 1
        if payload.get("paid") or provider == "openrouter":
            stats.builder_plan_paid_calls += 1
        else:
            stats.builder_plan_local_calls += 1
        stats.builder_plan_prompt_tokens += first_int(payload.get("prompt_tokens")) or 0
        stats.builder_plan_completion_tokens += first_int(payload.get("completion_tokens")) or 0
        stats.builder_plan_total_tokens += first_int(payload.get("total_tokens")) or 0
        stats.builder_plan_estimated_usd += first_float(payload.get("estimated_usd")) or 0.0
        if payload.get("fallback_reason"):
            stats.builder_plan_fallbacks += 1
    elif event_type in {"build_plan.generation.rejected", "build_plan.generation.skipped"}:
        if is_dedupe_plan_event(event_type, payload):
            stats.builder_plan_skipped_dedupe += 1
        if event_type == "build_plan.generation.skipped":
            reason = str(payload.get("reason") or "").lower()
            if reason == "active_build_exists":
                stats.builder_plan_skipped_active += 1
            elif reason == "cooldown":
                stats.builder_plan_skipped_cooldown += 1
            elif reason == "per_agent_cap":
                stats.builder_plan_skipped_per_agent_cap += 1
            if reason == "cache_hit" or payload.get("cache_hit"):
                stats.builder_plan_cache_hits += 1
            stats.builder_plan_max_per_agent = max(
                stats.builder_plan_max_per_agent,
                first_int(payload.get("max_builder_calls_per_agent")) or 0,
            )
    elif event_type in {
        "build_plan.generation.provider_failed",
        "build_plan.generation.budget_capped",
    }:
        stats.builder_plan_failures += 1
        if payload.get("fallback_reason"):
            stats.builder_plan_fallbacks += 1
    elif event_type == "build_plan.execution.completed":
        stats.builder_plan_unique_ids.add(action_id)
        stats.builder_plan_verified_blocks += verified_blocks_from_payload(payload)


def apply_build_plan_events_from_line(stats: AgentStats, line: str, *, source: str) -> None:
    event = extract_json_event(line)
    if event:
        apply_build_plan_event(stats, event, source=source)


def apply_build_plan_events_from_timeline(
    run_dir: Path,
    stats_by_agent: dict[str, AgentStats],
) -> None:
    raw_dir = run_dir / "timeline-raw"
    paths = sorted(raw_dir.glob("*.ndjson")) if raw_dir.is_dir() else []
    if not paths and (run_dir / "timeline.ndjson").is_file():
        paths = [run_dir / "timeline.ndjson"]

    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                event = extract_json_event(raw_line)
                if not event:
                    continue
                event_type = str(event.get("event_type") or event.get("type") or "")
                if not event_type.startswith("build_plan."):
                    continue
                agent = str(event.get("agent") or path.stem).strip().lower()
                stats = stats_by_agent.get(agent)
                if stats is None:
                    continue
                apply_build_plan_event(stats, event, source=f"{path}:{line_no}")


def is_potential_utterance(line: str) -> bool:
    if INSTRUCTION_RE.search(line):
        return False
    if is_incoming_chat_or_memory(line):
        return False
    lower = line.lower()
    blocked_fragments = (
        "management_review_event",
        "trace=",
        "action.result",
        "perception.report",
        "cost_events",
        "preflight",
        "settings_json",
    )
    if any(fragment in lower for fragment in blocked_fragments):
        return False
    return bool(UTTERANCE_RE.search(line))


def is_intent_without_command(line: str) -> bool:
    if COMMAND_RE.search(line):
        return False
    if classify_parser_failure(line):
        return False
    if not is_potential_utterance(line):
        return False
    return bool(INTENT_PROMISE_RE.search(line) and INTENT_VERB_RE.search(line))


def classify_execution(line: str) -> tuple[str | None, bool]:
    if classify_parser_failure(line):
        return None, False
    has_context = bool(ACTION_CONTEXT_RE.search(line))
    has_failure = bool(EXECUTION_FAILURE_RE.search(line))
    has_success = bool(EXECUTION_SUCCESS_RE.search(line))
    if has_failure and (has_context or has_success):
        return "failure", False
    if has_success and (has_context or VERIFICATION_RE.search(line)):
        return "success", bool(VERIFICATION_RE.search(line))
    return None, False


def add_execution(stats: AgentStats, execution: ParsedExecution, top_n: int) -> None:
    bucket = bucket_counts(stats, command_bucket(execution.name))
    if execution.outcome == "success":
        stats.execution_successes += 1
        bucket["success"] += 1
        if execution.verified:
            stats.verified_actions += 1
            bucket["verified"] += 1
            if len(stats.verified_success_examples) < top_n:
                stats.verified_success_examples.append(
                    Example(line=execution.line, text=excerpt(execution.detail))
                )
        return

    if execution.outcome == "failure":
        stats.execution_failures += 1
        bucket["failure"] += 1
        stats.execution_failure_classes[execution.outcome_class] += 1
        if len(stats.execution_failure_examples) < top_n:
            stats.execution_failure_examples.append(
                Example(
                    line=execution.line,
                    klass=execution.outcome_class,
                    text=excerpt(execution.detail),
                )
            )
        return

    stats.execution_unknowns += 1
    bucket["unknown"] += 1
    stats.execution_failure_classes[execution.outcome_class] += 1


def analyze_log(path: Path, top_n: int) -> AgentStats:
    stats = AgentStats(agent=path.stem, log_file=str(path))
    parsed_log = parse_bot_log_file(path)
    stats.generated_commands = parsed_log.generated_commands
    stats.discarded_commands = parsed_log.discarded_commands
    stats.stale_generations = sum(1 for generation in parsed_log.generations if generation.stale)
    stats.emitted_commands = len(parsed_log.accepted_commands)
    for command in parsed_log.accepted_commands:
        record_accepted_command(stats, command.name)
    for execution in parsed_log.executions:
        add_execution(stats, execution, top_n)
    execution_lines = {
        line_no
        for execution in parsed_log.executions
        for line_no in range(execution.line, execution.end_line + 1)
    }

    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            apply_build_plan_events_from_line(stats, line, source=f"{path}:{line_no}")
            parser_failure = (
                classify_parser_failure(line)
                if line_no not in execution_lines and should_count_parser_failure(line)
                else None
            )
            if parser_failure:
                stats.parser_failures[parser_failure] += 1
                if len(stats.failed_parse_examples) < top_n:
                    stats.failed_parse_examples.append(
                        Example(line=line_no, klass=parser_failure, text=excerpt(line))
                    )
                continue

            if is_intent_without_command(line):
                stats.intent_utterances += 1
                if len(stats.intent_examples) < top_n:
                    stats.intent_examples.append(Example(line=line_no, text=excerpt(line)))

            if parsed_log.executions:
                continue

            if INSTRUCTION_RE.search(line):
                continue

            execution_kind, verified = classify_execution(line)
            if execution_kind == "success":
                stats.execution_successes += 1
                if verified:
                    stats.verified_actions += 1
                    if len(stats.verified_success_examples) < top_n:
                        stats.verified_success_examples.append(
                            Example(line=line_no, text=excerpt(line))
                        )
            elif execution_kind == "failure":
                stats.execution_failures += 1
                stats.execution_failure_classes["line_failure"] += 1

    return stats


def threshold_violations(
    agent: str,
    stats: AgentStats,
    thresholds: dict[str, float | int],
) -> list[dict[str, Any]]:
    if stats.intended_action_events < int(thresholds["min_intents"]):
        return []

    metrics = stats.metrics()
    checks = (
        ("intent_to_command_ratio", "min_intent_to_command"),
        ("parse_success_rate", "min_parse_success"),
        ("command_execution_rate", "min_execution_rate"),
        ("verified_success_rate", "min_verified_success"),
    )
    violations: list[dict[str, Any]] = []
    for metric_name, threshold_name in checks:
        observed = metrics[metric_name]
        required = float(thresholds[threshold_name])
        if observed + 1e-9 < required:
            violations.append(
                {
                    "agent": agent,
                    "metric": metric_name,
                    "observed": observed,
                    "required": required,
                    "intended_action_events": stats.intended_action_events,
                }
            )
    return violations


def aggregate_stats(agent_stats: list[AgentStats]) -> AgentStats:
    aggregate = AgentStats(agent="aggregate", log_file="<aggregate>")
    for stats in agent_stats:
        aggregate.intent_utterances += stats.intent_utterances
        aggregate.emitted_commands += stats.emitted_commands
        aggregate.generated_commands += stats.generated_commands
        aggregate.discarded_commands += stats.discarded_commands
        aggregate.stale_generations += stats.stale_generations
        aggregate.parser_failures.update(stats.parser_failures)
        for bucket, counts in stats.command_buckets.items():
            bucket_counts(aggregate, bucket).update(counts)
        aggregate.execution_successes += stats.execution_successes
        aggregate.execution_failures += stats.execution_failures
        aggregate.execution_unknowns += stats.execution_unknowns
        aggregate.verified_actions += stats.verified_actions
        aggregate.execution_failure_classes.update(stats.execution_failure_classes)
        aggregate.builder_plan_generated += stats.builder_plan_generated
        aggregate.builder_plan_unique_ids.update(stats.builder_plan_unique_ids)
        aggregate.builder_plan_skipped_dedupe += stats.builder_plan_skipped_dedupe
        aggregate.builder_plan_skipped_active += stats.builder_plan_skipped_active
        aggregate.builder_plan_skipped_cooldown += stats.builder_plan_skipped_cooldown
        aggregate.builder_plan_skipped_per_agent_cap += stats.builder_plan_skipped_per_agent_cap
        aggregate.builder_plan_cache_hits += stats.builder_plan_cache_hits
        aggregate.builder_plan_max_per_agent = max(
            aggregate.builder_plan_max_per_agent,
            stats.builder_plan_max_per_agent,
        )
        aggregate.builder_plan_paid_calls += stats.builder_plan_paid_calls
        aggregate.builder_plan_local_calls += stats.builder_plan_local_calls
        aggregate.builder_plan_estimated_usd += stats.builder_plan_estimated_usd
        aggregate.builder_plan_prompt_tokens += stats.builder_plan_prompt_tokens
        aggregate.builder_plan_completion_tokens += stats.builder_plan_completion_tokens
        aggregate.builder_plan_total_tokens += stats.builder_plan_total_tokens
        aggregate.builder_plan_failures += stats.builder_plan_failures
        aggregate.builder_plan_fallbacks += stats.builder_plan_fallbacks
        aggregate.builder_plan_provider_counts.update(stats.builder_plan_provider_counts)
        aggregate.builder_plan_intended_blocks += stats.builder_plan_intended_blocks
        aggregate.builder_plan_verified_blocks += stats.builder_plan_verified_blocks
    return aggregate


def analyze_run(
    run_dir: Path,
    thresholds: dict[str, float | int],
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    bots_dir = run_dir / "bots"
    if not bots_dir.is_dir():
        raise FileNotFoundError(f"missing bot log directory: {bots_dir}")
    log_paths = sorted(bots_dir.glob("*.log"))
    if not log_paths:
        raise FileNotFoundError(f"no bot logs found in {bots_dir}")

    agent_stats = [analyze_log(path, top_n=top_n) for path in log_paths]
    apply_build_plan_events_from_timeline(
        run_dir,
        {stats.agent: stats for stats in agent_stats},
    )
    aggregate = aggregate_stats(agent_stats)
    violations: list[dict[str, Any]] = []
    agents: dict[str, Any] = {}
    for stats in agent_stats:
        agent_violations = threshold_violations(stats.agent, stats, thresholds)
        violations.extend(agent_violations)
        data = stats.to_json(top_n)
        data["threshold_violations"] = agent_violations
        agents[stats.agent] = data

    return {
        "run_dir": str(run_dir),
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "acceptable": not violations,
        "thresholds": thresholds,
        "agents": agents,
        "aggregate": {
            "counts": aggregate.counts(),
            "metrics": aggregate.metrics(),
            "parser_failure_classes": [
                {"class": klass, "count": count}
                for klass, count in aggregate.parser_failures.most_common(top_n)
            ],
            "execution_failure_classes": [
                {"class": klass, "count": count}
                for klass, count in aggregate.execution_failure_classes.most_common(top_n)
            ],
            "command_buckets": {
                bucket: dict(counts)
                for bucket, counts in sorted(aggregate.command_buckets.items())
            },
            "builder_plan_metrics": {
                "builder_plan_generated": aggregate.builder_plan_generated,
                "builder_plan_unique": aggregate.builder_plan_unique,
                "builder_plan_skipped_dedupe": aggregate.builder_plan_skipped_dedupe,
                "builder_plan_skipped_active": aggregate.builder_plan_skipped_active,
                "builder_plan_skipped_cooldown": aggregate.builder_plan_skipped_cooldown,
                "builder_plan_skipped_per_agent_cap": aggregate.builder_plan_skipped_per_agent_cap,
                "builder_plan_cache_hits": aggregate.builder_plan_cache_hits,
                "builder_plan_max_per_agent": aggregate.builder_plan_max_per_agent,
                "builder_plan_paid_calls": aggregate.builder_plan_paid_calls,
                "builder_plan_local_calls": aggregate.builder_plan_local_calls,
                "builder_plan_estimated_usd": round(aggregate.builder_plan_estimated_usd, 8),
                "builder_plan_prompt_tokens": aggregate.builder_plan_prompt_tokens,
                "builder_plan_completion_tokens": aggregate.builder_plan_completion_tokens,
                "builder_plan_total_tokens": aggregate.builder_plan_total_tokens,
                "builder_plan_failures": aggregate.builder_plan_failures,
                "builder_plan_fallbacks": aggregate.builder_plan_fallbacks,
                "builder_provider_breakdown": dict(
                    sorted(aggregate.builder_plan_provider_counts.items())
                ),
                "builder_plan_intended_blocks": aggregate.builder_plan_intended_blocks,
                "builder_plan_verified_blocks": aggregate.builder_plan_verified_blocks,
                "builder_plan_completion_rate": aggregate.builder_plan_completion_rate,
            },
        },
        "threshold_violations": violations,
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def render_examples(title: str, examples: list[dict[str, Any]]) -> list[str]:
    lines = [f"#### {title}"]
    if not examples:
        lines.append("none captured")
        return lines
    for example in examples:
        klass = f" [{example['class']}]" if "class" in example else ""
        text = example["text"].replace("`", "'")
        lines.append(f"- line {example['line']}{klass}: `{text}`")
    return lines


def render_markdown(data: dict[str, Any]) -> str:
    thresholds = data["thresholds"]
    lines = [
        "# Action-Command Reliability Report",
        "",
        f"Run directory: `{data['run_dir']}`",
        f"Generated UTC: `{data['generated_at_utc']}`",
        f"Status: **{'PASS' if data['acceptable'] else 'NOT ACCEPTABLE'}**",
        "",
        "## Thresholds",
        "",
        markdown_table(
            ["Metric", "Minimum"],
            [
                ["intent_to_command_ratio", thresholds["min_intent_to_command"]],
                ["parse_success_rate", thresholds["min_parse_success"]],
                ["command_execution_rate", thresholds["min_execution_rate"]],
                ["verified_success_rate", thresholds["min_verified_success"]],
                ["min_intents", thresholds["min_intents"]],
            ],
        ),
        "",
        "## Aggregate",
        "",
        markdown_table(
            ["Metric", "Value"],
            [[name, value] for name, value in data["aggregate"]["metrics"].items()],
        ),
        "",
        markdown_table(
            ["Count", "Value"],
            [[name, value] for name, value in data["aggregate"]["counts"].items()],
        ),
        "",
        "## Top Parser Failure Classes",
        "",
    ]
    parser_classes = data["aggregate"]["parser_failure_classes"]
    if parser_classes:
        lines.append(markdown_table(["Class", "Count"], [[item["class"], item["count"]] for item in parser_classes]))
    else:
        lines.append("none captured")

    lines.extend(["", "## Top Execution Failure Classes", ""])
    execution_classes = data["aggregate"].get("execution_failure_classes", [])
    if execution_classes:
        lines.append(
            markdown_table(
                ["Class", "Count"],
                [[item["class"], item["count"]] for item in execution_classes],
            )
        )
    else:
        lines.append("none captured")

    lines.extend(["", "## Command Buckets", ""])
    command_buckets = data["aggregate"].get("command_buckets", {})
    if command_buckets:
        rows = []
        for bucket, counts in sorted(command_buckets.items()):
            rows.append(
                [
                    bucket,
                    counts.get("accepted", 0),
                    counts.get("success", 0),
                    counts.get("failure", 0),
                    counts.get("unknown", 0),
                    counts.get("verified", 0),
                ]
            )
        lines.append(
            markdown_table(
                ["Bucket", "Accepted", "Success", "Failure", "Unknown", "Verified"],
                rows,
            )
        )
    else:
        lines.append("none captured")

    lines.extend(["", "## Builder Plan Metrics", ""])
    builder_metrics = data["aggregate"].get("builder_plan_metrics", {})
    if builder_metrics:
        lines.append(
            markdown_table(
                ["Metric", "Value"],
                [[name, value] for name, value in builder_metrics.items()],
            )
        )
    else:
        lines.append("none captured")

    lines.extend(["", "## Threshold Violations", ""])
    if data["threshold_violations"]:
        lines.append(
            markdown_table(
                ["Agent", "Metric", "Observed", "Required", "Intended events"],
                [
                    [
                        item["agent"],
                        item["metric"],
                        item["observed"],
                        item["required"],
                        item["intended_action_events"],
                    ]
                    for item in data["threshold_violations"]
                ],
            )
        )
    else:
        lines.append("none")

    lines.extend(["", "## Agents", ""])
    for agent, stats in sorted(data["agents"].items()):
        lines.extend(
            [
                f"### {agent}",
                "",
                markdown_table(["Metric", "Value"], [[name, value] for name, value in stats["metrics"].items()]),
                "",
                markdown_table(["Count", "Value"], [[name, value] for name, value in stats["counts"].items()]),
                "",
            ]
        )
        if stats.get("command_buckets"):
            lines.append(
                markdown_table(
                    ["Bucket", "Accepted", "Success", "Failure", "Unknown", "Verified"],
                    [
                        [
                            bucket,
                            counts.get("accepted", 0),
                            counts.get("success", 0),
                            counts.get("failure", 0),
                            counts.get("unknown", 0),
                            counts.get("verified", 0),
                        ]
                        for bucket, counts in sorted(stats["command_buckets"].items())
                    ],
                )
            )
            lines.append("")
        lines.extend(render_examples("Failed Parse Examples", stats["examples"]["failed_parses"]))
        lines.append("")
        lines.extend(render_examples("Verified Success Examples", stats["examples"]["verified_successes"]))
        lines.append("")
        lines.extend(render_examples("Execution Failure Examples", stats["examples"]["execution_failures"]))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_artifacts(run_dir: Path, data: dict[str, Any]) -> None:
    (run_dir / "action-reliability.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "action-reliability.md").write_text(render_markdown(data), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze per-bot Minecraft logs for action-command reliability.",
    )
    parser.add_argument("--run-dir", required=True, type=Path, help="Soak run directory containing bots/*.log")
    parser.add_argument(
        "--min-intent-to-command",
        type=float,
        default=DEFAULT_MIN_INTENT_TO_COMMAND,
        help=f"Minimum commands per intended-action utterance. Default: {DEFAULT_MIN_INTENT_TO_COMMAND}",
    )
    parser.add_argument(
        "--min-parse-success",
        type=float,
        default=DEFAULT_MIN_PARSE_SUCCESS,
        help=f"Minimum parse success rate. Default: {DEFAULT_MIN_PARSE_SUCCESS}",
    )
    parser.add_argument(
        "--min-execution-rate",
        type=float,
        default=DEFAULT_MIN_EXECUTION_RATE,
        help=f"Minimum command execution rate. Default: {DEFAULT_MIN_EXECUTION_RATE}",
    )
    parser.add_argument(
        "--min-verified-success",
        type=float,
        default=DEFAULT_MIN_VERIFIED_SUCCESS,
        help=f"Minimum verified success rate. Default: {DEFAULT_MIN_VERIFIED_SUCCESS}",
    )
    parser.add_argument(
        "--min-intents",
        type=int,
        default=DEFAULT_MIN_INTENTS,
        help=f"Only enforce thresholds for agents with at least this many intended events. Default: {DEFAULT_MIN_INTENTS}",
    )
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help=f"Examples/failure classes to retain. Default: {DEFAULT_TOP_N}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    thresholds: dict[str, float | int] = {
        "min_intent_to_command": args.min_intent_to_command,
        "min_parse_success": args.min_parse_success,
        "min_execution_rate": args.min_execution_rate,
        "min_verified_success": args.min_verified_success,
        "min_intents": args.min_intents,
    }
    try:
        data = analyze_run(args.run_dir, thresholds=thresholds, top_n=args.top_n)
        write_artifacts(args.run_dir, data)
    except Exception as exc:
        print(f"action reliability analysis failed: {exc}", file=sys.stderr)
        return 2

    if data["acceptable"]:
        print(f"ok action-command reliability passed; see {args.run_dir / 'action-reliability.md'}")
        return 0

    print(
        f"x action-command reliability below threshold; see {args.run_dir / 'action-reliability.md'}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

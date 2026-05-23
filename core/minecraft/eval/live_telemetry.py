"""Telemetry models for focused Minecraft live command smoke runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class OutcomeClass:
    """Stable JSON outcome class constants for live command eval cases."""

    SUCCESS = "success"
    MALFORMED = "malformed"
    REJECTED = "rejected"
    WORLD_CONSTRAINT = "world_constraint"
    TIMEOUT = "timeout"
    ERROR = "error"

    ALL = (
        SUCCESS,
        MALFORMED,
        REJECTED,
        WORLD_CONSTRAINT,
        TIMEOUT,
        ERROR,
    )


_ACTION_EVENT_KINDS = frozenset(("start", "end"))
_WORLD_CONSTRAINT_MARKERS = frozenset(
    (
        "blocked",
        "collision",
        "constraint",
        "inventory",
        "missing",
        "no path",
        "occupied",
        "out of range",
        "path",
        "protected",
        "terrain",
        "unreachable",
        "world",
    )
)


@dataclass(frozen=True, slots=True)
class ActionEvent:
    """One action lifecycle event emitted while running a command case."""

    action_id: str
    kind: str
    ts_ms: int
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("action_id must be non-empty")
        if self.kind not in _ACTION_EVENT_KINDS:
            allowed = ", ".join(sorted(_ACTION_EVENT_KINDS))
            raise ValueError(f"action event kind must be one of: {allowed}")
        if self.ts_ms < 0:
            raise ValueError("ts_ms must be non-negative")
        object.__setattr__(self, "payload", dict(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "kind": self.kind,
            "ts_ms": self.ts_ms,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class CaseResult:
    """Telemetry and outcome for one generated live command case."""

    case_id: str
    command_text: str
    params: Mapping[str, Any]
    action_events: tuple[ActionEvent, ...]
    outcome_class: str
    final_state: Mapping[str, Any]
    latency_ms: int
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id must be non-empty")
        if not self.command_text:
            raise ValueError("command_text must be non-empty")
        if self.outcome_class not in OutcomeClass.ALL:
            allowed = ", ".join(OutcomeClass.ALL)
            raise ValueError(f"outcome_class must be one of: {allowed}")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "action_events", tuple(self.action_events))
        object.__setattr__(self, "final_state", dict(self.final_state))

    @property
    def passed(self) -> bool:
        return self.outcome_class == OutcomeClass.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "command_text": self.command_text,
            "params": dict(self.params),
            "action_events": [event.to_dict() for event in self.action_events],
            "outcome_class": self.outcome_class,
            "final_state": dict(self.final_state),
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class LiveRunSummary:
    """Aggregated result for one focused Minecraft live command smoke run."""

    command: str
    resolved_command: str
    profile: str
    seed: int
    dry_run: bool
    verbose: bool
    case_results: tuple[CaseResult, ...]
    profile_detail: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command must be non-empty")
        if not self.resolved_command:
            raise ValueError("resolved_command must be non-empty")
        if not self.profile:
            raise ValueError("profile must be non-empty")
        object.__setattr__(self, "case_results", tuple(self.case_results))
        object.__setattr__(self, "profile_detail", dict(self.profile_detail))

    @property
    def outcome_counts(self) -> dict[str, int]:
        counts = {outcome: 0 for outcome in OutcomeClass.ALL}
        for result in self.case_results:
            counts[result.outcome_class] += 1
        return counts

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.case_results if result.passed)

    @property
    def failed_count(self) -> int:
        return len(self.case_results) - self.passed_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "resolved_command": self.resolved_command,
            "profile": self.profile,
            "profile_detail": dict(self.profile_detail),
            "seed": self.seed,
            "dry_run": self.dry_run,
            "verbose": self.verbose,
            "cases": len(self.case_results),
            "passed": self.passed_count,
            "failed": self.failed_count,
            "outcome_counts": self.outcome_counts,
            "case_results": [result.to_dict() for result in self.case_results],
        }


def classify_bridge_status(
    status: object,
    *,
    reason: object | None = None,
    error: object | None = None,
) -> str:
    """Classify a bridge status payload into stable live-eval outcome classes."""

    normalized = str(status or "").strip().casefold().replace("-", "_")
    detail = " ".join(
        str(part).strip().casefold()
        for part in (reason, error)
        if part is not None and str(part).strip()
    )

    if normalized in {"ok", "success", "succeeded"}:
        return OutcomeClass.SUCCESS
    if normalized in {"malformed", "parse_error", "parser_error", "invalid_command"}:
        return OutcomeClass.MALFORMED
    if normalized in {"rejected", "denied", "forbidden", "blocked_by_policy"}:
        return OutcomeClass.REJECTED
    if normalized in {"timeout", "timed_out"}:
        return OutcomeClass.TIMEOUT
    if normalized in {"partial", "failed", "failure"} and _is_world_constraint(detail):
        return OutcomeClass.WORLD_CONSTRAINT
    if normalized in {"partial", "failed", "failure"} and not detail:
        return OutcomeClass.ERROR
    if normalized and _is_world_constraint(f"{normalized} {detail}"):
        return OutcomeClass.WORLD_CONSTRAINT
    return OutcomeClass.ERROR


def _is_world_constraint(detail: str) -> bool:
    return any(marker in detail for marker in _WORLD_CONSTRAINT_MARKERS)

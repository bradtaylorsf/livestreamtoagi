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


class EvalCategory:
    """Stable JSON category constants for live eval behavior scoring."""

    PATHFINDING = "pathfinding"
    COLLISION = "collision"
    OTHER = "other"

    ALL = (
        PATHFINDING,
        COLLISION,
        OTHER,
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
_PATHFINDING_COMMANDS = frozenset(
    (
        "move",
        "searchforblock",
        "planandbuild",
        "buildfromplan",
    )
)
_COLLISION_MARKERS = frozenset(("collision", "collided", "colliding", "hit obstacle"))
_STUCK_MARKERS = frozenset(("stuck", "timed out", "timeout"))
_BLOCKED_PATH_MARKERS = frozenset(("blocked", "cannot path", "no path", "unreachable"))
_SIGNAL_TEXT_KEYS = frozenset(
    ("detail", "error", "last_error", "message", "reason", "status_detail")
)
_POSE_KEYS = ("final_pose", "pose")


@dataclass(frozen=True, slots=True)
class PathfindingSignals:
    """Derived pathfinding/collision signals for one live eval case."""

    success: bool | None
    stuck: bool = False
    collision: bool = False
    blocked_path: bool = False
    final_pose: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.success is not None and not isinstance(self.success, bool):
            raise ValueError("success must be a bool or None")
        object.__setattr__(self, "stuck", bool(self.stuck))
        object.__setattr__(self, "collision", bool(self.collision))
        object.__setattr__(self, "blocked_path", bool(self.blocked_path))
        pose = dict(self.final_pose) if isinstance(self.final_pose, Mapping) else None
        object.__setattr__(self, "final_pose", pose)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "stuck": self.stuck,
            "collision": self.collision,
            "blocked_path": self.blocked_path,
            "final_pose": dict(self.final_pose) if self.final_pose is not None else None,
        }


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
    eval_category: str | None = None
    pathfinding: PathfindingSignals | Mapping[str, Any] | None = None

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
        command_name = _command_name_from_case(self.command_text, self.params)
        eval_category = self.eval_category or classify_eval_category(
            command_name,
            self.outcome_class,
            self.error,
            self.final_state,
        )
        if eval_category not in EvalCategory.ALL:
            allowed = ", ".join(EvalCategory.ALL)
            raise ValueError(f"eval_category must be one of: {allowed}")
        object.__setattr__(self, "eval_category", eval_category)

        pathfinding = self.pathfinding
        if isinstance(pathfinding, Mapping):
            pathfinding = _coerce_pathfinding_signals(pathfinding)
        elif pathfinding is None and eval_category in (
            EvalCategory.PATHFINDING,
            EvalCategory.COLLISION,
        ):
            pathfinding = derive_pathfinding_signals(
                command_name,
                self.outcome_class,
                reason=self.error,
                error=self.error,
                final_state=self.final_state,
            )
        object.__setattr__(self, "pathfinding", pathfinding)

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
            "eval_category": self.eval_category,
            "pathfinding": self.pathfinding.to_dict() if self.pathfinding else None,
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
    def category_counts(self) -> dict[str, int]:
        counts = {category: 0 for category in EvalCategory.ALL}
        for result in self.case_results:
            counts[result.eval_category] += 1
        return counts

    @property
    def pathfinding_summary(self) -> dict[str, int]:
        summary = {
            "cases": 0,
            "success": 0,
            "failure": 0,
            "unknown": 0,
            "stuck": 0,
            "collision": 0,
            "blocked_path": 0,
            "final_pose": 0,
        }
        for result in self.case_results:
            signals = result.pathfinding
            if signals is None:
                continue
            summary["cases"] += 1
            if signals.success is True:
                summary["success"] += 1
            elif signals.success is False:
                summary["failure"] += 1
            else:
                summary["unknown"] += 1
            if signals.stuck:
                summary["stuck"] += 1
            if signals.collision:
                summary["collision"] += 1
            if signals.blocked_path:
                summary["blocked_path"] += 1
            if signals.final_pose is not None:
                summary["final_pose"] += 1
        return summary

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
            "category_counts": self.category_counts,
            "pathfinding_summary": self.pathfinding_summary,
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


def classify_eval_category(
    command_name: object,
    outcome_class: object,
    reason: object | None,
    final_state: Mapping[str, Any] | None,
) -> str:
    """Classify the live-eval behavior category for one command outcome."""

    detail = _normalize_detail(reason, _signal_text(final_state))
    if _has_collision_signal(detail, final_state):
        return EvalCategory.COLLISION

    normalized_command = _normalize_command_name(command_name)
    if normalized_command in _PATHFINDING_COMMANDS:
        return EvalCategory.PATHFINDING
    return EvalCategory.OTHER


def derive_pathfinding_signals(
    command_name: object,
    outcome_class: object,
    *,
    reason: object | None = None,
    error: object | None = None,
    final_state: Mapping[str, Any] | None = None,
) -> PathfindingSignals | None:
    """Derive pathfinding/collision signals for navigation-related eval cases."""

    eval_category = classify_eval_category(command_name, outcome_class, reason, final_state)
    if eval_category not in (EvalCategory.PATHFINDING, EvalCategory.COLLISION):
        return None

    detail = _normalize_detail(reason, error, _signal_text(final_state))
    if outcome_class == OutcomeClass.SUCCESS:
        success: bool | None = True
    elif outcome_class in (OutcomeClass.MALFORMED, OutcomeClass.REJECTED):
        success = None
    else:
        success = False

    return PathfindingSignals(
        success=success,
        stuck=_has_marker(detail, _STUCK_MARKERS) or _truthy_signal(final_state, "stuck"),
        collision=_has_collision_signal(detail, final_state),
        blocked_path=_has_marker(detail, _BLOCKED_PATH_MARKERS)
        or _truthy_signal(final_state, "blocked_path")
        or _truthy_signal(final_state, "blocked")
        or _truthy_signal(final_state, "unreachable")
        or _truthy_signal(final_state, "no_path"),
        final_pose=_extract_final_pose(final_state),
    )


def _is_world_constraint(detail: str) -> bool:
    return any(marker in detail for marker in _WORLD_CONSTRAINT_MARKERS)


def _coerce_pathfinding_signals(raw: Mapping[str, Any]) -> PathfindingSignals:
    return PathfindingSignals(
        success=raw.get("success") if isinstance(raw.get("success"), bool) else None,
        stuck=_coerce_bool(raw.get("stuck")),
        collision=_coerce_bool(raw.get("collision")),
        blocked_path=_coerce_bool(raw.get("blocked_path") or raw.get("blocked")),
        final_pose=raw.get("final_pose") if isinstance(raw.get("final_pose"), Mapping) else None,
    )


def _command_name_from_case(command_text: str, params: Mapping[str, Any]) -> str:
    token = str(params.get("command_token") or "").strip()
    if not token:
        token = command_text.strip().split(maxsplit=1)[0] if command_text.strip() else ""
    return token


def _normalize_command_name(command_name: object) -> str:
    return str(command_name or "").strip().lstrip("!").casefold()


def _normalize_detail(*parts: object | None) -> str:
    return " ".join(
        str(part).strip().casefold() for part in parts if part is not None and str(part).strip()
    )


def _has_marker(detail: str, markers: frozenset[str]) -> bool:
    return any(marker in detail for marker in markers)


def _has_collision_signal(
    detail: str,
    final_state: Mapping[str, Any] | None,
) -> bool:
    return (
        _has_marker(detail, _COLLISION_MARKERS)
        or _truthy_signal(final_state, "collision")
        or _truthy_signal(final_state, "collided")
        or _truthy_signal(final_state, "hit_obstacle")
    )


def _truthy_signal(raw: object, key: str) -> bool:
    if not isinstance(raw, Mapping):
        return False
    for raw_key, value in raw.items():
        if str(raw_key).casefold() == key.casefold() and _coerce_bool(value):
            return True
        if isinstance(value, Mapping) and _truthy_signal(value, key):
            return True
    return False


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return False


def _signal_text(raw: object) -> str:
    values: list[str] = []
    _collect_signal_text(raw, values)
    return " ".join(values)


def _collect_signal_text(raw: object, values: list[str]) -> None:
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(value, Mapping):
                _collect_signal_text(value, values)
            elif str(key).casefold() in _SIGNAL_TEXT_KEYS and value is not None:
                values.append(str(value))
    elif isinstance(raw, (tuple, list)):
        for value in raw:
            _collect_signal_text(value, values)


def _extract_final_pose(final_state: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(final_state, Mapping):
        return None
    for key in _POSE_KEYS:
        value = final_state.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    pathfinding = final_state.get("pathfinding")
    if isinstance(pathfinding, Mapping):
        for key in _POSE_KEYS:
            value = pathfinding.get(key)
            if isinstance(value, Mapping):
                return dict(value)
    return None

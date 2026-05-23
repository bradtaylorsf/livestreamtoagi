"""Telemetry models for focused Minecraft live command smoke runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
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
    INVENTORY = "inventory"
    BLOCK_MUTATION = "block_mutation"
    OTHER = "other"

    ALL = (
        PATHFINDING,
        COLLISION,
        INVENTORY,
        BLOCK_MUTATION,
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
INVENTORY_COMMANDS = frozenset(("inventory", "placehere", "planandbuild", "buildfromplan"))
BLOCK_MUTATION_COMMANDS = frozenset(("placehere", "planandbuild", "buildfromplan"))
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
class InventoryDelta:
    """Initial/final inventory and derived item deltas for one command."""

    initial: Mapping[str, int]
    final: Mapping[str, int]
    added: Mapping[str, int]
    removed: Mapping[str, int]
    net: Mapping[str, int]
    matches_expected: bool | None
    missing_expected: Mapping[str, int]
    unexpected: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial", _coerce_int_mapping(self.initial))
        object.__setattr__(self, "final", _coerce_int_mapping(self.final))
        object.__setattr__(self, "added", _coerce_int_mapping(self.added))
        object.__setattr__(self, "removed", _coerce_int_mapping(self.removed))
        object.__setattr__(self, "net", _coerce_int_mapping(self.net))
        if self.matches_expected is not None and not isinstance(self.matches_expected, bool):
            raise ValueError("matches_expected must be a bool or None")
        object.__setattr__(
            self,
            "missing_expected",
            _coerce_int_mapping(self.missing_expected),
        )
        object.__setattr__(self, "unexpected", _coerce_int_mapping(self.unexpected))

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial": dict(self.initial),
            "final": dict(self.final),
            "added": dict(self.added),
            "removed": dict(self.removed),
            "net": dict(self.net),
            "matches_expected": self.matches_expected,
            "missing_expected": dict(self.missing_expected),
            "unexpected": dict(self.unexpected),
        }


@dataclass(frozen=True, slots=True)
class BlockMutation:
    """Intended-vs-actual block placement comparison for one command."""

    intended_placements: tuple[Mapping[str, Any], ...]
    actual_placements: tuple[Mapping[str, Any], ...]
    matched_placements: tuple[Mapping[str, Any], ...]
    missing_placements: tuple[Mapping[str, Any], ...]
    extra_placements: tuple[Mapping[str, Any], ...]
    matches_expected: bool | None
    initial_blocks: tuple[Mapping[str, Any], ...]
    final_blocks: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "intended_placements",
            _coerce_placement_tuple(self.intended_placements),
        )
        object.__setattr__(
            self,
            "actual_placements",
            _coerce_placement_tuple(self.actual_placements),
        )
        object.__setattr__(
            self,
            "matched_placements",
            _coerce_placement_tuple(self.matched_placements),
        )
        object.__setattr__(
            self,
            "missing_placements",
            _coerce_placement_tuple(self.missing_placements),
        )
        object.__setattr__(
            self,
            "extra_placements",
            _coerce_placement_tuple(self.extra_placements),
        )
        if self.matches_expected is not None and not isinstance(self.matches_expected, bool):
            raise ValueError("matches_expected must be a bool or None")
        object.__setattr__(self, "initial_blocks", _coerce_placement_tuple(self.initial_blocks))
        object.__setattr__(self, "final_blocks", _coerce_placement_tuple(self.final_blocks))

    def to_dict(self) -> dict[str, Any]:
        return {
            "intended_placements": [dict(block) for block in self.intended_placements],
            "actual_placements": [dict(block) for block in self.actual_placements],
            "matched_placements": [dict(block) for block in self.matched_placements],
            "missing_placements": [dict(block) for block in self.missing_placements],
            "extra_placements": [dict(block) for block in self.extra_placements],
            "matches_expected": self.matches_expected,
            "initial_blocks": [dict(block) for block in self.initial_blocks],
            "final_blocks": [dict(block) for block in self.final_blocks],
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
    inventory: InventoryDelta | Mapping[str, Any] | None = None
    block_mutation: BlockMutation | Mapping[str, Any] | None = None

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

        inventory = self.inventory
        if isinstance(inventory, Mapping):
            inventory = _coerce_inventory_delta(inventory)
        elif inventory is None and eval_category in (
            EvalCategory.INVENTORY,
            EvalCategory.BLOCK_MUTATION,
        ):
            inventory = derive_inventory_delta(
                command_name,
                self.outcome_class,
                params=self.params,
                final_state=self.final_state,
            )
        object.__setattr__(self, "inventory", inventory)

        block_mutation = self.block_mutation
        if isinstance(block_mutation, Mapping):
            block_mutation = _coerce_block_mutation(block_mutation)
        elif block_mutation is None and eval_category == EvalCategory.BLOCK_MUTATION:
            block_mutation = derive_block_mutation(
                command_name,
                self.outcome_class,
                params=self.params,
                final_state=self.final_state,
            )
        object.__setattr__(self, "block_mutation", block_mutation)

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
            "inventory": self.inventory.to_dict() if self.inventory else None,
            "block_mutation": self.block_mutation.to_dict() if self.block_mutation else None,
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
    def inventory_summary(self) -> dict[str, int]:
        summary = {
            "cases": 0,
            "matches": 0,
            "mismatches": 0,
            "unknown": 0,
            "cases_with_state": 0,
        }
        for result in self.case_results:
            inventory = result.inventory
            if inventory is None:
                continue
            summary["cases"] += 1
            if inventory.initial or inventory.final:
                summary["cases_with_state"] += 1
            if inventory.matches_expected is True:
                summary["matches"] += 1
            elif inventory.matches_expected is False:
                summary["mismatches"] += 1
            else:
                summary["unknown"] += 1
        return summary

    @property
    def block_mutation_summary(self) -> dict[str, int]:
        summary = {
            "cases": 0,
            "matches": 0,
            "mismatches": 0,
            "unknown": 0,
            "cases_with_state": 0,
        }
        for result in self.case_results:
            block_mutation = result.block_mutation
            if block_mutation is None:
                continue
            summary["cases"] += 1
            if (
                block_mutation.initial_blocks
                or block_mutation.final_blocks
                or block_mutation.actual_placements
            ):
                summary["cases_with_state"] += 1
            if block_mutation.matches_expected is True:
                summary["matches"] += 1
            elif block_mutation.matches_expected is False:
                summary["mismatches"] += 1
            else:
                summary["unknown"] += 1
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
            "inventory_summary": self.inventory_summary,
            "block_mutation_summary": self.block_mutation_summary,
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
    if normalized_command in _PATHFINDING_COMMANDS and (
        normalized_command not in BLOCK_MUTATION_COMMANDS
        or _has_pathfinding_signal(detail, final_state)
    ):
        return EvalCategory.PATHFINDING
    if normalized_command in BLOCK_MUTATION_COMMANDS:
        return EvalCategory.BLOCK_MUTATION
    if normalized_command == "inventory":
        return EvalCategory.INVENTORY
    if _has_inventory_state(final_state):
        return EvalCategory.INVENTORY
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


def derive_inventory_delta(
    command_name: object,
    outcome_class: object,
    *,
    params: Mapping[str, Any] | None = None,
    final_state: Mapping[str, Any] | None = None,
) -> InventoryDelta | None:
    """Derive inventory deltas and optional expected-delta match details."""

    normalized_command = _normalize_command_name(command_name)
    state = final_state if isinstance(final_state, Mapping) else {}
    if normalized_command not in INVENTORY_COMMANDS and not _has_inventory_state(state):
        return None

    initial = _inventory_from_state(state, ("initial_inventory",))
    final = _inventory_from_state(state, ("final_inventory", "inventory"))
    if not initial and not final and not _has_inventory_state(state):
        return None

    expected = _expected_inventory_delta(params)
    del outcome_class
    return _inventory_delta(initial, final, expected)


def derive_block_mutation(
    command_name: object,
    outcome_class: object,
    *,
    params: Mapping[str, Any] | None = None,
    final_state: Mapping[str, Any] | None = None,
) -> BlockMutation | None:
    """Derive intended-vs-actual block placement comparison details."""

    normalized_command = _normalize_command_name(command_name)
    if normalized_command not in BLOCK_MUTATION_COMMANDS:
        return None

    state = final_state if isinstance(final_state, Mapping) else {}
    raw_params = params if isinstance(params, Mapping) else {}
    intended, has_expectation = _intended_placements(normalized_command, raw_params, state)
    actual = _block_placements_from_state(state, ("placed_blocks", "blocks", "final_blocks"))
    initial_blocks = _block_placements_from_state(state, ("initial_blocks",))
    matched, missing, extra = _match_placements(intended, actual)
    matches_expected = None if not has_expectation else not missing and not extra
    del outcome_class

    return BlockMutation(
        intended_placements=intended,
        actual_placements=actual,
        matched_placements=matched,
        missing_placements=missing,
        extra_placements=extra,
        matches_expected=matches_expected,
        initial_blocks=initial_blocks,
        final_blocks=actual,
    )


def _inventory_delta(
    initial: Mapping[str, int],
    final: Mapping[str, int],
    expected_delta: Mapping[str, int] | None,
) -> InventoryDelta:
    keys = sorted(set(initial).union(final))
    net = {
        key: final.get(key, 0) - initial.get(key, 0)
        for key in keys
        if final.get(key, 0) - initial.get(key, 0) != 0
    }
    added = {key: value for key, value in net.items() if value > 0}
    removed = {key: abs(value) for key, value in net.items() if value < 0}

    if expected_delta is None:
        matches_expected = None
        missing_expected: dict[str, int] = {}
        unexpected: dict[str, int] = {}
    else:
        expected = dict(expected_delta)
        missing_expected = {
            key: expected_value
            for key, expected_value in expected.items()
            if net.get(key, 0) != expected_value
        }
        unexpected = {
            key: actual_value
            for key, actual_value in net.items()
            if key not in expected or expected[key] != actual_value
        }
        matches_expected = not missing_expected and not unexpected

    return InventoryDelta(
        initial=initial,
        final=final,
        added=added,
        removed=removed,
        net=net,
        matches_expected=matches_expected,
        missing_expected=missing_expected,
        unexpected=unexpected,
    )


def _intended_placements(
    command_name: str,
    params: Mapping[str, Any],
    final_state: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], bool]:
    expected_raw, has_expected = _first_present(params, ("expected_blocks", "placed_blocks"))
    origin = _placement_origin(params.get("origin")) or _placement_origin(final_state.get("origin"))
    if origin is None:
        origin = _extract_final_pose(final_state)
    if has_expected:
        return _normalize_placements(expected_raw, origin=origin), True

    plan = params.get("plan")
    if isinstance(plan, Mapping):
        plan_blocks, has_plan_blocks = _first_present(plan, ("blocks", "expected_blocks"))
        if has_plan_blocks:
            plan_origin = (
                _placement_origin(params.get("origin"))
                or _placement_origin(plan.get("origin"))
                or origin
            )
            return _normalize_placements(plan_blocks, origin=plan_origin), True

    del command_name
    return (), False


def _match_placements(
    intended: tuple[Mapping[str, Any], ...],
    actual: tuple[Mapping[str, Any], ...],
) -> tuple[
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
]:
    actual_counts = Counter(_placement_key(block) for block in actual)
    matched: list[Mapping[str, Any]] = []
    missing: list[Mapping[str, Any]] = []
    for block in intended:
        key = _placement_key(block)
        if actual_counts[key] > 0:
            actual_counts[key] -= 1
            matched.append(block)
        else:
            missing.append(block)

    extra: list[Mapping[str, Any]] = []
    for block in actual:
        key = _placement_key(block)
        if actual_counts[key] > 0:
            actual_counts[key] -= 1
            extra.append(block)

    return tuple(matched), tuple(missing), tuple(extra)


def _coerce_inventory_delta(raw: Mapping[str, Any]) -> InventoryDelta:
    matches = raw.get("matches_expected")
    return InventoryDelta(
        initial=raw.get("initial") if isinstance(raw.get("initial"), Mapping) else {},
        final=raw.get("final") if isinstance(raw.get("final"), Mapping) else {},
        added=raw.get("added") if isinstance(raw.get("added"), Mapping) else {},
        removed=raw.get("removed") if isinstance(raw.get("removed"), Mapping) else {},
        net=raw.get("net") if isinstance(raw.get("net"), Mapping) else {},
        matches_expected=matches if isinstance(matches, bool) or matches is None else None,
        missing_expected=raw.get("missing_expected")
        if isinstance(raw.get("missing_expected"), Mapping)
        else {},
        unexpected=raw.get("unexpected") if isinstance(raw.get("unexpected"), Mapping) else {},
    )


def _coerce_block_mutation(raw: Mapping[str, Any]) -> BlockMutation:
    matches = raw.get("matches_expected")
    return BlockMutation(
        intended_placements=_raw_sequence(raw.get("intended_placements")),
        actual_placements=_raw_sequence(raw.get("actual_placements")),
        matched_placements=_raw_sequence(raw.get("matched_placements")),
        missing_placements=_raw_sequence(raw.get("missing_placements")),
        extra_placements=_raw_sequence(raw.get("extra_placements")),
        matches_expected=matches if isinstance(matches, bool) or matches is None else None,
        initial_blocks=_raw_sequence(raw.get("initial_blocks")),
        final_blocks=_raw_sequence(raw.get("final_blocks")),
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


def _has_pathfinding_signal(detail: str, final_state: Mapping[str, Any] | None) -> bool:
    return (
        _has_marker(detail, _STUCK_MARKERS)
        or _has_marker(detail, _BLOCKED_PATH_MARKERS)
        or _truthy_signal(final_state, "stuck")
        or _truthy_signal(final_state, "blocked_path")
        or _truthy_signal(final_state, "blocked")
        or _truthy_signal(final_state, "unreachable")
        or _truthy_signal(final_state, "no_path")
    )


def _has_inventory_state(raw: object) -> bool:
    if not isinstance(raw, Mapping):
        return False
    wanted = {"inventory", "initial_inventory", "final_inventory"}
    return any(str(key).casefold() in wanted for key in raw)


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


def _coerce_int_mapping(raw: object) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    coerced: dict[str, int] = {}
    for key, value in raw.items():
        amount = _coerce_int(value)
        if amount is None:
            continue
        coerced[str(key)] = amount
    return coerced


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _inventory_from_state(
    final_state: Mapping[str, Any],
    keys: tuple[str, ...],
) -> dict[str, int]:
    value, found = _first_present(final_state, keys)
    if not found:
        return {}
    return _coerce_int_mapping(value)


def _expected_inventory_delta(params: Mapping[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(params, Mapping):
        return None
    raw, found = _first_present(params, ("expected_inventory_delta", "inventory_delta"))
    if not found:
        return None
    return _coerce_int_mapping(raw)


def _block_placements_from_state(
    final_state: Mapping[str, Any],
    keys: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    raw, found = _first_present(final_state, keys)
    if not found:
        return ()
    return _normalize_placements(raw)


def _normalize_placements(
    raw: object,
    *,
    origin: Mapping[str, Any] | None = None,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        placement
        for placement in (_normalize_placement(item, origin=origin) for item in _raw_sequence(raw))
        if placement is not None
    )


def _normalize_placement(
    raw: object,
    *,
    origin: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    block_type = raw.get("block_type") or raw.get("type") or raw.get("block")
    if block_type is None or not str(block_type).strip():
        return None

    if all(key in raw for key in ("x", "y", "z")):
        x = _coerce_int(raw.get("x"))
        y = _coerce_int(raw.get("y"))
        z = _coerce_int(raw.get("z"))
    elif all(key in raw for key in ("dx", "dy", "dz")):
        base = origin if isinstance(origin, Mapping) else {}
        base_x = _coerce_int(base.get("x")) or 0
        base_y = _coerce_int(base.get("y")) or 0
        base_z = _coerce_int(base.get("z")) or 0
        dx = _coerce_int(raw.get("dx"))
        dy = _coerce_int(raw.get("dy"))
        dz = _coerce_int(raw.get("dz"))
        x = None if dx is None else base_x + dx
        y = None if dy is None else base_y + dy
        z = None if dz is None else base_z + dz
    else:
        return None

    if x is None or y is None or z is None:
        return None
    return {"x": x, "y": y, "z": z, "block_type": str(block_type)}


def _coerce_placement_tuple(raw: object) -> tuple[Mapping[str, Any], ...]:
    return _normalize_placements(raw)


def _placement_key(block: Mapping[str, Any]) -> tuple[int, int, int, str]:
    return (
        int(block["x"]),
        int(block["y"]),
        int(block["z"]),
        str(block["block_type"]),
    )


def _placement_origin(raw: object) -> Mapping[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    x = _coerce_int(raw.get("x"))
    y = _coerce_int(raw.get("y"))
    z = _coerce_int(raw.get("z"))
    if x is None or y is None or z is None:
        return None
    return {"x": x, "y": y, "z": z}


def _raw_sequence(raw: object) -> tuple[object, ...]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        return tuple(raw)
    return ()


def _first_present(raw: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[object, bool]:
    wanted = {key.casefold(): key for key in keys}
    for key, value in raw.items():
        if str(key).casefold() in wanted:
            return value, True
    return None, False


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

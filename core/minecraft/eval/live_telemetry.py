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
    DEATH_LOOP = "death_loop"
    SAFE_SPAWN = "safe_spawn"
    STUCK_UNSTUCK = "stuck_unstuck"
    MULTI_AGENT_TIMING = "multi_agent_timing"
    OTHER = "other"

    ALL = (
        PATHFINDING,
        COLLISION,
        INVENTORY,
        BLOCK_MUTATION,
        DEATH_LOOP,
        SAFE_SPAWN,
        STUCK_UNSTUCK,
        MULTI_AGENT_TIMING,
        OTHER,
    )


class MultiAgentTimingFailure:
    """Stable JSON failure classes for multi-agent timing eval cases."""

    QUEUE_CONTENTION = "queue_contention"
    SELF_INTERRUPTION = "self_interruption"
    DIRECTOR_FANOUT = "director_fanout"
    COMMAND_LOSS = "command_loss"
    TIMING_DRIFT = "timing_drift"
    NONE = "none"

    ALL = (
        QUEUE_CONTENTION,
        SELF_INTERRUPTION,
        DIRECTOR_FANOUT,
        COMMAND_LOSS,
        TIMING_DRIFT,
        NONE,
    )


_ACTION_EVENT_KINDS = frozenset(
    (
        "start",
        "end",
        "queued",
        "dropped",
        "preempted",
        "interrupted",
        "fanout",
        "death",
        "died",
        "killed",
        "fatal",
        "respawn",
        "respawned",
        "safe_spawn",
        "unsafe_spawn",
        "stuck",
        "unstuck",
        "unstuck_attempt",
        "unstuck_success",
        "unstuck_failure",
        "recovery",
        "recovered",
    )
)
_WORLD_CONSTRAINT_MARKERS = frozenset(
    (
        "blocked",
        "collision",
        "constraint",
        "death",
        "died",
        "fatal",
        "inventory",
        "killed",
        "lava",
        "missing",
        "no path",
        "occupied",
        "out of range",
        "path",
        "protected",
        "recovery",
        "spawn in lava",
        "still_stuck",
        "stuck",
        "terrain",
        "unreachable",
        "unsafe spawn",
        "void spawn",
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
_DEATH_MARKERS = frozenset(("died", "death", "killed", "fatal"))
_RESPAWN_MARKERS = frozenset(("respawn", "respawned"))
_SAFE_SPAWN_MARKERS = frozenset(("safe spawn", "safe_spawn", "spawn_safe", "safe-spawn"))
_UNSAFE_SPAWN_MARKERS = frozenset(
    ("unsafe spawn", "lava", "void spawn", "spawn in lava", "cliff spawn")
)
_UNSTUCK_ATTEMPT_MARKERS = frozenset(("unstuck", "recover", "recovery", "free_self"))
_UNSTUCK_SUCCESS_MARKERS = frozenset(("recovered", "unstuck_ok", "freed"))
_UNSTUCK_FAILURE_MARKERS = frozenset(("unstuck_failed", "still_stuck", "recovery_failed"))
_QUEUE_CONTENTION_MARKERS = frozenset(
    (
        "queue contention",
        "queue_contention",
        "queue conflict",
        "contention",
        "conflicting action",
        "conflicting_action",
    )
)
_SELF_INTERRUPTION_MARKERS = frozenset(
    (
        "self interruption",
        "self-interruption",
        "self_interruption",
        "interrupted",
        "preempted",
        "preempt",
    )
)
_DIRECTOR_FANOUT_MARKERS = frozenset(
    (
        "director fanout",
        "director_fanout",
        "fanout",
        "duplicate dispatch",
    )
)
_COMMAND_LOSS_MARKERS = frozenset(
    (
        "command loss",
        "command_loss",
        "dropped command",
        "lost command",
        "dropped",
    )
)
_TIMING_DRIFT_MARKERS = frozenset(("timing drift", "timing_drift", "drift", "late command"))
_TIMING_SIGNAL_KEYS = frozenset(
    (
        "timing",
        "queue_depth",
        "queue_contention",
        "self_interruption_count",
        "director_fanout_count",
        "dropped_commands",
        "command_loss_count",
        "timing_drift",
        "conflicts",
        "conflicting_action_ids",
        "last_command_ts_ms",
    )
)
_LIFECYCLE_COMMANDS = frozenset(
    (
        "move",
        "searchforblock",
        "nearbyblocks",
        "placehere",
        "planandbuild",
        "buildfromplan",
    )
)
_SIGNAL_TEXT_KEYS = frozenset(
    ("detail", "error", "failure_class", "last_error", "message", "reason", "status_detail")
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
class LifecycleSignals:
    """Derived death-loop, spawn-safety, and unstuck signals for one command."""

    death_count: int = 0
    deaths: tuple[Mapping[str, Any], ...] = ()
    death_loop: bool = False
    respawns: int = 0
    safe_spawn: bool | None = None
    unsafe_spawn_count: int = 0
    unsafe_spawn_reasons: tuple[str, ...] = ()
    stuck: bool = False
    stuck_events: int = 0
    unstuck_attempts: int = 0
    unstuck_succeeded: bool | None = None
    unstuck_failed: bool = False
    last_pose: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "death_count", max(0, int(self.death_count)))
        object.__setattr__(self, "deaths", _coerce_mapping_tuple(self.deaths))
        object.__setattr__(self, "death_loop", bool(self.death_loop))
        object.__setattr__(self, "respawns", max(0, int(self.respawns)))
        if self.safe_spawn is not None and not isinstance(self.safe_spawn, bool):
            raise ValueError("safe_spawn must be a bool or None")
        object.__setattr__(self, "unsafe_spawn_count", max(0, int(self.unsafe_spawn_count)))
        object.__setattr__(
            self,
            "unsafe_spawn_reasons",
            tuple(str(reason) for reason in self.unsafe_spawn_reasons if str(reason).strip()),
        )
        object.__setattr__(self, "stuck", bool(self.stuck))
        object.__setattr__(self, "stuck_events", max(0, int(self.stuck_events)))
        object.__setattr__(self, "unstuck_attempts", max(0, int(self.unstuck_attempts)))
        if self.unstuck_succeeded is not None and not isinstance(self.unstuck_succeeded, bool):
            raise ValueError("unstuck_succeeded must be a bool or None")
        object.__setattr__(self, "unstuck_failed", bool(self.unstuck_failed))
        pose = dict(self.last_pose) if isinstance(self.last_pose, Mapping) else None
        object.__setattr__(self, "last_pose", pose)

    def to_dict(self) -> dict[str, Any]:
        return {
            "death_count": self.death_count,
            "deaths": [dict(death) for death in self.deaths],
            "death_loop": self.death_loop,
            "respawns": self.respawns,
            "safe_spawn": self.safe_spawn,
            "unsafe_spawn_count": self.unsafe_spawn_count,
            "unsafe_spawn_reasons": list(self.unsafe_spawn_reasons),
            "stuck": self.stuck,
            "stuck_events": self.stuck_events,
            "unstuck_attempts": self.unstuck_attempts,
            "unstuck_succeeded": self.unstuck_succeeded,
            "unstuck_failed": self.unstuck_failed,
            "last_pose": dict(self.last_pose) if self.last_pose is not None else None,
        }


@dataclass(frozen=True, slots=True)
class TimingSignals:
    """Derived queue and timing signals for one multi-agent eval case."""

    agent_id: str
    queue_depth: int = 0
    queue_contention: bool = False
    self_interruption_count: int = 0
    director_fanout_count: int = 0
    dropped_commands: int = 0
    command_loss_count: int = 0
    latency_ms: int = 0
    conflicting_action_ids: tuple[str, ...] = ()
    last_command_ts_ms: int | None = None

    def __post_init__(self) -> None:
        agent_id = str(self.agent_id).strip()
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "queue_depth", max(0, int(self.queue_depth)))
        object.__setattr__(self, "queue_contention", bool(self.queue_contention))
        object.__setattr__(
            self,
            "self_interruption_count",
            max(0, int(self.self_interruption_count)),
        )
        object.__setattr__(
            self,
            "director_fanout_count",
            max(0, int(self.director_fanout_count)),
        )
        object.__setattr__(self, "dropped_commands", max(0, int(self.dropped_commands)))
        object.__setattr__(
            self,
            "command_loss_count",
            max(0, int(self.command_loss_count)),
        )
        object.__setattr__(self, "latency_ms", max(0, int(self.latency_ms)))
        object.__setattr__(
            self,
            "conflicting_action_ids",
            tuple(
                dict.fromkeys(
                    str(action_id) for action_id in self.conflicting_action_ids if action_id
                )
            ),
        )
        if self.last_command_ts_ms is not None:
            object.__setattr__(
                self,
                "last_command_ts_ms",
                max(0, int(self.last_command_ts_ms)),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "queue_depth": self.queue_depth,
            "queue_contention": self.queue_contention,
            "self_interruption_count": self.self_interruption_count,
            "director_fanout_count": self.director_fanout_count,
            "dropped_commands": self.dropped_commands,
            "command_loss_count": self.command_loss_count,
            "latency_ms": self.latency_ms,
            "conflicting_action_ids": list(self.conflicting_action_ids),
            "last_command_ts_ms": self.last_command_ts_ms,
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
    agent_id: str | None = None
    error: str | None = None
    eval_category: str | None = None
    pathfinding: PathfindingSignals | Mapping[str, Any] | None = None
    inventory: InventoryDelta | Mapping[str, Any] | None = None
    block_mutation: BlockMutation | Mapping[str, Any] | None = None
    lifecycle: LifecycleSignals | Mapping[str, Any] | None = None
    timing: TimingSignals | Mapping[str, Any] | None = None

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
        agent_id = self.agent_id or _agent_id_from_context(self.params, self.final_state)
        agent_id = str(agent_id).strip() if agent_id is not None else None
        object.__setattr__(self, "agent_id", agent_id or None)

        lifecycle = self.lifecycle
        if isinstance(lifecycle, Mapping):
            lifecycle = _coerce_lifecycle_signals(lifecycle)
        elif lifecycle is None:
            lifecycle = derive_lifecycle_signals(
                command_name,
                self.outcome_class,
                self.action_events,
                params=self.params,
                final_state=self.final_state,
            )

        timing = self.timing
        if isinstance(timing, Mapping):
            timing = _coerce_timing_signals(timing)
        elif timing is None and agent_id:
            timing = derive_timing_signals(
                agent_id,
                self.action_events,
                params=self.params,
                final_state=self.final_state,
            )

        eval_category = self.eval_category or classify_eval_category(
            command_name,
            self.outcome_class,
            self.error,
            self.final_state,
            params=self.params,
        )
        if timing is not None:
            eval_category = EvalCategory.MULTI_AGENT_TIMING
        eval_category = _apply_lifecycle_category(command_name, eval_category, lifecycle)
        if eval_category not in EvalCategory.ALL:
            allowed = ", ".join(EvalCategory.ALL)
            raise ValueError(f"eval_category must be one of: {allowed}")
        object.__setattr__(self, "eval_category", eval_category)
        object.__setattr__(self, "lifecycle", lifecycle)
        object.__setattr__(self, "timing", timing)

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
            "agent_id": self.agent_id,
            "action_events": [event.to_dict() for event in self.action_events],
            "outcome_class": self.outcome_class,
            "final_state": dict(self.final_state),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "eval_category": self.eval_category,
            "pathfinding": self.pathfinding.to_dict() if self.pathfinding else None,
            "inventory": self.inventory.to_dict() if self.inventory else None,
            "block_mutation": self.block_mutation.to_dict() if self.block_mutation else None,
            "lifecycle": self.lifecycle.to_dict() if self.lifecycle else None,
            "timing": self.timing.to_dict() if self.timing else None,
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
    def lifecycle_summary(self) -> dict[str, int]:
        summary = {
            "cases": 0,
            "deaths": 0,
            "death_loops": 0,
            "safe_spawns": 0,
            "unsafe_spawns": 0,
            "stuck_events": 0,
            "unstuck_attempts": 0,
            "unstuck_successes": 0,
            "unstuck_failures": 0,
        }
        for result in self.case_results:
            lifecycle = result.lifecycle
            if lifecycle is None:
                continue
            summary["cases"] += 1
            summary["deaths"] += lifecycle.death_count
            if lifecycle.death_loop:
                summary["death_loops"] += 1
            if lifecycle.safe_spawn is True:
                summary["safe_spawns"] += 1
            if lifecycle.safe_spawn is False or lifecycle.unsafe_spawn_count:
                summary["unsafe_spawns"] += max(1, lifecycle.unsafe_spawn_count)
            summary["stuck_events"] += lifecycle.stuck_events
            summary["unstuck_attempts"] += lifecycle.unstuck_attempts
            if lifecycle.unstuck_succeeded is True:
                summary["unstuck_successes"] += 1
            if lifecycle.unstuck_failed:
                summary["unstuck_failures"] += 1
        return summary

    @property
    def timing_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "cases": 0,
            "agents": 0,
            "contention": 0,
            "interruptions": 0,
            "fanouts": 0,
            "dropped": 0,
            "command_loss": 0,
            "timing_drift": 0,
            "failure_classes": {failure: 0 for failure in MultiAgentTimingFailure.ALL},
            "per_agent": {},
        }
        per_agent: dict[str, dict[str, Any]] = {}
        for result in self.case_results:
            timing = result.timing
            if timing is None:
                continue
            summary["cases"] += 1
            agent_metrics = per_agent.setdefault(
                timing.agent_id,
                {
                    "cases": 0,
                    "contention": 0,
                    "interruptions": 0,
                    "fanouts": 0,
                    "dropped": 0,
                    "command_loss": 0,
                    "timing_drift": 0,
                    "max_queue_depth": 0,
                    "latency_ms_total": 0,
                    "last_command_ts_ms": None,
                    "failure_classes": {failure: 0 for failure in MultiAgentTimingFailure.ALL},
                },
            )
            agent_metrics["cases"] += 1
            agent_metrics["latency_ms_total"] += timing.latency_ms
            agent_metrics["max_queue_depth"] = max(
                agent_metrics["max_queue_depth"],
                timing.queue_depth,
            )
            if timing.last_command_ts_ms is not None:
                agent_metrics["last_command_ts_ms"] = max(
                    agent_metrics["last_command_ts_ms"] or 0,
                    timing.last_command_ts_ms,
                )

            if timing.queue_contention:
                summary["contention"] += 1
                agent_metrics["contention"] += 1
            summary["interruptions"] += timing.self_interruption_count
            agent_metrics["interruptions"] += timing.self_interruption_count
            summary["fanouts"] += timing.director_fanout_count
            agent_metrics["fanouts"] += timing.director_fanout_count
            summary["dropped"] += timing.dropped_commands
            agent_metrics["dropped"] += timing.dropped_commands
            summary["command_loss"] += timing.command_loss_count
            agent_metrics["command_loss"] += timing.command_loss_count

            failure_class = classify_timing_failure(timing, params=result.params)
            summary["failure_classes"][failure_class] += 1
            agent_metrics["failure_classes"][failure_class] += 1
            if failure_class == MultiAgentTimingFailure.TIMING_DRIFT:
                summary["timing_drift"] += 1
                agent_metrics["timing_drift"] += 1

        summary["agents"] = len(per_agent)
        summary["per_agent"] = {
            agent_id: _finalize_agent_timing_metrics(metrics)
            for agent_id, metrics in sorted(per_agent.items())
        }
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
            "lifecycle_summary": self.lifecycle_summary,
            "timing_summary": self.timing_summary,
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
    *,
    params: Mapping[str, Any] | None = None,
) -> str:
    """Classify the live-eval behavior category for one command outcome."""

    detail = _normalize_detail(reason, _signal_text(final_state), _signal_text(params))
    if _has_multi_agent_context(params, final_state) and (
        _has_timing_signal(detail, final_state) or _has_timing_signal(detail, params)
    ):
        return EvalCategory.MULTI_AGENT_TIMING

    lifecycle = derive_lifecycle_signals(
        command_name,
        outcome_class,
        (),
        params=None,
        final_state=_state_with_detail(final_state, detail),
    )
    lifecycle_category = _apply_lifecycle_category(
        command_name,
        EvalCategory.OTHER,
        lifecycle,
    )
    if lifecycle_category in (EvalCategory.DEATH_LOOP, EvalCategory.SAFE_SPAWN):
        return lifecycle_category
    if lifecycle_category == EvalCategory.STUCK_UNSTUCK and _has_explicit_unstuck_signal(
        detail,
        final_state,
    ):
        return lifecycle_category
    if lifecycle_category == EvalCategory.STUCK_UNSTUCK and _has_explicit_stuck_events(
        final_state,
    ):
        return lifecycle_category

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
    if lifecycle_category == EvalCategory.STUCK_UNSTUCK:
        return EvalCategory.STUCK_UNSTUCK
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


def derive_lifecycle_signals(
    command_name: object,
    outcome_class: object,
    action_events: Sequence[ActionEvent],
    *,
    params: Mapping[str, Any] | None = None,
    final_state: Mapping[str, Any] | None = None,
) -> LifecycleSignals | None:
    """Derive death-loop, spawn-safety, and unstuck signals for one eval case."""

    state = final_state if isinstance(final_state, Mapping) else {}
    raw_params = params if isinstance(params, Mapping) else {}
    normalized_command = _normalize_command_name(command_name)
    event_details: list[str] = []
    state_detail = _normalize_detail(_signal_text(state), _signal_text(raw_params))
    death_records: list[Mapping[str, Any]] = []
    event_deaths = 0
    explicit_death_count = _count_signal(state, ("death_count", "deaths"))
    respawn_events = 0
    explicit_respawns = _count_signal(state, ("respawns", "respawn_count"))
    stuck_event_count = _count_signal(state, ("stuck_events",))
    unstuck_attempt_events = _count_signal(state, ("unstuck_attempts",))
    unsafe_spawn_count = _count_signal(state, ("unsafe_spawn_count",))
    unsafe_spawn_reasons: list[str] = []
    last_pose = _extract_final_pose(state)
    unstuck_success_marker = _truthy_signal(state, "unstuck_succeeded") or _truthy_signal(
        state,
        "unstuck_success",
    )
    unstuck_failure_marker = _truthy_signal(state, "unstuck_failed") or _truthy_signal(
        state,
        "unstuck_failure",
    )

    for raw_event in action_events:
        kind, payload = _event_parts(raw_event)
        detail = _normalize_detail(kind, _signal_text(payload))
        if detail:
            event_details.append(detail)
        if last_pose is None:
            last_pose = _extract_final_pose(payload)

        payload_deaths = _death_records_from_payload(payload)
        if payload_deaths:
            death_records.extend(payload_deaths)
            event_deaths += len(payload_deaths)
        elif _has_marker(detail, _DEATH_MARKERS) or _truthy_signal(payload, "death"):
            death_records.append(_event_record(kind, payload))
            event_deaths += 1
        explicit_death_count = max(
            explicit_death_count,
            _count_signal(payload, ("death_count", "deaths")),
        )

        if _has_marker(detail, _RESPAWN_MARKERS) or _truthy_signal(payload, "respawn"):
            respawn_events += 1
        explicit_respawns = max(
            explicit_respawns,
            _count_signal(payload, ("respawns", "respawn_count")),
        )

        if _has_marker(detail, _STUCK_MARKERS) or _truthy_signal(payload, "stuck"):
            stuck_event_count += 1
        stuck_event_count = max(stuck_event_count, _count_signal(payload, ("stuck_events",)))

        if _has_marker(detail, _UNSTUCK_ATTEMPT_MARKERS):
            unstuck_attempt_events += 1
        unstuck_attempt_events = max(
            unstuck_attempt_events,
            _count_signal(payload, ("unstuck_attempts",)),
        )
        if _has_marker(detail, _UNSTUCK_SUCCESS_MARKERS) or _truthy_signal(
            payload,
            "unstuck_succeeded",
        ):
            unstuck_success_marker = True
        if _has_marker(detail, _UNSTUCK_FAILURE_MARKERS) or _truthy_signal(
            payload,
            "unstuck_failed",
        ):
            unstuck_failure_marker = True

        event_unsafe_count, event_unsafe_reasons = _unsafe_spawn_signals(detail, payload)
        unsafe_spawn_count += event_unsafe_count
        unsafe_spawn_reasons.extend(event_unsafe_reasons)

    final_state_deaths = _death_records_from_payload(state)
    if final_state_deaths:
        death_records.extend(final_state_deaths)
    combined_detail = _normalize_detail(state_detail, *event_details)
    death_count = max(explicit_death_count, len(death_records))
    if death_count == 0 and _has_marker(combined_detail, _DEATH_MARKERS):
        death_count = 1
    death_loop = (
        death_count >= 2
        or event_deaths >= 2
        or _truthy_signal(state, "death_loop")
        or _has_marker(combined_detail, frozenset(("death loop", "death_loop")))
    )
    respawns = max(explicit_respawns, respawn_events)
    if respawns == 0 and _has_marker(combined_detail, _RESPAWN_MARKERS):
        respawns = 1

    state_unsafe_count, state_unsafe_reasons = _unsafe_spawn_signals(combined_detail, state)
    unsafe_spawn_count += state_unsafe_count
    unsafe_spawn_reasons.extend(state_unsafe_reasons)
    safe_spawn = _safe_spawn_signal(state, combined_detail)
    if safe_spawn is None and respawns > 0 and unsafe_spawn_count == 0:
        safe_spawn = True
    if unsafe_spawn_count > 0:
        safe_spawn = False

    pathfinding_stuck = _has_marker(combined_detail, _STUCK_MARKERS) or _truthy_signal(
        state,
        "stuck",
    )
    stuck = pathfinding_stuck or stuck_event_count > 0 or unstuck_attempt_events > 0
    if stuck and stuck_event_count == 0:
        stuck_event_count = 1

    unstuck_attempts = unstuck_attempt_events
    if unstuck_attempts == 0 and _has_marker(combined_detail, _UNSTUCK_ATTEMPT_MARKERS):
        unstuck_attempts = 1
    if _has_marker(combined_detail, _UNSTUCK_SUCCESS_MARKERS):
        unstuck_success_marker = True
    if _has_marker(combined_detail, _UNSTUCK_FAILURE_MARKERS):
        unstuck_failure_marker = True
    if unstuck_success_marker:
        unstuck_succeeded: bool | None = True
    elif unstuck_failure_marker or (unstuck_attempts > 0 and stuck):
        unstuck_succeeded = False
    else:
        unstuck_succeeded = None
    unstuck_failed = bool(
        unstuck_failure_marker or (unstuck_attempts > 0 and unstuck_succeeded is not True)
    )

    observed = any(
        (
            death_count,
            death_loop,
            respawns,
            safe_spawn is not None,
            unsafe_spawn_count,
            stuck,
            stuck_event_count,
            unstuck_attempts,
            unstuck_succeeded is not None,
            unstuck_failed,
        )
    )
    if not observed and normalized_command not in _LIFECYCLE_COMMANDS:
        return None

    del outcome_class
    return LifecycleSignals(
        death_count=death_count,
        deaths=tuple(death_records),
        death_loop=death_loop,
        respawns=respawns,
        safe_spawn=safe_spawn,
        unsafe_spawn_count=unsafe_spawn_count,
        unsafe_spawn_reasons=tuple(dict.fromkeys(unsafe_spawn_reasons)),
        stuck=stuck,
        stuck_events=stuck_event_count,
        unstuck_attempts=unstuck_attempts,
        unstuck_succeeded=unstuck_succeeded,
        unstuck_failed=unstuck_failed,
        last_pose=last_pose,
    )


def derive_timing_signals(
    agent_id: object,
    action_events: Sequence[ActionEvent],
    *,
    params: Mapping[str, Any] | None = None,
    final_state: Mapping[str, Any] | None = None,
) -> TimingSignals | None:
    """Derive queue contention and command-loss signals for one agent case."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return None

    state = final_state if isinstance(final_state, Mapping) else {}
    raw_params = params if isinstance(params, Mapping) else {}
    event_details: list[str] = []
    queue_depth = max(
        _max_int_signal(state, ("queue_depth",)),
        _max_int_signal(raw_params, ("queue_depth",)),
    )
    self_interruption_count = max(
        _count_signal(state, ("self_interruption_count", "self_interruptions")),
        _count_signal(raw_params, ("self_interruption_count", "self_interruptions")),
    )
    director_fanout_count = max(
        _count_signal(state, ("director_fanout_count", "director_fanouts")),
        _count_signal(raw_params, ("director_fanout_count", "director_fanouts")),
    )
    dropped_commands = max(
        _count_signal(state, ("dropped_commands", "dropped")),
        _count_signal(raw_params, ("dropped_commands", "dropped")),
    )
    command_loss_count = max(
        _count_signal(state, ("command_loss_count", "command_loss", "lost_commands")),
        _count_signal(raw_params, ("command_loss_count", "command_loss", "lost_commands")),
    )
    latency_ms = max(
        _max_int_signal(state, ("latency_ms", "elapsed_ms", "duration_ms")),
        _max_int_signal(raw_params, ("latency_ms", "elapsed_ms", "duration_ms")),
    )
    last_command_ts_ms = _max_optional_int_signal(
        state,
        ("last_command_ts_ms", "scheduled_ts_ms", "command_ts_ms"),
    )
    params_last_command = _max_optional_int_signal(
        raw_params,
        ("last_command_ts_ms", "scheduled_ts_ms", "command_ts_ms"),
    )
    if params_last_command is not None:
        last_command_ts_ms = max(last_command_ts_ms or 0, params_last_command)

    conflicting_action_ids: list[str] = []
    conflicting_action_ids.extend(_action_ids_from_context(state))
    conflicting_action_ids.extend(_action_ids_from_context(raw_params))

    queued_events = 0
    dropped_events = 0
    interruption_events = 0
    fanout_events = 0
    for raw_event in action_events:
        kind, payload = _event_parts(raw_event)
        detail = _normalize_detail(kind, _signal_text(payload))
        if detail:
            event_details.append(detail)
        queue_depth = max(queue_depth, _max_int_signal(payload, ("queue_depth",)))
        self_interruption_count = max(
            self_interruption_count,
            _count_signal(payload, ("self_interruption_count", "self_interruptions")),
        )
        director_fanout_count = max(
            director_fanout_count,
            _count_signal(payload, ("director_fanout_count", "director_fanouts")),
        )
        dropped_commands = max(
            dropped_commands,
            _count_signal(payload, ("dropped_commands", "dropped")),
        )
        command_loss_count = max(
            command_loss_count,
            _count_signal(payload, ("command_loss_count", "command_loss", "lost_commands")),
        )
        latency_ms = max(latency_ms, _max_int_signal(payload, ("latency_ms",)))
        if isinstance(raw_event, ActionEvent):
            last_command_ts_ms = max(last_command_ts_ms or 0, raw_event.ts_ms)
        event_ts = _max_optional_int_signal(payload, ("last_command_ts_ms", "command_ts_ms"))
        if event_ts is not None:
            last_command_ts_ms = max(last_command_ts_ms or 0, event_ts)
        conflicting_action_ids.extend(_action_ids_from_context(payload))

        if kind == "queued":
            queued_events += 1
        if kind == "dropped":
            dropped_events += 1
        if kind in {"interrupted", "preempted"}:
            interruption_events += 1
        if kind == "fanout":
            fanout_events += 1

    combined_detail = _normalize_detail(
        _signal_text(state), _signal_text(raw_params), *event_details
    )
    if dropped_events:
        dropped_commands = max(dropped_commands, dropped_events)
        command_loss_count = max(command_loss_count, dropped_events)
    if interruption_events:
        self_interruption_count = max(self_interruption_count, interruption_events)
    if fanout_events:
        director_fanout_count = max(director_fanout_count, fanout_events)
    if _has_marker(combined_detail, _SELF_INTERRUPTION_MARKERS):
        self_interruption_count = max(self_interruption_count, 1)
    if _has_marker(combined_detail, _DIRECTOR_FANOUT_MARKERS):
        director_fanout_count = max(director_fanout_count, 1)
    if _has_marker(combined_detail, _COMMAND_LOSS_MARKERS):
        dropped_commands = max(dropped_commands, 1)
        command_loss_count = max(command_loss_count, dropped_commands)

    queue_threshold = _coerce_int(raw_params.get("queue_contention_threshold"))
    if queue_threshold is None:
        queue_threshold = 1
    queue_contention = (
        queue_depth > queue_threshold
        or bool(conflicting_action_ids)
        or _truthy_signal(state, "queue_contention")
        or _truthy_signal(raw_params, "queue_contention")
        or _has_marker(combined_detail, _QUEUE_CONTENTION_MARKERS)
    )
    if queued_events and queue_depth == 0:
        queue_depth = queued_events

    observed = any(
        (
            _has_multi_agent_context(raw_params, state),
            queue_depth,
            queue_contention,
            self_interruption_count,
            director_fanout_count,
            dropped_commands,
            command_loss_count,
            latency_ms,
            conflicting_action_ids,
            last_command_ts_ms is not None,
        )
    )
    if not observed:
        return None

    return TimingSignals(
        agent_id=normalized_agent_id,
        queue_depth=queue_depth,
        queue_contention=queue_contention,
        self_interruption_count=self_interruption_count,
        director_fanout_count=director_fanout_count,
        dropped_commands=dropped_commands,
        command_loss_count=command_loss_count,
        latency_ms=latency_ms,
        conflicting_action_ids=tuple(conflicting_action_ids),
        last_command_ts_ms=last_command_ts_ms,
    )


def classify_timing_failure(
    timing: TimingSignals,
    *,
    params: Mapping[str, Any] | None = None,
) -> str:
    """Classify one timing signal set into a primary stable failure class."""

    if timing.command_loss_count or timing.dropped_commands:
        return MultiAgentTimingFailure.COMMAND_LOSS
    if timing.queue_contention:
        return MultiAgentTimingFailure.QUEUE_CONTENTION
    if timing.self_interruption_count:
        return MultiAgentTimingFailure.SELF_INTERRUPTION
    if timing.director_fanout_count:
        return MultiAgentTimingFailure.DIRECTOR_FANOUT
    raw_params = params if isinstance(params, Mapping) else {}
    max_latency_ms = _coerce_int(raw_params.get("max_latency_ms"))
    if max_latency_ms is not None and timing.latency_ms > max_latency_ms:
        return MultiAgentTimingFailure.TIMING_DRIFT
    return MultiAgentTimingFailure.NONE


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


def _coerce_lifecycle_signals(raw: Mapping[str, Any]) -> LifecycleSignals:
    safe_spawn = raw.get("safe_spawn")
    unstuck_succeeded = raw.get("unstuck_succeeded")
    return LifecycleSignals(
        death_count=_coerce_int(raw.get("death_count")) or 0,
        deaths=_raw_sequence(raw.get("deaths")),
        death_loop=_coerce_bool(raw.get("death_loop")),
        respawns=_coerce_int(raw.get("respawns")) or 0,
        safe_spawn=safe_spawn if isinstance(safe_spawn, bool) or safe_spawn is None else None,
        unsafe_spawn_count=_coerce_int(raw.get("unsafe_spawn_count")) or 0,
        unsafe_spawn_reasons=tuple(
            str(reason) for reason in _raw_sequence(raw.get("unsafe_spawn_reasons"))
        ),
        stuck=_coerce_bool(raw.get("stuck")),
        stuck_events=_coerce_int(raw.get("stuck_events")) or 0,
        unstuck_attempts=_coerce_int(raw.get("unstuck_attempts")) or 0,
        unstuck_succeeded=unstuck_succeeded
        if isinstance(unstuck_succeeded, bool) or unstuck_succeeded is None
        else None,
        unstuck_failed=_coerce_bool(raw.get("unstuck_failed")),
        last_pose=raw.get("last_pose") if isinstance(raw.get("last_pose"), Mapping) else None,
    )


def _coerce_timing_signals(raw: Mapping[str, Any]) -> TimingSignals:
    return TimingSignals(
        agent_id=str(raw.get("agent_id") or ""),
        queue_depth=_coerce_int(raw.get("queue_depth")) or 0,
        queue_contention=_coerce_bool(raw.get("queue_contention")),
        self_interruption_count=_coerce_int(raw.get("self_interruption_count")) or 0,
        director_fanout_count=_coerce_int(raw.get("director_fanout_count")) or 0,
        dropped_commands=_coerce_int(raw.get("dropped_commands")) or 0,
        command_loss_count=_coerce_int(raw.get("command_loss_count")) or 0,
        latency_ms=_coerce_int(raw.get("latency_ms")) or 0,
        conflicting_action_ids=tuple(
            str(action_id) for action_id in _raw_sequence(raw.get("conflicting_action_ids"))
        ),
        last_command_ts_ms=_coerce_int(raw.get("last_command_ts_ms")),
    )


def _apply_lifecycle_category(
    command_name: object,
    eval_category: str,
    lifecycle: LifecycleSignals | None,
) -> str:
    if eval_category == EvalCategory.MULTI_AGENT_TIMING:
        return eval_category
    if lifecycle is None:
        return eval_category
    if lifecycle.death_loop:
        return EvalCategory.DEATH_LOOP
    if lifecycle.respawns or lifecycle.safe_spawn is not None or lifecycle.unsafe_spawn_count:
        return EvalCategory.SAFE_SPAWN
    if (
        lifecycle.unstuck_attempts
        or lifecycle.unstuck_succeeded is not None
        or lifecycle.unstuck_failed
    ):
        return EvalCategory.STUCK_UNSTUCK
    if lifecycle.stuck and eval_category == EvalCategory.OTHER:
        return EvalCategory.STUCK_UNSTUCK
    del command_name
    return eval_category


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


def _event_parts(raw_event: object) -> tuple[str, Mapping[str, Any]]:
    if isinstance(raw_event, ActionEvent):
        return raw_event.kind, raw_event.payload
    if not isinstance(raw_event, Mapping):
        return "", {}
    payload = raw_event.get("payload")
    return str(raw_event.get("kind") or ""), payload if isinstance(payload, Mapping) else {}


def _event_record(kind: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
    record = dict(payload)
    if kind and "kind" not in record:
        record["kind"] = kind
    return record


def _death_records_from_payload(raw: object) -> list[Mapping[str, Any]]:
    if not isinstance(raw, Mapping):
        return []
    deaths = raw.get("deaths")
    if isinstance(deaths, Sequence) and not isinstance(deaths, (str, bytes, bytearray)):
        records: list[Mapping[str, Any]] = []
        for death in deaths:
            if isinstance(death, Mapping):
                records.append(dict(death))
            elif death is not None:
                records.append({"detail": str(death)})
        return records
    if _truthy_signal(raw, "death") or _truthy_signal(raw, "died") or _truthy_signal(raw, "dead"):
        return [dict(raw)]
    return []


def _count_signal(raw: object, keys: tuple[str, ...]) -> int:
    if not isinstance(raw, Mapping):
        return 0
    counts: list[int] = []
    wanted = {key.casefold() for key in keys}
    for key, value in raw.items():
        if str(key).casefold() in wanted:
            count = _value_count(value)
            if count is not None:
                counts.append(count)
        if isinstance(value, Mapping):
            nested = _count_signal(value, keys)
            if nested:
                counts.append(nested)
    return max(counts, default=0)


def _value_count(value: object) -> int | None:
    coerced = _coerce_int(value)
    if coerced is not None:
        return max(0, coerced)
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return len(value)
    return None


def _safe_spawn_signal(
    final_state: Mapping[str, Any],
    detail: str,
) -> bool | None:
    direct = _bool_signal(final_state, ("safe_spawn", "spawn_safe"))
    if direct is not None:
        return direct
    spawn = final_state.get("spawn")
    if isinstance(spawn, Mapping):
        spawn_direct = _bool_signal(spawn, ("safe", "spawn_safe", "safe_spawn"))
        if spawn_direct is not None:
            return spawn_direct
    if _truthy_signal(final_state, "unsafe_spawn") or _has_marker(detail, _UNSAFE_SPAWN_MARKERS):
        return False
    if _has_marker(detail, _SAFE_SPAWN_MARKERS):
        return True
    return None


def _bool_signal(raw: object, keys: tuple[str, ...]) -> bool | None:
    if not isinstance(raw, Mapping):
        return None
    wanted = {key.casefold() for key in keys}
    for key, value in raw.items():
        if str(key).casefold() not in wanted:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
    return None


def _unsafe_spawn_signals(
    detail: str,
    raw: object,
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    if isinstance(raw, Mapping):
        for key in ("unsafe_spawn_reason", "spawn_reason", "reason", "detail", "message"):
            value = raw.get(key)
            if value is not None and str(value).strip():
                value_text = str(value).strip()
                if _has_marker(value_text.casefold(), _UNSAFE_SPAWN_MARKERS):
                    reasons.append(value_text)
        spawn = raw.get("spawn")
        if isinstance(spawn, Mapping):
            nested_count, nested_reasons = _unsafe_spawn_signals(_signal_text(spawn), spawn)
            reasons.extend(nested_reasons)
            if nested_count:
                reasons.append("unsafe spawn")
        if _truthy_signal(raw, "unsafe_spawn"):
            reasons.append("unsafe_spawn")
    markers = [marker for marker in _UNSAFE_SPAWN_MARKERS if marker in detail]
    reasons.extend(markers)
    count = 1 if markers else 0
    if reasons and count == 0:
        count = 1
    return count, reasons


def _has_explicit_unstuck_signal(
    detail: str,
    final_state: Mapping[str, Any] | None,
) -> bool:
    return (
        _has_marker(detail, _UNSTUCK_ATTEMPT_MARKERS)
        or _has_marker(detail, _UNSTUCK_SUCCESS_MARKERS)
        or _has_marker(detail, _UNSTUCK_FAILURE_MARKERS)
        or _truthy_signal(final_state, "unstuck")
        or _truthy_signal(final_state, "unstuck_attempts")
        or _truthy_signal(final_state, "unstuck_succeeded")
        or _truthy_signal(final_state, "unstuck_failed")
    )


def _has_explicit_stuck_events(final_state: Mapping[str, Any] | None) -> bool:
    return _count_signal(final_state, ("stuck_events",)) > 0


def _has_multi_agent_context(
    params: Mapping[str, Any] | None,
    final_state: Mapping[str, Any] | None,
) -> bool:
    return (
        _truthy_signal(params, "multi_agent")
        or _truthy_signal(final_state, "multi_agent")
        or _has_key(params, "agent_id")
        or _has_key(final_state, "agent_id")
        or _has_key(params, "agents")
        or _has_key(final_state, "agents")
    )


def _has_timing_signal(detail: str, raw: object) -> bool:
    return (
        _has_marker(detail, _QUEUE_CONTENTION_MARKERS)
        or _has_marker(detail, _SELF_INTERRUPTION_MARKERS)
        or _has_marker(detail, _DIRECTOR_FANOUT_MARKERS)
        or _has_marker(detail, _COMMAND_LOSS_MARKERS)
        or _has_marker(detail, _TIMING_DRIFT_MARKERS)
        or _has_any_key(raw, _TIMING_SIGNAL_KEYS)
    )


def _agent_id_from_context(
    params: Mapping[str, Any],
    final_state: Mapping[str, Any],
) -> str | None:
    for raw in (params, final_state):
        value = _first_key_value(raw, ("agent_id",))
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _action_ids_from_context(raw: object) -> list[str]:
    if not isinstance(raw, Mapping):
        return []
    values: list[str] = []
    for key in (
        "conflicting_action_ids",
        "conflict_action_ids",
        "conflicting_actions",
        "conflicts",
    ):
        value = _first_key_value(raw, (key,))
        if value is None:
            continue
        if isinstance(value, Mapping):
            action_id = value.get("action_id") or value.get("id")
            if action_id:
                values.append(str(action_id))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                if isinstance(item, Mapping):
                    action_id = item.get("action_id") or item.get("id")
                    if action_id:
                        values.append(str(action_id))
                elif item is not None and str(item).strip():
                    values.append(str(item))
        elif str(value).strip():
            values.append(str(value).strip())
    return values


def _max_int_signal(raw: object, keys: tuple[str, ...]) -> int:
    value = _max_optional_int_signal(raw, keys)
    return value or 0


def _max_optional_int_signal(raw: object, keys: tuple[str, ...]) -> int | None:
    if not isinstance(raw, Mapping):
        return None
    wanted = {key.casefold() for key in keys}
    values: list[int] = []
    for key, value in raw.items():
        if str(key).casefold() in wanted:
            coerced = _coerce_int(value)
            if coerced is not None:
                values.append(max(0, coerced))
        if isinstance(value, Mapping):
            nested = _max_optional_int_signal(value, keys)
            if nested is not None:
                values.append(nested)
    return max(values) if values else None


def _has_key(raw: object, key: str) -> bool:
    return _has_any_key(raw, frozenset((key,)))


def _has_any_key(raw: object, keys: frozenset[str]) -> bool:
    if not isinstance(raw, Mapping):
        return False
    wanted = {key.casefold() for key in keys}
    for raw_key, value in raw.items():
        if str(raw_key).casefold() in wanted:
            return True
        if isinstance(value, Mapping) and _has_any_key(value, keys):
            return True
    return False


def _first_key_value(raw: object, keys: tuple[str, ...]) -> object | None:
    if not isinstance(raw, Mapping):
        return None
    wanted = {key.casefold() for key in keys}
    for raw_key, value in raw.items():
        if str(raw_key).casefold() in wanted:
            return value
        if isinstance(value, Mapping):
            nested = _first_key_value(value, keys)
            if nested is not None:
                return nested
    return None


def _finalize_agent_timing_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    cases = int(metrics.get("cases") or 0)
    latency_total = int(metrics.get("latency_ms_total") or 0)
    finalized = dict(metrics)
    finalized.pop("latency_ms_total", None)
    finalized["avg_latency_ms"] = 0 if cases == 0 else round(latency_total / cases)
    return finalized


def _state_with_detail(
    final_state: Mapping[str, Any] | None,
    detail: str,
) -> Mapping[str, Any]:
    state = dict(final_state) if isinstance(final_state, Mapping) else {}
    if detail:
        state.setdefault("status_detail", detail)
    return state


def _coerce_mapping_tuple(raw: object) -> tuple[Mapping[str, Any], ...]:
    records: list[Mapping[str, Any]] = []
    for item in _raw_sequence(raw):
        if isinstance(item, Mapping):
            records.append(dict(item))
        elif item is not None:
            records.append({"detail": str(item)})
    return tuple(records)


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

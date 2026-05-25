"""Scene-scoped build macro ownership for Minecraft Director V2."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.minecraft.director.scene_inbox import Scene

BuildMacroRole = Literal["planner_owner", "support"]
SupportRole = Literal["gather", "clear", "guard", "converse"]

DEFAULT_RETRYABLE_REASONS = frozenset(
    {
        "bridge_down",
        "bridge_unavailable",
        "materials_missing",
        "provider_failed",
        "temporary_blocked",
        "timed_out",
        "timeout",
        "tool_missing",
    }
)


class BuildMacroAssignment(BaseModel):
    """Director build macro context for one agent prompt verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: str
    plan_id: str | None = None
    owner: str | None = None
    role: BuildMacroRole
    support_role: SupportRole | None = None
    support_task: str | None = None
    reason: str
    granted: bool = False
    status: str | None = None
    cache_key: str | None = None
    objective_id: str | None = None
    phase_index: int | None = None
    phase_owner: str | None = None


class BuildMacroAcquireResult(BaseModel):
    """Result of attempting to reserve one scene build plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    granted: bool
    scene_id: str
    plan_id: str | None = None
    owner: str | None = None
    reason: str
    status: str | None = None
    cache_key: str
    support_assignments: dict[str, BuildMacroAssignment] = Field(default_factory=dict)
    objective_id: str | None = None
    phase_index: int | None = None
    phase_owner: str | None = None


class SettlementObjectiveContext(BaseModel):
    """Active multi-phase settlement build objective used by the Director gate."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    objective_id: str
    phase_index: int = 0
    description: str | None = None
    owner_agent_id: str | None = None
    status: str | None = None
    previous_owner_agent_ids: list[str] = Field(default_factory=list)
    owner_started_at_ms: int | None = None
    stale_after_ms: int | None = None
    cooldown_until_ms: int | None = None
    reassign_reason: str | None = None


@dataclass
class _ScenePlanState:
    scene_id: str
    plan_id: str
    owner_agent_id: str
    description: str
    origin: dict[str, Any]
    cache_key: str
    started_ms: int
    status: str
    support_assignments: dict[str, BuildMacroAssignment]
    result: str | None = None
    verified_blocks: int = 0
    cooldown_until_ms: int | None = None
    objective_id: str | None = None
    phase_index: int | None = None
    phase_owner: str | None = None


@dataclass
class BuildMacroScheduler:
    """Own Director-scheduled build macro plans per scene and owning agent."""

    cooldown_ms: int = 300_000
    retryable_reasons: frozenset[str] = DEFAULT_RETRYABLE_REASONS
    _scene_state: dict[str, _ScenePlanState] = field(default_factory=dict)
    _active_agent_goals: dict[tuple[str, str], str] = field(default_factory=dict)
    _pending_objective_seen_ms: dict[str, int] = field(default_factory=dict)

    def try_acquire_plan(
        self,
        *,
        scene_id: str,
        agent_id: str,
        description: str,
        origin: Mapping[str, Any] | None = None,
        scene: Scene | None = None,
        candidates: Sequence[Any] = (),
        active_objective: Mapping[str, Any] | SettlementObjectiveContext | None = None,
        plan_build_agent_allowlist: Sequence[Any] | str | None = None,
        now_ms: int | None = None,
    ) -> BuildMacroAcquireResult:
        """Reserve one active build plan for a scene if no equivalent plan owns it."""

        now = now_ms if now_ms is not None else _now_ms()
        scene_key = _text(scene_id) or "unknown-scene"
        owner = _agent_id(agent_id)
        objective = _objective_context(active_objective)
        eligible_owner_ids = _plan_build_allowed_agents(plan_build_agent_allowlist)
        phase_owner, phase_reason = self.select_phase_owner(
            active_objective=objective,
            candidates=candidates,
            fallback_owner=owner,
            plan_build_agent_allowlist=eligible_owner_ids,
            now_ms=now,
        )
        if objective is not None and phase_owner and phase_owner != owner:
            cache_desc = _objective_cache_description(objective, description)
            origin_payload = _origin_dict(origin)
            cache_key = _cache_key(scene_key, phase_owner, cache_desc, origin_payload)
            support_assignments = self.assign_support_roles(
                scene=scene,
                owner=phase_owner,
                candidates=candidates,
                scene_id=scene_key,
                plan_id=None,
                cache_key=cache_key,
                active_objective=objective,
            )
            return BuildMacroAcquireResult(
                granted=False,
                scene_id=scene_key,
                plan_id=None,
                owner=phase_owner,
                reason=phase_reason,
                status="support",
                cache_key=cache_key,
                support_assignments=support_assignments,
                objective_id=objective.objective_id,
                phase_index=objective.phase_index,
                phase_owner=phase_owner,
            )

        if phase_owner:
            owner = phase_owner
        acquisition_reason = phase_reason if objective is not None else "acquired"
        desc = _normalize_description(
            objective.description if objective and objective.description else description
        )
        origin_payload = _origin_dict(origin)
        cache_desc = _objective_cache_description(objective, desc)
        cache_key = _cache_key(scene_key, owner, cache_desc, origin_payload)
        self._expire_scene_if_ready(scene_key, now)

        support_assignments = self.assign_support_roles(
            scene=scene,
            owner=owner,
            candidates=candidates,
            scene_id=scene_key,
            plan_id=None,
            cache_key=cache_key,
            active_objective=objective,
        )

        if not _plan_build_agent_allowed(owner, eligible_owner_ids):
            return BuildMacroAcquireResult(
                granted=False,
                scene_id=scene_key,
                plan_id=None,
                owner=owner,
                reason="plan_build_agent_not_allowed",
                status="support",
                cache_key=cache_key,
                support_assignments=support_assignments,
                objective_id=objective.objective_id if objective else None,
                phase_index=objective.phase_index if objective else None,
                phase_owner=phase_owner,
            )

        existing = self._scene_state.get(scene_key)
        if (
            existing is not None
            and objective is not None
            and existing.objective_id != objective.objective_id
        ):
            self._active_agent_goals.pop((existing.owner_agent_id, existing.cache_key), None)
            self._scene_state.pop(scene_key, None)
            existing = None
        if existing is not None:
            reason = "already_owned" if existing.owner_agent_id == owner else "scene_locked"
            owner_can_resume_acquired_plan = (
                objective is not None
                and existing.owner_agent_id == owner
                and existing.status == "acquired"
                and existing.objective_id == (objective.objective_id if objective else None)
            )
            return BuildMacroAcquireResult(
                granted=owner_can_resume_acquired_plan,
                scene_id=scene_key,
                plan_id=existing.plan_id,
                owner=existing.owner_agent_id,
                reason=reason,
                status=existing.status,
                cache_key=existing.cache_key,
                support_assignments=_assignments_for_plan(
                    existing.support_assignments,
                    scene_id=scene_key,
                    owner=existing.owner_agent_id,
                    plan_id=existing.plan_id,
                    cache_key=existing.cache_key,
                    reason=reason,
                ),
                objective_id=existing.objective_id,
                phase_index=existing.phase_index,
                phase_owner=existing.phase_owner,
            )

        agent_goal = (owner, cache_key)
        active_plan_id = self._active_agent_goals.get(agent_goal)
        if active_plan_id is not None:
            return BuildMacroAcquireResult(
                granted=False,
                scene_id=scene_key,
                plan_id=active_plan_id,
                owner=owner,
                reason="agent_plan_active",
                status="active",
                cache_key=cache_key,
                support_assignments=support_assignments,
                objective_id=objective.objective_id if objective else None,
                phase_index=objective.phase_index if objective else None,
                phase_owner=phase_owner,
            )

        plan_id = (
            f"build-plan-{hashlib.sha1(cache_key.encode(), usedforsecurity=False).hexdigest()[:12]}"
        )
        support_assignments = _assignments_for_plan(
            support_assignments,
            scene_id=scene_key,
            owner=owner,
            plan_id=plan_id,
            cache_key=cache_key,
            reason="support_assignment",
        )
        self._scene_state[scene_key] = _ScenePlanState(
            scene_id=scene_key,
            plan_id=plan_id,
            owner_agent_id=owner,
            description=desc,
            origin=origin_payload,
            cache_key=cache_key,
            started_ms=now,
            status="acquired",
            support_assignments=support_assignments,
            objective_id=objective.objective_id if objective else None,
            phase_index=objective.phase_index if objective else None,
            phase_owner=phase_owner,
        )
        self._active_agent_goals[agent_goal] = plan_id
        return BuildMacroAcquireResult(
            granted=True,
            scene_id=scene_key,
            plan_id=plan_id,
            owner=owner,
            reason=acquisition_reason,
            status="acquired",
            cache_key=cache_key,
            support_assignments=support_assignments,
            objective_id=objective.objective_id if objective else None,
            phase_index=objective.phase_index if objective else None,
            phase_owner=phase_owner,
        )

    def select_phase_owner(
        self,
        *,
        active_objective: Mapping[str, Any] | SettlementObjectiveContext | None,
        candidates: Sequence[Any],
        fallback_owner: str | None = None,
        plan_build_agent_allowlist: Sequence[Any] | str | set[str] | None = None,
        now_ms: int | None = None,
    ) -> tuple[str | None, str]:
        """Resolve the effective owner for a settlement objective phase."""

        objective = _objective_context(active_objective)
        current = _agent_id(objective.owner_agent_id) if objective else None
        eligible_owner_ids = _plan_build_allowed_agents(plan_build_agent_allowlist)

        def allowed(agent_id: str | None) -> bool:
            return _plan_build_agent_allowed(agent_id, eligible_owner_ids)

        if objective is None:
            fallback = _agent_id(fallback_owner)
            if fallback and allowed(fallback):
                return fallback, "acquired"
            return None, "plan_build_no_eligible_agent"
        fallback = _agent_id(fallback_owner)
        status = (objective.status or "").strip().lower()
        if status == "pending" and objective.owner_started_at_ms is None:
            now = now_ms if now_ms is not None else _now_ms()
            first_seen = self._pending_objective_seen_ms.setdefault(objective.objective_id, now)
            owner_grace_elapsed = now - first_seen >= _pending_owner_grace_ms()
            if current and allowed(current) and not owner_grace_elapsed:
                return current, "settlement_phase_owner"
            if fallback and fallback != current and allowed(fallback):
                return fallback, "settlement_phase_owner_assigned"
        else:
            self._pending_objective_seen_ms.pop(objective.objective_id, None)
        if current and allowed(current) and not _objective_needs_reassignment(objective, now_ms):
            return current, "settlement_phase_owner"

        candidate_ids = _candidate_roles(candidates)
        excluded = {current, *(_agent_id(item) for item in objective.previous_owner_agent_ids)}
        preferred = _preferred_phase_owners(candidates, candidate_ids)
        for candidate_id in preferred:
            if candidate_id and candidate_id not in excluded and allowed(candidate_id):
                return candidate_id, (
                    "settlement_phase_owner_reassigned"
                    if current
                    else "settlement_phase_owner_assigned"
                )
        for candidate_id in preferred:
            if candidate_id and candidate_id != current and allowed(candidate_id):
                return candidate_id, "settlement_phase_owner_reassigned"
        if current and allowed(current):
            return current, "settlement_phase_owner"
        if fallback and allowed(fallback):
            return fallback, "settlement_phase_owner_assigned"
        return None, "plan_build_no_eligible_agent"

    def mark_started(self, scene_id: str, plan_id: str, *, now_ms: int | None = None) -> bool:
        """Mark a reserved scene plan as executing."""

        del now_ms
        state = self._scene_state.get(_text(scene_id) or "")
        if state is None or state.plan_id != plan_id:
            return False
        state.status = "started"
        return True

    def mark_completed(
        self,
        scene_id: str,
        plan_id: str,
        *,
        result: str = "",
        verified_blocks: int = 0,
        now_ms: int | None = None,
    ) -> bool:
        """Complete a scene plan and hold its scene cooldown."""

        now = now_ms if now_ms is not None else _now_ms()
        state = self._scene_state.get(_text(scene_id) or "")
        if state is None or state.plan_id != plan_id:
            return False
        state.status = "completed"
        state.result = result
        state.verified_blocks = max(0, int(verified_blocks))
        state.cooldown_until_ms = now + max(0, self.cooldown_ms)
        self._active_agent_goals.pop((state.owner_agent_id, state.cache_key), None)
        return True

    def mark_failed(
        self,
        scene_id: str,
        plan_id: str,
        *,
        result: str = "",
        reason: str | None = None,
        retryable: bool | None = None,
        verified_blocks: int = 0,
        now_ms: int | None = None,
    ) -> bool:
        """Record a plan failure, releasing only structured retryable failures."""

        now = now_ms if now_ms is not None else _now_ms()
        scene_key = _text(scene_id) or ""
        state = self._scene_state.get(scene_key)
        if state is None or state.plan_id != plan_id:
            return False
        failure_reason = _failure_reason(reason, result)
        is_retryable = (
            retryable if retryable is not None else failure_reason in self.retryable_reasons
        )
        self._active_agent_goals.pop((state.owner_agent_id, state.cache_key), None)
        if is_retryable:
            self._scene_state.pop(scene_key, None)
            return True
        state.status = "failed"
        state.result = result
        state.verified_blocks = max(0, int(verified_blocks))
        state.cooldown_until_ms = now + max(0, self.cooldown_ms)
        return True

    def assign_support_roles(
        self,
        *,
        scene: Scene | None,
        owner: str,
        candidates: Sequence[Any] = (),
        scene_id: str | None = None,
        plan_id: str | None = None,
        cache_key: str | None = None,
        active_objective: Mapping[str, Any] | SettlementObjectiveContext | None = None,
    ) -> dict[str, BuildMacroAssignment]:
        """Assign non-owner scene agents normal support roles."""

        scene_key = scene.scene_id if scene is not None else (_text(scene_id) or "unknown-scene")
        objective = _objective_context(active_objective)
        agent_roles = _candidate_roles(candidates)
        agent_ids = set(agent_roles)
        if scene is not None:
            agent_ids.update(scene.participants)
            agent_ids.update(scene.observers)
        assignments: dict[str, BuildMacroAssignment] = {}
        for index, agent_id in enumerate(sorted(agent_ids)):
            canonical = _agent_id(agent_id)
            if not canonical or canonical == owner:
                continue
            support_role = _support_role(canonical, agent_roles.get(canonical), index)
            assignments[canonical] = BuildMacroAssignment(
                scene_id=scene_key,
                plan_id=plan_id,
                owner=owner,
                role="support",
                support_role=support_role,
                support_task=_support_task(support_role, owner),
                reason="support_assignment",
                granted=False,
                status="support",
                cache_key=cache_key,
                objective_id=objective.objective_id if objective else None,
                phase_index=objective.phase_index if objective else None,
                phase_owner=owner if objective else None,
            )
        return assignments

    def active_plan(self, scene_id: str) -> BuildMacroAcquireResult | None:
        """Return the current plan lock for tests and monitor adapters."""

        state = self._scene_state.get(_text(scene_id) or "")
        if state is None:
            return None
        return BuildMacroAcquireResult(
            granted=False,
            scene_id=state.scene_id,
            plan_id=state.plan_id,
            owner=state.owner_agent_id,
            reason="active",
            status=state.status,
            cache_key=state.cache_key,
            support_assignments=state.support_assignments,
            objective_id=state.objective_id,
            phase_index=state.phase_index,
            phase_owner=state.phase_owner,
        )

    def _expire_scene_if_ready(self, scene_id: str, now_ms: int) -> None:
        state = self._scene_state.get(scene_id)
        if state is None or state.cooldown_until_ms is None:
            return
        if now_ms >= state.cooldown_until_ms:
            self._scene_state.pop(scene_id, None)


def _assignments_for_plan(
    assignments: Mapping[str, BuildMacroAssignment],
    *,
    scene_id: str,
    owner: str,
    plan_id: str | None,
    cache_key: str | None,
    reason: str,
) -> dict[str, BuildMacroAssignment]:
    return {
        agent_id: assignment.model_copy(
            update={
                "scene_id": scene_id,
                "owner": owner,
                "plan_id": plan_id,
                "cache_key": cache_key,
                "reason": reason if assignment.role == "support" else assignment.reason,
                "phase_owner": owner if assignment.objective_id else assignment.phase_owner,
            }
        )
        for agent_id, assignment in assignments.items()
    }


def _candidate_roles(candidates: Sequence[Any]) -> dict[str, str | None]:
    roles: dict[str, str | None] = {}
    for candidate in candidates:
        if isinstance(candidate, str):
            roles[_agent_id(candidate)] = None
            continue
        agent_id = _agent_id(getattr(candidate, "agent_id", None))
        if not agent_id and isinstance(candidate, Mapping):
            agent_id = _agent_id(candidate.get("agent_id"))
        if not agent_id:
            continue
        role = getattr(candidate, "role", None)
        if role is None and isinstance(candidate, Mapping):
            role = candidate.get("role")
        roles[agent_id] = str(role) if role else None
    return roles


def _support_role(agent_id: str, role: str | None, index: int) -> SupportRole:
    lowered = f"{agent_id} {role or ''}".lower()
    if any(token in lowered for token in ("sentinel", "guard", "safety", "moderator")):
        return "guard"
    if any(token in lowered for token in ("explorer", "runner", "gather", "resource")):
        return "gather"
    if any(token in lowered for token in ("builder", "architect", "engineer", "maker")):
        return "clear"
    if any(token in lowered for token in ("host", "analyst", "facilitator")):
        return "converse"
    return ("gather", "clear", "guard", "converse")[index % 4]


def _support_task(role: SupportRole, owner: str) -> str:
    if role == "gather":
        return f"Gather nearby starter materials for {owner}'s build plan."
    if role == "clear":
        return f"Clear obvious obstructions near {owner}'s build area without planning a duplicate build."
    if role == "guard":
        return f"Watch for mobs, hazards, or blocked paths while {owner} owns the build plan."
    return f"Keep the scene coordinated in chat while {owner} handles the build plan."


def _objective_context(
    value: Mapping[str, Any] | SettlementObjectiveContext | None,
) -> SettlementObjectiveContext | None:
    if value is None:
        return None
    if isinstance(value, SettlementObjectiveContext):
        return value
    try:
        return SettlementObjectiveContext.model_validate(value)
    except ValueError:
        return None


def _objective_cache_description(
    objective: SettlementObjectiveContext | None,
    description: str,
) -> str:
    if objective is None:
        return _normalize_description(description)
    return _normalize_description(
        f"{objective.objective_id}:{objective.description or description}"
    )


def _objective_needs_reassignment(
    objective: SettlementObjectiveContext,
    now_ms: int | None,
) -> bool:
    status = (objective.status or "").strip().lower()
    if status in {"blocked", "owner_cap_reached", "cooldown", "stale", "abandoned"}:
        return True
    now = now_ms if now_ms is not None else _now_ms()
    if objective.cooldown_until_ms is not None and objective.cooldown_until_ms > now:
        return True
    if objective.owner_started_at_ms is None or objective.stale_after_ms is None:
        return False
    return now - objective.owner_started_at_ms >= objective.stale_after_ms


def _preferred_phase_owners(
    candidates: Sequence[Any],
    roles: Mapping[str, str | None],
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for candidate_id, role in roles.items():
        lowered = f"{candidate_id} {role or ''}".lower()
        priority = 0
        if any(token in lowered for token in ("builder", "architect", "engineer", "maker")):
            priority = -2
        elif any(token in lowered for token in ("explorer", "resource", "gather")):
            priority = -1
        scored.append((priority, candidate_id))
    if not scored:
        return sorted({_agent_id(item) for item in candidates if _agent_id(item)})
    return [candidate_id for _priority, candidate_id in sorted(scored)]


def _pending_owner_grace_ms() -> int:
    raw = (
        os.environ.get("MC_SIM_SETTLEMENT_PENDING_OWNER_GRACE_MS")
        or os.environ.get("MINECRAFT_SETTLEMENT_PENDING_OWNER_GRACE_MS")
        or "600000"
    )
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 600_000


def _plan_build_allowed_agents(
    value: Sequence[Any] | str | set[str] | None = None,
) -> set[str] | None:
    if isinstance(value, set):
        parsed = {_agent_id(item) for item in value}
        parsed.discard("")
        return parsed or None
    if value is None:
        raw = (
            os.environ.get("MC_SIM_PLAN_BUILD_AGENT_ALLOWLIST")
            or os.environ.get("SOAK_PLAN_BUILD_BOTS")
            or ""
        ).strip()
    elif isinstance(value, str):
        raw = value.strip()
    else:
        raw = " ".join(str(item) for item in value)
    if not raw:
        return None
    if raw.lower() in {"*", "all", "any"}:
        return None
    parsed = {_agent_id(item) for item in raw.replace(",", " ").split()}
    parsed.discard("")
    return parsed or None


def _plan_build_agent_allowed(agent_id: str | None, allowed_agents: set[str] | None = None) -> bool:
    normalized = _agent_id(agent_id)
    if not normalized:
        return False
    allowed = _plan_build_allowed_agents() if allowed_agents is None else allowed_agents
    return allowed is None or normalized in allowed


def _cache_key(scene_id: str, owner: str, description: str, origin: Mapping[str, Any]) -> str:
    raw = "|".join(
        (
            scene_id,
            owner,
            description,
            str(origin.get("x", 0)),
            str(origin.get("y", 64)),
            str(origin.get("z", 0)),
        )
    )
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()


def _origin_dict(origin: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = origin or {}
    return {
        "x": int(float(raw.get("x", 0) or 0)),
        "y": int(float(raw.get("y", 64) or 64)),
        "z": int(float(raw.get("z", 0) or 0)),
    }


def _failure_reason(reason: str | None, result: str) -> str:
    if reason:
        return reason.strip().lower().replace("-", "_")
    lowered = str(result or "").lower().replace("-", "_")
    for candidate in DEFAULT_RETRYABLE_REASONS:
        if candidate in lowered:
            return candidate
    if "protected" in lowered:
        return "protected"
    if "invalid" in lowered:
        return "invalid"
    return "failed"


def _normalize_description(value: str) -> str:
    return " ".join(str(value or "").lower().split()) or "build"


def _agent_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now_ms() -> int:
    return int(time.time() * 1000)

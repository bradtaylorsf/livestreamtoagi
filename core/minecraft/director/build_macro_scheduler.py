"""Scene-scoped build macro ownership for Minecraft Director V2."""

from __future__ import annotations

import hashlib
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


@dataclass
class BuildMacroScheduler:
    """Own Director-scheduled build macro plans per scene and owning agent."""

    cooldown_ms: int = 300_000
    retryable_reasons: frozenset[str] = DEFAULT_RETRYABLE_REASONS
    _scene_state: dict[str, _ScenePlanState] = field(default_factory=dict)
    _active_agent_goals: dict[tuple[str, str], str] = field(default_factory=dict)

    def try_acquire_plan(
        self,
        *,
        scene_id: str,
        agent_id: str,
        description: str,
        origin: Mapping[str, Any] | None = None,
        scene: Scene | None = None,
        candidates: Sequence[Any] = (),
        now_ms: int | None = None,
    ) -> BuildMacroAcquireResult:
        """Reserve one active build plan for a scene if no equivalent plan owns it."""

        now = now_ms if now_ms is not None else _now_ms()
        scene_key = _text(scene_id) or "unknown-scene"
        owner = _agent_id(agent_id)
        desc = _normalize_description(description)
        origin_payload = _origin_dict(origin)
        cache_key = _cache_key(scene_key, owner, desc, origin_payload)
        self._expire_scene_if_ready(scene_key, now)

        support_assignments = self.assign_support_roles(
            scene=scene,
            owner=owner,
            candidates=candidates,
            scene_id=scene_key,
            plan_id=None,
            cache_key=cache_key,
        )

        existing = self._scene_state.get(scene_key)
        if existing is not None:
            reason = "already_owned" if existing.owner_agent_id == owner else "scene_locked"
            return BuildMacroAcquireResult(
                granted=False,
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
            )

        plan_id = f"build-plan-{hashlib.sha1(cache_key.encode()).hexdigest()[:12]}"
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
        )
        self._active_agent_goals[agent_goal] = plan_id
        return BuildMacroAcquireResult(
            granted=True,
            scene_id=scene_key,
            plan_id=plan_id,
            owner=owner,
            reason="acquired",
            status="acquired",
            cache_key=cache_key,
            support_assignments=support_assignments,
        )

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
    ) -> dict[str, BuildMacroAssignment]:
        """Assign non-owner scene agents normal support roles."""

        scene_key = scene.scene_id if scene is not None else (_text(scene_id) or "unknown-scene")
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
    return hashlib.sha1(raw.encode()).hexdigest()


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

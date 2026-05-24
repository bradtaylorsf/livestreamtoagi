"""Bridge handlers for the embodied shared-state blackboard."""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from typing import Any

from core.bridge.contract import (
    BridgeRequest,
    SharedStateReadRequest,
    SharedStateWriteRequest,
)
from core.event_bus import EventType, event_bus
from core.redis_keys import ScopedRedis
from core.shared_state import (
    AgentClaim,
    BuildSite,
    DangerReport,
    GroupGoal,
    NextStep,
    ResourceEntry,
    SharedWorkingState,
    VerifiedAction,
)

RESCUE_STRATEGIES_BY_MODE = {
    "easy": "teleport_op",
    "standard": "navigate",
    "production": "navigate",
}


def _state_for_request(env: BridgeRequest, services: Any) -> SharedWorkingState:
    redis = getattr(services, "redis", None)
    if redis is not None:
        return SharedWorkingState(ScopedRedis(redis, uuid.UUID(env.simulation_id)))
    state = getattr(services, "shared_working_state", None)
    if state is None:
        raise ValueError("shared working state is unavailable")
    return state


async def _read_payload(state: SharedWorkingState) -> dict[str, Any]:
    goal = await state.get_group_goal()
    build_site = await state.get_build_site()
    unresolved = await state.get_unresolved_dangers()
    return {
        "goal": asdict(goal) if goal else None,
        "resources": [asdict(resource) for resource in await state.get_resources()],
        "claims": [asdict(claim) for claim in await state.get_agent_claims()],
        "dangers": [asdict(report) for report in await state.get_danger_reports()],
        "unresolved_dangers": [asdict(report) for report in unresolved],
        "recent_actions": [
            asdict(action) for action in await state.get_recent_verified_actions()
        ],
        "build_site": asdict(build_site) if build_site else None,
        "next_steps": [asdict(step) for step in await state.get_next_steps()],
        "formatted": await state.get_summary_for_context(),
    }


async def handle_shared_state_read(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Read the current run-scoped embodied blackboard."""
    SharedStateReadRequest.model_validate(env.payload)
    return await _read_payload(_state_for_request(env, services))


async def record_distress_report(
    env: BridgeRequest,
    services: Any,
    report: DangerReport,
    *,
    writer: str | None = None,
) -> dict[str, Any]:
    """Persist distress, dispatch a rescue task, and emit an observable event."""

    state = _state_for_request(env, services)
    report.reported_by = writer or env.agent_id
    await state.report_danger(report)

    mode = _rescue_mode()
    rescuer_id = await _select_rescuer(state, report.agent_id)
    strategy = RESCUE_STRATEGIES_BY_MODE.get(mode, "navigate")
    rescue_task = await state.dispatch_rescue_task(
        report.danger_id,
        rescuer_id=rescuer_id,
        strategy=strategy,
        mode=mode,
    )
    payload = {
        "danger": asdict(report),
        "rescue_task": asdict(rescue_task) if rescue_task else None,
        "rescue_mode": mode,
        "rescue_strategy": strategy,
    }
    bus = getattr(services, "event_bus", None) or event_bus
    await bus.emit(EventType.DISTRESS_REPORTED, payload)
    return payload


async def handle_shared_state_write(env: BridgeRequest, services: Any) -> dict[str, Any]:
    """Apply an advisory blackboard update for this run."""
    payload = SharedStateWriteRequest.model_validate(env.payload)
    state = _state_for_request(env, services)
    writer = env.agent_id

    if payload.operation == "goal_set":
        if payload.goal is None:
            raise ValueError("goal_set requires goal")
        data = payload.goal.model_dump()
        data["set_by"] = writer
        await state.set_group_goal(GroupGoal(**data))
    elif payload.operation == "resource_upsert":
        if payload.resource is None:
            raise ValueError("resource_upsert requires resource")
        data = payload.resource.model_dump()
        data["reported_by"] = writer
        await state.upsert_resource(ResourceEntry(**data))
    elif payload.operation == "claim_set":
        if payload.claim is None:
            raise ValueError("claim_set requires claim")
        data = payload.claim.model_dump()
        data["claimed_by"] = writer
        await state.set_agent_claim(AgentClaim(**data))
    elif payload.operation == "danger_report":
        if payload.danger is None:
            raise ValueError("danger_report requires danger")
        data = payload.danger.model_dump()
        await record_distress_report(
            env,
            services,
            DangerReport(**data),
            writer=writer,
        )
    elif payload.operation == "danger_resolve":
        if payload.danger_resolution is None:
            raise ValueError("danger_resolve requires danger_resolution")
        data = payload.danger_resolution.model_dump()
        resolved = await state.mark_danger_resolved(
            danger_id=data.get("danger_id"),
            agent_id=data.get("agent_id"),
            rescuer_id=data.get("rescuer_id") or writer,
            recovery_status=data["recovery_status"],
        )
        if resolved is None:
            raise ValueError("danger_resolve did not match an unresolved danger")
    elif payload.operation == "verified_action_record":
        if payload.verified_action is None:
            raise ValueError("verified_action_record requires verified_action")
        await state.record_verified_action(
            VerifiedAction(**payload.verified_action.model_dump())
        )
    elif payload.operation == "build_site_set":
        if payload.build_site is None:
            raise ValueError("build_site_set requires build_site")
        await state.set_build_site(BuildSite(**payload.build_site.model_dump()))
    elif payload.operation == "next_step_add":
        if payload.next_step is None:
            raise ValueError("next_step_add requires next_step")
        data = payload.next_step.model_dump()
        data["added_by"] = writer
        await state.add_next_step(NextStep(**data))

    return {
        "accepted": True,
        "formatted": await state.get_summary_for_context(),
    }


def _rescue_mode() -> str:
    mode = os.environ.get("RESCUE_MODE") or os.environ.get("MINECRAFT_RESCUE_MODE") or "standard"
    normalized = mode.strip().lower()
    return normalized if normalized in {"easy", "standard", "production"} else "standard"


async def _select_rescuer(state: SharedWorkingState, target_agent_id: str) -> str:
    target = target_agent_id.strip().lower()
    claims = await state.get_agent_claims()
    claimed_agents = [claim.agent_id.strip().lower() for claim in claims if claim.agent_id]
    env_order = os.environ.get("MINECRAFT_RESCUE_AGENT_ORDER")
    ordered = (
        [item.strip().lower() for item in env_order.split(",") if item.strip()]
        if env_order
        else ["alpha", "sentinel", "rex", "vera", "aurora", "pixel", "fork", "grok"]
    )
    for agent_id in [*claimed_agents, *ordered]:
        if agent_id and agent_id != target:
            return agent_id
    return "alpha" if target != "alpha" else "rex"

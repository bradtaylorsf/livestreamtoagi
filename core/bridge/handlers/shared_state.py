"""Bridge handlers for the embodied shared-state blackboard."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import asdict
from typing import Any

from core.bridge.contract import (
    BridgeRequest,
    RescueTaskRequest,
    RescueTaskResponse,
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
    SettlementObjective,
    SharedTask,
    SharedWorkingState,
    VerifiedAction,
)

logger = logging.getLogger(__name__)

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
    objectives = await state.get_settlement_objectives()
    active_objective = await state.get_active_settlement_objective()
    return {
        "goal": asdict(goal) if goal else None,
        "resources": [asdict(resource) for resource in await state.get_resources()],
        "claims": [asdict(claim) for claim in await state.get_agent_claims()],
        "dangers": [asdict(report) for report in await state.get_danger_reports()],
        "unresolved_dangers": [asdict(report) for report in unresolved],
        "recent_actions": [asdict(action) for action in await state.get_recent_verified_actions()],
        "build_site": asdict(build_site) if build_site else None,
        "next_steps": [asdict(step) for step in await state.get_next_steps()],
        "settlement_objectives": [asdict(objective) for objective in objectives],
        "active_objective": asdict(active_objective) if active_objective else None,
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
    rescue_request = RescueTaskRequest(
        rescue_id=f"rescue-{report.danger_id}",
        target_agent_id=report.agent_id,
        rescuer_agent_id=rescuer_id,
        strategy=strategy,
        mode=mode,
        danger_id=report.danger_id,
    )
    rescue_task = await state.dispatch_rescue_task(
        report.danger_id,
        rescuer_id=rescuer_id,
        strategy=strategy,
        mode=mode,
    )
    payload = {
        "danger": asdict(report),
        "rescue_task": asdict(rescue_task) if rescue_task else None,
        "rescue_request": rescue_request.model_dump(),
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
    task_result: dict[str, Any] = {}

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
        rescue_response = RescueTaskResponse(
            rescue_id=f"rescue-{data.get('danger_id') or data.get('agent_id') or 'unknown'}",
            target_agent_id=data.get("agent_id") or "unknown",
            rescuer_agent_id=data.get("rescuer_id") or writer,
            status="failure" if data["recovery_status"] == "failed" else "success",
            recovery_status=data["recovery_status"],
            detail="",
        )
        resolved = await state.mark_danger_resolved(
            danger_id=data.get("danger_id"),
            agent_id=data.get("agent_id"),
            rescuer_id=data.get("rescuer_id") or writer,
            recovery_status=data["recovery_status"],
        )
        if resolved is None:
            raise ValueError("danger_resolve did not match an unresolved danger")
        rescue_response.model_dump()
    elif payload.operation == "verified_action_record":
        if payload.verified_action is None:
            raise ValueError("verified_action_record requires verified_action")
        await state.record_verified_action(VerifiedAction(**payload.verified_action.model_dump()))
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
    elif payload.operation == "settlement_objectives_set":
        if not payload.settlement_objectives:
            raise ValueError("settlement_objectives_set requires settlement_objectives")
        await state.set_settlement_objectives(
            [
                SettlementObjective(**objective.model_dump())
                for objective in payload.settlement_objectives
            ]
        )
    elif payload.operation == "settlement_objective_assign":
        if payload.settlement_objective is None:
            raise ValueError("settlement_objective_assign requires settlement_objective")
        data = payload.settlement_objective.model_dump()
        owner = data.get("owner_agent_id") or writer
        updated = await state.assign_settlement_objective_owner(
            data["objective_id"],
            owner,
            reason=data.get("reassign_reason") or "bridge_assignment",
            owner_started_at_ms=data.get("owner_started_at_ms"),
        )
        if updated is None:
            raise ValueError("settlement_objective_assign did not match an objective")
    elif payload.operation == "settlement_objective_advance":
        if payload.settlement_objective is None:
            raise ValueError("settlement_objective_advance requires settlement_objective")
        data = payload.settlement_objective.model_dump()
        updated = await state.advance_settlement_objective(
            data["objective_id"],
            status=data["status"],
            plan_id=data.get("plan_id"),
            intended_blocks=data.get("intended_blocks"),
            verified_blocks=data.get("verified_blocks"),
            completion_ratio=data.get("completion_ratio"),
            evidence=data.get("evidence") or None,
        )
        if updated is None:
            logger.warning(
                "settlement_objective_advance did not match an objective "
                "(objective_id=%r status=%r)",
                data.get("objective_id"),
                data.get("status"),
            )
            raise ValueError(
                "settlement_objective_advance did not match an objective "
                f"(objective_id={data.get('objective_id')!r} status={data.get('status')!r})"
            )
    elif payload.operation == "task_create":
        # E21-7g: a bot proposes work to the shared board. Created OPEN/unclaimed
        # (owner=None) so any agent — including the proposer — can claim it,
        # which keeps the emergent propose->claim loop genuinely multi-agent.
        title = (payload.task_title or "").strip()
        if not title:
            raise ValueError("task_create requires task_title")
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        await state.add_task(SharedTask(id=task_id, title=title, owner=None, status="pending"))
        task_result = {"task_id": task_id, "task_status": "created"}
    elif payload.operation == "task_claim":
        # E21-7g: atomic first-claim-wins (the loser learns the current owner).
        if not payload.task_id:
            raise ValueError("task_claim requires task_id")
        claimed = await state.claim_task(payload.task_id, writer)
        owner = claimed.get("owner")
        task_result = {
            "task_id": payload.task_id,
            "task_status": str(claimed.get("status")),
            "task_owner": str(owner) if owner else None,
        }
    elif payload.operation == "task_complete":
        # E21-7g: mark a claimed task done (evidence is announced in chat).
        if not payload.task_id:
            raise ValueError("task_complete requires task_id")
        found = await state.update_task_status(payload.task_id, "done")
        task_result = {
            "task_id": payload.task_id,
            "task_status": "done" if found else "not_found",
        }
    elif payload.operation == "task_list":
        # E21-7g: the board is rendered in the formatted summary returned below.
        task_result = {"task_status": "ok"}

    return {
        "accepted": True,
        "formatted": await state.get_summary_for_context(),
        **task_result,
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

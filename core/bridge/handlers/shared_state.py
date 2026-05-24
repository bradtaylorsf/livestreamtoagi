"""Bridge handlers for the embodied shared-state blackboard."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any

from core.bridge.contract import (
    BridgeRequest,
    SharedStateReadRequest,
    SharedStateWriteRequest,
)
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
    return {
        "goal": asdict(goal) if goal else None,
        "resources": [asdict(resource) for resource in await state.get_resources()],
        "claims": [asdict(claim) for claim in await state.get_agent_claims()],
        "dangers": [asdict(report) for report in await state.get_danger_reports()],
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
        data["reported_by"] = writer
        await state.report_danger(DangerReport(**data))
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

"""Bridge handler for Director V2 Mindcraft prompt gating."""

from __future__ import annotations

from typing import Any

from core.bridge.consumers import ensure_scene_memory_consumer
from core.bridge.contract import BridgeRequest, DirectorGateRequest
from core.conversation_mode import is_director_v2_run
from core.minecraft.director.prompt_gate import get_prompt_gate
from core.minecraft.director.timeline import ensure_soak_run_dir_from_run_id


async def handle_director_gate(env: BridgeRequest, services: Any | None = None) -> dict[str, Any]:
    """Return a Director V2 prompt verdict for one Mindcraft bot."""

    payload = DirectorGateRequest.model_validate(env.payload)
    if not is_director_v2_run():
        return {
            "selected": True,
            "turn_kind": None,
            "reason": "mode_bypass",
            "suppression_reason": None,
            "scene_id": payload.scene_hint or "mode-bypass",
            "scene_digest": "Director V2 gate bypassed outside director_v2 mode.",
            "role": "legacy decentralized responder",
            "local_observations": {},
            "granted_tools": payload.available_tools,
            "build_macro": None,
            "queue_depth": 0,
            "suppressed_agents": [],
        }

    _ensure_scene_memory_evidence_path(env, services)
    gate = get_prompt_gate(env.simulation_id)
    event = payload.model_dump()
    if env.trace_id:
        event["trace_id"] = env.trace_id
    decision = await gate.evaluate(
        env.simulation_id,
        payload.agent_id,
        event,
    )
    return {
        "selected": decision.selected,
        "turn_kind": decision.turn_kind,
        "reason": decision.reason,
        "suppression_reason": decision.suppression_reason,
        "scene_id": decision.scene_id,
        "scene_digest": decision.scene_digest,
        "role": decision.role,
        "local_observations": decision.local_observations,
        "granted_tools": decision.available_tools,
        "build_macro": decision.build_macro.model_dump() if decision.build_macro else None,
        "queue_depth": decision.queue_depth,
        "suppressed_agents": decision.suppressed_agents,
    }


def _ensure_scene_memory_evidence_path(env: BridgeRequest, services: Any | None) -> None:
    ensure_soak_run_dir_from_run_id(env.run_id)
    if services is None:
        return
    event_bus = getattr(services, "event_bus", None)
    compactor = getattr(services, "compactor", None)
    if event_bus is None or compactor is None:
        return
    ensure_scene_memory_consumer(event_bus, compactor)

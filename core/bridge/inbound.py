"""Node->Python perception/action-result inbound channel (issue #545, E4-6).

Option C requires perception/action outcomes to flow *back* from the Node
Minecraft bots into Python so later stages (E5 memory writes, E10 eval) can
consume them. This module is that inbound leg: it turns the two Node->Python
report verbs into schema-validated events on the existing event bus
(:mod:`core.event_bus`). It owns *only* the ingest hop — emitting an observable,
attributed event — and deliberately nothing downstream of it:

* **In scope:** Node emits ``perception.report`` / ``action.result`` over the
  bridge; this re-parses the (already envelope/registry-validated) payload into
  its typed contract model so the emitted event is schema-validated, then emits
  it on the event bus with full attribution.
* **Out of scope:** memory writes (E5) and eval consumption (E10). Those attach
  later as ordinary ``event_bus.on(...)`` subscribers — no change here.

The wire format is fixed by the E4-2 contract (:mod:`core.bridge.contract`),
itself fixed by ADR ``docs/decisions/0010-bridge-protocol.md`` §6. The
request/response *stub* for these verbs stays in :mod:`core.bridge.server`
``STUB_HANDLERS`` (the response is still ``{"accepted": True}``); this module
runs the additional emit so the contract response is unchanged while the event
becomes observable on the Python side before the ack returns.

There is no LLM runtime path in this issue: it is pure event plumbing with no
model calls. The nearest local smoke path is the dependency-free
``tests/backend/test_bridge_inbound.py`` (event observed in-process, no
Docker/network/LLM).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.bridge.contract import (
    SERVICE_REGISTRY,
    ActionResultRequest,
    BridgeRequest,
    PerceptionReportRequest,
    service_key,
)
from core.event_bus import EventType, event_bus

# The closed set of Node->Python verbs that produce an observable event on the
# Python side. Everything else on the bridge is a normal request/response stub
# (E4-3) and is NOT routed here. These names match the contract's closed
# registry (ADR §6); the parity check below proves it.
INBOUND_VERBS: frozenset[str] = frozenset({"perception.report", "action.result"})


def _attribution(env: BridgeRequest) -> dict[str, str]:
    """Envelope-carried attribution every inbound event must carry.

    request_id is the correlation/idempotency key (ADR §5); the rest tie the
    event to the right run/simulation so E5/E10 can charge and journal it.
    """
    return {
        "request_id": env.request_id,
        "agent_id": env.agent_id,
        "run_id": env.run_id,
        "simulation_id": env.simulation_id,
    }


async def handle_perception_report(env: BridgeRequest) -> dict[str, Any]:
    """Emit a schema-validated ``BRIDGE_PERCEPTION`` event; ack the report.

    The payload was already validated by the server's ``validate_request``;
    re-parsing it into :class:`PerceptionReportRequest` here guarantees the
    emitted event body is itself contract-valid (not a raw dict that could
    drift). The return value is identical to the E4-3 stub so the contract
    response schema stays satisfied.
    """
    payload = PerceptionReportRequest.model_validate(env.payload)
    await event_bus.emit(
        EventType.BRIDGE_PERCEPTION,
        {**_attribution(env), "observations": payload.observations},
    )
    return {"accepted": True}


async def handle_action_result(env: BridgeRequest) -> dict[str, Any]:
    """Emit a schema-validated ``BRIDGE_ACTION_RESULT`` event; ack the result.

    ``model_dump()`` spreads the validated ``action_id``/``status``/``detail``
    into the event so subscribers get typed fields, not a raw payload dict.
    """
    payload = ActionResultRequest.model_validate(env.payload)
    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {**_attribution(env), **payload.model_dump()},
    )
    return {"accepted": True}


# Keyed by the canonical "<service>.<method>" registry key (ADR §6).
INBOUND_HANDLERS: dict[str, Callable[[BridgeRequest], Awaitable[dict[str, Any]]]] = {
    "perception.report": handle_perception_report,
    "action.result": handle_action_result,
}


async def dispatch_inbound(env: BridgeRequest) -> dict[str, Any]:
    """Route an inbound report envelope to its handler and return the ack.

    The caller (the server receive loop) only invokes this for an ``ok``
    response whose verb is in :data:`INBOUND_VERBS`, so the key is always
    present; a missing key is a wiring bug and should fail loudly.
    """
    return await INBOUND_HANDLERS[service_key(env.service, env.method)](env)


# Defensive parity: the inbound handler set, the public verb set, and the
# contract's closed registry must agree exactly. Mirrors the equivalent guard
# in core/bridge/server.py so a verb cannot be added in one place only.
def _assert_inbound_in_sync() -> None:
    handler_keys = set(INBOUND_HANDLERS)
    if handler_keys != set(INBOUND_VERBS):
        raise RuntimeError(
            f"INBOUND_HANDLERS out of sync with INBOUND_VERBS: "
            f"handlers={sorted(handler_keys)} verbs={sorted(INBOUND_VERBS)}"
        )
    not_in_registry = handler_keys - set(SERVICE_REGISTRY)
    if not_in_registry:
        raise RuntimeError(
            f"inbound verbs not in the closed contract registry: {sorted(not_in_registry)}"
        )


_assert_inbound_in_sync()

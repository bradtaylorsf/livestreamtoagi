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
* **Out of scope:** memory writes (E5) and eval consumption (E10). Downstream
  consumers attach as ordinary ``event_bus.on(...)`` subscribers — no change
  here.

E4-7 (#546) adds the end-to-end ``trace_id`` to the emitted event's attribution
and logs the emit with it, so a report is followable from the Node send
through the Python bus by the same correlation id the server logged.

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

E6-2 (#557) movement/navigation skills reuse this same channel: they emit a
pose ``perception.report`` followed by a terminal ``action.result``.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from core.bridge.contract import (
    SERVICE_REGISTRY,
    ActionResultRequest,
    BridgeRequest,
    PerceptionReportRequest,
    service_key,
)
from core.bridge.handlers.shared_state import record_distress_report
from core.bridge.observability import log_bridge_inbound_event
from core.embodiment import build_perception_snapshot
from core.event_bus import EventType, event_bus
from core.shared_state import DangerReport

logger = logging.getLogger(__name__)

# The closed set of Node->Python verbs that produce an observable event on the
# Python side. Everything else on the bridge is a normal request/response stub
# (E4-3) and is NOT routed here. These names match the contract's closed
# registry (ADR §6); the parity check below proves it.
INBOUND_VERBS: frozenset[str] = frozenset({"perception.report", "action.result"})
REPEATED_FAILURE_OUTCOMES = frozenset({"interrupted", "blocked"})
REPEATED_FAILURE_THRESHOLD = 3
REPEATED_FAILURE_WINDOW_SECONDS = 90
MAX_FAILURE_WINDOWS = 4096
_failure_windows: dict[tuple[str, str, str], deque[float]] = {}


def _resolve_trace_id(env: BridgeRequest, trace_id: str | None) -> str:
    """The correlation id for this inbound emit (E4-7, #546).

    Prefer the trace id the server already resolved for the frame (passed in by
    :mod:`core.bridge.server` so the bus event, the server log, and the wire
    response all share one id). Fall back to the envelope's own ``trace_id``
    (e.g. a direct handler unit-call), and finally mint one so the attribution
    dict is always a complete ``dict[str, str]`` and never carries a ``None``.
    """
    return trace_id or env.trace_id or f"trace-{uuid4()}"


def _canonical_agent_id(agent_id: str) -> str:
    """Return the database/runtime canonical agent id carried by bridge events."""
    return agent_id.strip().lower()


def _attribution(env: BridgeRequest, trace_id: str) -> dict[str, str]:
    """Envelope-carried attribution every inbound event must carry.

    request_id is the correlation/idempotency key (ADR §5); trace_id is the
    E4-7 end-to-end correlation id (#546); the rest tie the event to the right
    run/simulation so E5/E10 can charge and journal it.
    """
    return {
        "trace_id": trace_id,
        "request_id": env.request_id,
        "agent_id": _canonical_agent_id(env.agent_id),
        "run_id": env.run_id,
        "simulation_id": env.simulation_id,
    }


async def handle_perception_report(
    env: BridgeRequest,
    trace_id: str | None = None,
    services: Any | None = None,
) -> dict[str, Any]:
    """Emit a schema-validated ``BRIDGE_PERCEPTION`` event; ack the report.

    The payload was already validated by the server's ``validate_request``;
    re-parsing it into :class:`PerceptionReportRequest` here guarantees the
    emitted event body is itself contract-valid (not a raw dict that could
    drift). The return value is identical to the E4-3 stub so the contract
    response schema stays satisfied. ``trace_id`` (E4-7, #546) is carried on
    the event and logged so this emit joins the frame's correlation id.
    """
    del services
    payload = PerceptionReportRequest.model_validate(env.payload)
    tid = _resolve_trace_id(env, trace_id)
    event_payload: dict[str, Any] = {
        **_attribution(env, tid),
        "observations": payload.observations,
    }
    snapshot = build_perception_snapshot(payload.observations)
    if snapshot is not None:
        event_payload["snapshot"] = snapshot.model_dump()
    await event_bus.emit(
        EventType.BRIDGE_PERCEPTION,
        event_payload,
    )
    log_bridge_inbound_event(
        logger,
        trace_id=tid,
        request_id=env.request_id,
        agent_id=_canonical_agent_id(env.agent_id),
        event_type=EventType.BRIDGE_PERCEPTION.value,
    )
    return {"accepted": True}


async def handle_action_result(
    env: BridgeRequest,
    trace_id: str | None = None,
    services: Any | None = None,
) -> dict[str, Any]:
    """Emit a schema-validated ``BRIDGE_ACTION_RESULT`` event; ack the result.

    ``model_dump()`` spreads the validated ``action_id``/``status``/``detail``
    into the event so subscribers get typed fields, not a raw payload dict.
    ``trace_id`` (E4-7, #546) is carried on the event and logged so this emit
    joins the frame's correlation id.
    """
    payload = ActionResultRequest.model_validate(env.payload)
    tid = _resolve_trace_id(env, trace_id)
    await event_bus.emit(
        EventType.BRIDGE_ACTION_RESULT,
        {**_attribution(env, tid), **payload.model_dump()},
    )
    await _maybe_emit_repeated_failure_distress(env, payload, services)
    log_bridge_inbound_event(
        logger,
        trace_id=tid,
        request_id=env.request_id,
        agent_id=_canonical_agent_id(env.agent_id),
        event_type=EventType.BRIDGE_ACTION_RESULT.value,
    )
    return {"accepted": True}


# Keyed by the canonical "<service>.<method>" registry key (ADR §6).
InboundHandler = Callable[[BridgeRequest, str | None, Any | None], Awaitable[dict[str, Any]]]
INBOUND_HANDLERS: dict[str, InboundHandler] = {
    "perception.report": handle_perception_report,
    "action.result": handle_action_result,
}


async def dispatch_inbound(
    env: BridgeRequest,
    trace_id: str | None = None,
    services: Any | None = None,
) -> dict[str, Any]:
    """Route an inbound report envelope to its handler and return the ack.

    The caller (the server receive loop) only invokes this for an ``ok``
    response whose verb is in :data:`INBOUND_VERBS`, so the key is always
    present; a missing key is a wiring bug and should fail loudly. ``trace_id``
    is the frame's resolved correlation id (E4-7, #546) — threaded through so
    the emitted bus event shares the id the server logged and echoed.
    """
    return await INBOUND_HANDLERS[service_key(env.service, env.method)](env, trace_id, services)


async def _maybe_emit_repeated_failure_distress(
    env: BridgeRequest,
    payload: ActionResultRequest,
    services: Any | None,
) -> None:
    outcome = (payload.outcome_class or "").strip().lower()
    if outcome not in REPEATED_FAILURE_OUTCOMES:
        return
    key = (env.simulation_id, _canonical_agent_id(env.agent_id), outcome)
    now = time.time()
    window = _failure_windows.setdefault(key, deque())
    window.append(now)
    while window and now - window[0] > REPEATED_FAILURE_WINDOW_SECONDS:
        window.popleft()
    _prune_failure_windows(now)
    if len(window) < REPEATED_FAILURE_THRESHOLD:
        return
    window.clear()
    if services is None:
        return
    report = DangerReport(
        agent_id=_canonical_agent_id(env.agent_id),
        kind="repeated_failure",
        location=None,
        severity=3,
        details=payload.detail or f"Repeated {outcome} action results",
    )
    await record_distress_report(env, services, report, writer="bridge_action_result")


def _prune_failure_windows(now: float) -> None:
    for key, window in list(_failure_windows.items()):
        while window and now - window[0] > REPEATED_FAILURE_WINDOW_SECONDS:
            window.popleft()
        if not window:
            _failure_windows.pop(key, None)
    if len(_failure_windows) <= MAX_FAILURE_WINDOWS:
        return
    oldest = sorted(
        _failure_windows.items(),
        key=lambda item: item[1][-1] if item[1] else 0.0,
    )
    for key, _window in oldest[: max(0, len(_failure_windows) - MAX_FAILURE_WINDOWS)]:
        _failure_windows.pop(key, None)


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

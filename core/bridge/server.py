"""Python bridge server endpoint (issue #542, E4-3).

A single authenticated, namespaced WebSocket surface that Node Minecraft bots
connect to, mounted into the existing FastAPI app alongside ``/ws``. This issue
is *only* the bridge surface: handshake auth, envelope/version/contract
validation, and a dispatch table whose handlers return contract-valid **stub**
payloads. Real cost wiring is explicitly out of scope (E11);
the perception/action inbound channel is E4-5/E4-6.

E4-7 (#546) layers observability on the receive loop without changing the wire
contract: every settled frame resolves a single ``trace_id`` (echoed from the
request or minted here when the additive field is absent), is echoed back on
the :class:`BridgeResponse`, and emits one structured log record + one metrics
sample via :mod:`core.bridge.observability` — so one request is traceable end
to end by a single id across the Node and Python logs.

Everything here is fixed by ADR ``docs/decisions/0010-bridge-protocol.md``
(#540, E4-1) and validated against the versioned contract from
:mod:`core.bridge.contract` (#541, E4-2):

* ADR §1 — endpoint is ``/api/minecraft/bridge/ws``, one WebSocket per bot.
* ADR §4 — **fail-closed** shared-secret bearer auth. A missing/empty server
  token, or a missing/malformed/wrong presented token, closes the socket with
  code ``1008`` *before* ``accept()``. No ``service`` is ever dispatched on an
  unauthenticated connection: there is no anonymous or "auth optional in dev"
  path to spend or in-world actions. This mirrors the constant-time check in
  ``core/admin/kill_switch_routes.py``. The primary credential transport is
  ``Authorization: Bearer``; ``?token=`` is accepted only when
  ``MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN`` is explicitly enabled for constrained
  local clients.
* ADR §2/§3/§6 — every inbound frame is parsed as a :class:`BridgeRequest`,
  version-negotiated fail-closed on an unknown major, and validated against the
  closed per-verb registry. Every failure after ``accept()`` goes back as a
  contract-valid :class:`BridgeResponse` (``ok=false`` + typed error); only the
  handshake closes the socket.

``memory.recall`` delegates read-only to the existing memory managers,
``memory.write`` delegates append/write work to the existing memory compactor,
``management.review`` gates bot chat through Management, and ``errand.complete``
records Alpha outcomes to that same compactor when FastAPI lifespan has
initialized services. ``code.execute`` delegates to the existing Docker/gVisor
sandbox tool; remaining verbs stay contract-valid stubs until their owning
issues wire them.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from core.bridge import inbound, observability
from core.bridge.contract import (
    ERR_INVALID_PAYLOAD,
    ERR_UNSUPPORTED_SERVICE,
    BridgeRequest,
    BridgeResponse,
    CostGateRequest,
    ErrandCompleteRequest,
    ErrandPollRequest,
    MemoryRecallRequest,
    UnsupportedServiceError,
    is_supported_version,
    make_error_response,
    service_key,
    unsupported_version_response,
    validate_request,
    validate_response,
)
from core.bridge.errand_queue import Errand, errand_queue
from core.bridge.handlers.code_execution import handle_code_execute
from core.bridge.handlers.director import handle_director_gate
from core.bridge.handlers.errand import handle_errand_complete
from core.bridge.handlers.management import handle_management_review
from core.bridge.handlers.memory import handle_memory_read, handle_memory_write
from core.bridge.handlers.shared_state import (
    handle_shared_state_read,
    handle_shared_state_write,
)
from core.kill_switch import KILL_SWITCH_ACTIVE_VALUE, KILL_SWITCH_KEY

logger = logging.getLogger(__name__)

bridge_router = APIRouter(tags=["bridge"])

# ADR §1: the one namespaced bridge surface. Kept as a constant so the wiring
# test and the route declaration cannot drift.
BRIDGE_WS_PATH = "/api/minecraft/bridge/ws"

# ADR §4: the env var the Node client and this server share the secret through.
BRIDGE_TOKEN_ENV = "MINECRAFT_BRIDGE_TOKEN"

# Query-string bearer tokens are easier for constrained WS clients but they are
# also easier to leak through logs/proxies/history. Keep the fallback off unless
# a local test or explicitly constrained client enables it.
BRIDGE_QUERY_TOKEN_ENV = "MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN"

# RFC 6455 policy-violation close code; used for every fail-closed handshake
# rejection so the Node side sees one unambiguous "auth refused" signal.
WS_POLICY_VIOLATION = 1008

# BridgeResponse.request_id has min_length=1, so an error response for an
# envelope we could not parse a request_id out of still needs a non-empty
# correlation value. ADR §5 keys idempotency/correlation on request_id; we use
# this explicit sentinel rather than "" (which the contract rejects) so the
# response is itself contract-valid and the Node side can still see it was an
# unparseable inbound frame.
UNKNOWN_REQUEST_ID = "unknown"

ERR_MEMORY_SERVICE_UNAVAILABLE = "memory_service_unavailable"
ERR_MANAGEMENT_SERVICE_UNAVAILABLE = "management_service_unavailable"
ERR_SHARED_STATE_SERVICE_UNAVAILABLE = "shared_state_service_unavailable"
ERR_CODE_SERVICE_UNAVAILABLE = "code_service_unavailable"
ERR_DIRECTOR_GATE_UNAVAILABLE = "director_gate_unavailable"
ERR_KILL_SWITCH_ACTIVE = "kill_switch_active"
MEMORY_HANDLER_VERBS = frozenset({"memory.recall"})
MEMORY_WRITE_VERBS = frozenset({"memory.write"})
MANAGEMENT_REVIEW_VERBS = frozenset({"management.review"})
SHARED_STATE_READ_VERBS = frozenset({"shared_state.read"})
SHARED_STATE_WRITE_VERBS = frozenset({"shared_state.write"})
SHARED_STATE_VERBS = SHARED_STATE_READ_VERBS | SHARED_STATE_WRITE_VERBS
CODE_EXECUTE_VERBS = frozenset({"code.execute"})
DIRECTOR_GATE_VERBS = frozenset({"director.gate"})
ERRAND_POLL_VERBS = frozenset({"errand.poll"})
ERRAND_COMPLETE_VERBS = frozenset({"errand.complete"})
ERRAND_VERBS = ERRAND_POLL_VERBS | ERRAND_COMPLETE_VERBS
COST_GATE_VERBS = frozenset({"cost.gate"})
KILL_STATUS_VERBS = frozenset({"kill.status"})
WORLD_ACTION_ERROR_VERBS = frozenset({"action.result", "code.execute", "errand.complete"})
WORLD_ACTION_SAFE_IDLE_VERBS = frozenset({"perception.report", "errand.poll"})
WORLD_ACTION_VERBS = WORLD_ACTION_ERROR_VERBS | WORLD_ACTION_SAFE_IDLE_VERBS


# ── Stub dispatch table (no business logic — E5/E8 own the real wiring) ──────

StubHandler = Callable[[BridgeRequest], dict[str, Any]]

# Each handler returns a payload that satisfies the verb's *response* schema in
# core/bridge/contract.py and nothing more. They run only after
# ``validate_request`` has accepted the inbound payload, so ``bridge.ping`` can
# safely index ``env.payload["message"]``. Keys must exactly match
# SERVICE_REGISTRY (asserted below + covered by the contract-parity test).
STUB_HANDLERS: dict[str, StubHandler] = {
    "bridge.ping": lambda env: {"pong": env.payload["message"]},
    "cost.gate": lambda env: {
        "allowed": True,
        "reason": "stub",
        "remaining_budget_usd": 0.0,
    },
    "perception.report": lambda env: {"accepted": True},
    "action.result": lambda env: {"accepted": True},
}


def _services_from_websocket(websocket: WebSocket) -> Any | None:
    """Resolve initialized app services without assuming lifespan has run."""
    return getattr(websocket.app.state, "services", None)


def _summarize_validation_error(exc: ValidationError) -> str:
    """Compact, log-safe summary of a pydantic error for the response body."""
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
    )


def _request_id_from_raw(raw: Any) -> str:
    """Best-effort correlation id for an envelope that failed to parse.

    Echo the caller's ``request_id`` when the frame at least carried a
    non-empty string one, so a retry/correlation still lines up; otherwise fall
    back to :data:`UNKNOWN_REQUEST_ID` (never ``""`` — the contract forbids it).
    """
    if isinstance(raw, dict):
        rid = raw.get("request_id")
        if isinstance(rid, str) and rid:
            return rid
    return UNKNOWN_REQUEST_ID


def _resolve_trace_id(raw: Any) -> str:
    """The correlation id for this frame (E4-7, #546).

    Echo the caller's ``trace_id`` when the inbound frame carried a non-empty
    string one; otherwise **mint** a server-side ``trace-<uuid>`` so a request
    is *always* traceable end-to-end by a single id — a 1.0 peer that omits the
    field (additive, ADR §3) still gets correlated logs on both halves.
    """
    if isinstance(raw, dict):
        tid = raw.get("trace_id")
        if isinstance(tid, str) and tid:
            return tid
    return f"trace-{uuid4()}"


def _str_field_from_raw(raw: Any, key: str, default: str) -> str:
    """Best-effort string field off an un-trusted/maybe-unparsed frame (logs only)."""
    if isinstance(raw, dict):
        val = raw.get(key)
        if isinstance(val, str) and val:
            return val
    return default


def _verb_from_raw(raw: Any) -> str:
    """Canonical ``service.method`` for metrics, or ``unparseable`` when absent.

    Used only to key the in-process counters/log line; the real dispatch still
    goes through the validated envelope, so a bogus value here never routes.
    """
    if isinstance(raw, dict):
        service, method = raw.get("service"), raw.get("method")
        if isinstance(service, str) and service and isinstance(method, str) and method:
            return service_key(service, method)
    return "unparseable"


def _validated_request_or_error(raw: Any) -> BridgeRequest | BridgeResponse:
    """Validate envelope, version, and per-verb payload."""
    try:
        env = BridgeRequest.model_validate(raw)
    except ValidationError as exc:
        return make_error_response(
            _request_id_from_raw(raw),
            ERR_INVALID_PAYLOAD,
            f"invalid request envelope: {_summarize_validation_error(exc)}",
        )

    if not is_supported_version(env.version):
        return unsupported_version_response(env.request_id, env.version)

    try:
        validate_request(env)
    except UnsupportedServiceError as exc:
        return make_error_response(env.request_id, ERR_UNSUPPORTED_SERVICE, str(exc))
    except ValidationError as exc:
        return make_error_response(
            env.request_id,
            ERR_INVALID_PAYLOAD,
            f"invalid {env.service}.{env.method} payload: {_summarize_validation_error(exc)}",
        )

    return env


def _success_response(env: BridgeRequest, payload: dict[str, Any]) -> BridgeResponse:
    response = BridgeResponse(request_id=env.request_id, ok=True, payload=payload)
    # Prove the payload honours the verb's response schema before it goes on
    # the wire — a handler that drifts from the contract should fail loudly
    # here, not silently ship an invalid frame to the Node side.
    validate_response(response, service=env.service, method=env.method)
    return response


def _memory_services_unavailable(env: BridgeRequest, services: Any | None) -> BridgeResponse | None:
    payload = MemoryRecallRequest.model_validate(env.payload)
    manager_name = "core_memory" if payload.tier == "core" else "recall_memory"
    if services is None:
        message = "memory services are unavailable; application lifespan has not initialized"
    elif payload.tier == "recall" and (
        getattr(services, "memory_backend", None) is not None
        or getattr(services, "recall_memory", None) is not None
    ):
        return None
    elif getattr(services, manager_name, None) is None:
        message = f"memory manager {manager_name!r} is unavailable"
    else:
        return None

    return make_error_response(
        env.request_id,
        ERR_MEMORY_SERVICE_UNAVAILABLE,
        message,
        retryable=True,
    )


def _memory_write_services_unavailable(
    env: BridgeRequest, services: Any | None
) -> BridgeResponse | None:
    if services is None:
        message = "memory services are unavailable; application lifespan has not initialized"
    elif getattr(services, "compactor", None) is None:
        message = "memory compactor is unavailable"
    else:
        return None

    return make_error_response(
        env.request_id,
        ERR_MEMORY_SERVICE_UNAVAILABLE,
        message,
        retryable=True,
    )


def _management_services_unavailable(
    env: BridgeRequest, services: Any | None
) -> BridgeResponse | None:
    if services is None:
        message = "management service is unavailable; application lifespan has not initialized"
    elif getattr(services, "management", None) is None:
        message = "management service is unavailable"
    else:
        return None

    return make_error_response(
        env.request_id,
        ERR_MANAGEMENT_SERVICE_UNAVAILABLE,
        message,
        retryable=True,
    )


def _shared_state_services_unavailable(
    env: BridgeRequest, services: Any | None
) -> BridgeResponse | None:
    if services is None:
        message = "shared-state services are unavailable; application lifespan has not initialized"
    elif getattr(services, "redis", None) is None and getattr(
        services, "shared_working_state", None
    ) is None:
        message = "shared working state is unavailable"
    else:
        return None

    return make_error_response(
        env.request_id,
        ERR_SHARED_STATE_SERVICE_UNAVAILABLE,
        message,
        retryable=True,
    )


def _code_services_unavailable(env: BridgeRequest, services: Any | None) -> BridgeResponse | None:
    if services is None:
        message = (
            "code execution services are unavailable; application lifespan has not initialized"
        )
    elif getattr(services, "event_bus", None) is None:
        message = "event bus is unavailable for code execution"
    else:
        return None

    return make_error_response(
        env.request_id,
        ERR_CODE_SERVICE_UNAVAILABLE,
        message,
        retryable=True,
    )


async def _kill_switch_active(services: Any | None) -> bool:
    """Return whether the global Redis kill switch is active.

    ``kill_switch`` is intentionally read from the raw app Redis client, not
    ``scoped_redis``; it is a global emergency control.
    """
    if services is None:
        return False
    redis = getattr(services, "redis", None)
    if redis is None:
        return False
    try:
        raw = await redis.get(KILL_SWITCH_KEY)
        return raw == KILL_SWITCH_ACTIVE_VALUE or raw == KILL_SWITCH_ACTIVE_VALUE.encode()
    except Exception:
        logger.warning(
            "Bridge kill-switch lookup failed; treating world action gate as active",
            exc_info=True,
        )
        return True


async def _kill_switch_ttl(redis: Any) -> int | None:
    """Best-effort Redis TTL lookup for the global kill switch key."""
    ttl_fn = getattr(redis, "ttl", None)
    if callable(ttl_fn):
        raw = await ttl_fn(KILL_SWITCH_KEY)
    else:
        client = getattr(redis, "client", None)
        client_ttl = getattr(client, "ttl", None)
        if not callable(client_ttl):
            return None
        raw = await client_ttl(KILL_SWITCH_KEY)

    if isinstance(raw, int) and raw >= 0:
        return raw
    return None


async def _handle_kill_status(env: BridgeRequest, services: Any | None) -> dict[str, Any]:
    """Return current global kill-switch state without applying the kill gate."""
    del env
    if services is None:
        return {"active": False, "ttl_seconds": None, "reason": None}
    redis = getattr(services, "redis", None)
    if redis is None:
        return {"active": False, "ttl_seconds": None, "reason": None}
    try:
        raw = await redis.get(KILL_SWITCH_KEY)
        active = raw == "active" or raw == b"active"
        ttl_seconds = await _kill_switch_ttl(redis)
    except Exception:
        logger.warning(
            "Bridge kill-switch status lookup failed; reporting fail-safe active",
            exc_info=True,
        )
        return {
            "active": True,
            "ttl_seconds": None,
            "reason": "kill_switch_lookup_failed",
        }
    return {
        "active": active,
        "ttl_seconds": ttl_seconds if active else None,
        "reason": "kill_switch_active" if active else None,
    }


def _errand_payload(errand: Errand | None) -> dict[str, Any]:
    if errand is None:
        return {
            "task_id": None,
            "task": None,
            "from_agent": None,
            "dispatched_at_ms": None,
            "urgency": None,
        }
    return {
        "task_id": errand.task_id,
        "task": errand.task,
        "from_agent": errand.from_agent,
        "dispatched_at_ms": errand.dispatched_at_ms,
        "urgency": errand.urgency,
    }


def _handle_errand_poll(env: BridgeRequest) -> dict[str, Any]:
    payload = ErrandPollRequest.model_validate(env.payload)
    return _errand_payload(errand_queue.poll(payload.agent_id))


def _handle_errand_complete(env: BridgeRequest) -> dict[str, Any]:
    payload = ErrandCompleteRequest.model_validate(env.payload)
    errand_queue.record_completion(
        payload.task_id,
        payload.status,
        payload.symbol,
        payload.detail,
        [step.model_dump() for step in payload.step_results],
    )
    return {"accepted": True}


async def _handle_cost_gate(env: BridgeRequest, services: Any | None) -> dict[str, Any]:
    payload = CostGateRequest.model_validate(env.payload)
    governor = getattr(services, "cost_governor", None) if services is not None else None
    if governor is None:
        logger.warning("Bridge cost.gate served by stub because CostGovernor is unavailable")
        return STUB_HANDLERS["cost.gate"](env)

    try:
        allowed, spend, cap = await governor.is_allowed(payload.agent_id)
    except Exception:
        logger.warning(
            "Bridge cost.gate failed closed for agent=%s action=%s",
            payload.agent_id,
            payload.action,
            exc_info=True,
        )
        return {
            "allowed": False,
            "reason": "cost_governor_error",
            "remaining_budget_usd": 0.0,
        }

    remaining = max(cap - spend, Decimal("0"))
    return {
        "allowed": allowed,
        "reason": "ok" if allowed else "agent_hourly_cap_exceeded",
        "remaining_budget_usd": float(remaining),
    }


def _errand_poll_targets_alpha(env: BridgeRequest) -> bool:
    payload = ErrandPollRequest.model_validate(env.payload)
    return env.agent_id == "alpha" or payload.agent_id == "alpha"


def _errand_complete_targets_alpha(env: BridgeRequest) -> bool:
    return env.agent_id == "alpha"


def build_bridge_response(raw: Any) -> BridgeResponse:
    """Turn one decoded non-memory frame into a contract-valid response envelope.

    Pure and synchronous so the dispatch policy is unit-testable without a
    socket. Order mirrors ADR §2→§3→§6: envelope shape, then version, then the
    closed per-verb registry, then the stub handler. The async WebSocket loop
    handles service-backed verbs separately because they delegate to initialized
    app services.
    """
    validated = _validated_request_or_error(raw)
    if isinstance(validated, BridgeResponse):
        return validated

    env = validated
    key = service_key(env.service, env.method)
    if key in KILL_STATUS_VERBS:
        return _success_response(
            env,
            {"active": False, "ttl_seconds": None, "reason": None},
        )
    if key in MEMORY_HANDLER_VERBS | MEMORY_WRITE_VERBS:
        return make_error_response(
            env.request_id,
            ERR_MEMORY_SERVICE_UNAVAILABLE,
            f"{key} requires initialized memory services",
            retryable=True,
        )
    if key in MANAGEMENT_REVIEW_VERBS:
        return make_error_response(
            env.request_id,
            ERR_MANAGEMENT_SERVICE_UNAVAILABLE,
            f"{key} requires initialized management services",
            retryable=True,
        )
    if key in SHARED_STATE_VERBS:
        return make_error_response(
            env.request_id,
            ERR_SHARED_STATE_SERVICE_UNAVAILABLE,
            f"{key} requires initialized shared-state services",
            retryable=True,
        )
    if key in CODE_EXECUTE_VERBS:
        return make_error_response(
            env.request_id,
            ERR_CODE_SERVICE_UNAVAILABLE,
            f"{key} requires initialized code execution services",
            retryable=True,
        )
    if key in DIRECTOR_GATE_VERBS:
        return make_error_response(
            env.request_id,
            ERR_DIRECTOR_GATE_UNAVAILABLE,
            f"{key} requires the async bridge dispatcher",
            retryable=True,
        )
    if key in ERRAND_POLL_VERBS:
        return _success_response(env, _handle_errand_poll(env))
    if key in ERRAND_COMPLETE_VERBS:
        return _success_response(env, _handle_errand_complete(env))

    return _success_response(env, STUB_HANDLERS[key](env))


async def build_bridge_response_with_services(
    raw: Any,
    services: Any | None,
) -> BridgeResponse:
    """Turn one decoded inbound frame into a contract-valid response envelope."""
    validated = _validated_request_or_error(raw)
    if isinstance(validated, BridgeResponse):
        return validated

    env = validated
    key = service_key(env.service, env.method)
    if key in KILL_STATUS_VERBS:
        return _success_response(env, await _handle_kill_status(env, services))

    if key in WORLD_ACTION_VERBS and await _kill_switch_active(services):
        if key in WORLD_ACTION_SAFE_IDLE_VERBS:
            payload = {"accepted": True} if key == "perception.report" else _errand_payload(None)
            return _success_response(env, payload)
        return make_error_response(
            env.request_id,
            ERR_KILL_SWITCH_ACTIVE,
            f"kill switch active; bridge world action {key} is paused",
            retryable=True,
        )

    if key in MEMORY_HANDLER_VERBS:
        unavailable = _memory_services_unavailable(env, services)
        if unavailable is not None:
            return unavailable
        return _success_response(env, await handle_memory_read(env, services))

    if key in MEMORY_WRITE_VERBS:
        unavailable = _memory_write_services_unavailable(env, services)
        if unavailable is not None:
            return unavailable
        try:
            payload = await handle_memory_write(env, services)
        except ValueError as exc:
            return make_error_response(env.request_id, ERR_INVALID_PAYLOAD, str(exc))
        return _success_response(env, payload)

    if key in MANAGEMENT_REVIEW_VERBS:
        unavailable = _management_services_unavailable(env, services)
        if unavailable is not None:
            return unavailable
        return _success_response(env, await handle_management_review(env, services))

    if key in SHARED_STATE_READ_VERBS:
        unavailable = _shared_state_services_unavailable(env, services)
        if unavailable is not None:
            return unavailable
        return _success_response(env, await handle_shared_state_read(env, services))

    if key in SHARED_STATE_WRITE_VERBS:
        unavailable = _shared_state_services_unavailable(env, services)
        if unavailable is not None:
            return unavailable
        try:
            payload = await handle_shared_state_write(env, services)
        except ValueError as exc:
            return make_error_response(env.request_id, ERR_INVALID_PAYLOAD, str(exc))
        return _success_response(env, payload)

    if key in CODE_EXECUTE_VERBS:
        unavailable = _code_services_unavailable(env, services)
        if unavailable is not None:
            return unavailable
        return _success_response(env, await handle_code_execute(env, services))

    if key in DIRECTOR_GATE_VERBS:
        return _success_response(env, await handle_director_gate(env, services))
    if key in COST_GATE_VERBS:
        return _success_response(env, await _handle_cost_gate(env, services))

    if key in ERRAND_POLL_VERBS:
        return _success_response(env, _handle_errand_poll(env))
    if key in ERRAND_COMPLETE_VERBS:
        return _success_response(env, await handle_errand_complete(env, services))

    return _success_response(env, STUB_HANDLERS[key](env))


def _extract_bearer_token(websocket: WebSocket) -> str | None:
    """Read the presented bearer token from the WS handshake (ADR §4).

    Prefer the ``Authorization: Bearer <token>`` header. A ``token`` query
    param is accepted only when ``MINECRAFT_BRIDGE_ALLOW_QUERY_TOKEN`` is
    explicitly enabled for constrained local clients that cannot set WebSocket
    request headers. Returns ``None`` when no usable token is present.
    """
    auth = websocket.headers.get("authorization")
    if auth:
        scheme, _, param = auth.partition(" ")
        if scheme.lower() == "bearer" and param:
            return param
    if os.environ.get(BRIDGE_QUERY_TOKEN_ENV, "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    token = websocket.query_params.get("token")
    return token or None


@bridge_router.websocket(BRIDGE_WS_PATH)
async def bridge_ws(websocket: WebSocket) -> None:
    """Authenticated bridge WebSocket (ADR §1/§4).

    Fail-closed BEFORE ``accept()``: a missing/empty server token, or a
    missing/malformed/wrong presented token, closes the socket with code 1008
    and dispatches nothing. After auth, loop: decode a frame, run the pure
    dispatch policy, send back a contract-valid response. Errors after the
    handshake degrade to ``ok=false`` responses, never an open socket with no
    answer.
    """
    expected = os.environ.get(BRIDGE_TOKEN_ENV, "")
    presented = _extract_bearer_token(websocket)
    if not expected or not presented or not hmac.compare_digest(presented, expected):
        # No agent_id/peer logged: the connection is unauthenticated, so any
        # identity claim it carries is unproven (ADR §4).
        logger.warning("Bridge handshake rejected: missing or invalid token")
        await websocket.close(code=WS_POLICY_VIOLATION)
        return

    await websocket.accept()
    try:
        while True:
            try:
                raw = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except ValueError as exc:
                # Frame was not JSON at all — still answer with a typed,
                # contract-valid error rather than dropping the connection.
                started = time.perf_counter()
                raw = None  # never parsed; observed under the 'unparseable' verb
                response = make_error_response(
                    UNKNOWN_REQUEST_ID,
                    ERR_INVALID_PAYLOAD,
                    f"frame was not valid JSON: {exc}",
                )
            else:
                started = time.perf_counter()
                services = _services_from_websocket(websocket)
                response = await build_bridge_response_with_services(raw, services)

            # E4-7 (#546): one correlation id per frame. Echo the caller's
            # trace_id, or mint one when the (additive) field is absent, so the
            # request is traceable end-to-end by a single id in BOTH logs.
            trace_id = _resolve_trace_id(raw)

            # E4-6 (#545): perception.report / action.result are Node->Python
            # *reports*. The wire response is still the same contract-valid stub
            # build_bridge_response already produced ({"accepted": true}); the
            # additional work here is emitting the schema-validated event onto
            # the bus so it is observable on the Python side *before* the ack
            # goes out. Only routed for an ok response to an in-registry inbound
            # verb — the envelope and payload are then guaranteed already
            # validated. The resolved trace_id rides along so the emitted bus
            # event joins the same correlation id (E4-7).
            if response.ok and isinstance(raw, dict):
                inbound_key = service_key(raw.get("service", ""), raw.get("method", ""))
                if inbound_key in inbound.INBOUND_VERBS and not (
                    inbound_key in WORLD_ACTION_SAFE_IDLE_VERBS
                    and await _kill_switch_active(services)
                ):
                    await inbound.dispatch_inbound(
                        BridgeRequest.model_validate(raw),
                        trace_id=trace_id,
                        services=services,
                    )

            # E4-7 (#546): observe + correlate EVERY settled frame — success,
            # ok=false, and the unparseable path alike — so the counters'
            # denominator is honest and a single id greps across both languages.
            latency_ms = (time.perf_counter() - started) * 1000.0
            response.trace_id = trace_id
            observability.log_bridge_event(
                logger,
                trace_id=trace_id,
                request_id=response.request_id,
                agent_id=_str_field_from_raw(raw, "agent_id", "unknown"),
                service=_str_field_from_raw(raw, "service", "-"),
                method=_str_field_from_raw(raw, "method", "-"),
                ok=response.ok,
                latency_ms=latency_ms,
                error_code=response.error.code if response.error else None,
                direction="inbound",
            )
            observability.record_call(
                verb=_verb_from_raw(raw),
                ok=response.ok,
                latency_ms=latency_ms,
                error_code=response.error.code if response.error else None,
            )
            await websocket.send_json(response.model_dump())
    except WebSocketDisconnect:
        pass


# Defensive parity check: the dispatch table must cover exactly the closed
# registry. Importing SERVICE_REGISTRY here (rather than at module top) keeps
# the failure message local to this invariant.
def _assert_handlers_cover_registry() -> None:
    from core.bridge.contract import SERVICE_REGISTRY

    handled = (
        set(STUB_HANDLERS)
        | MEMORY_HANDLER_VERBS
        | MEMORY_WRITE_VERBS
        | MANAGEMENT_REVIEW_VERBS
        | SHARED_STATE_VERBS
        | CODE_EXECUTE_VERBS
        | DIRECTOR_GATE_VERBS
        | ERRAND_VERBS
        | KILL_STATUS_VERBS
    )
    missing = set(SERVICE_REGISTRY) - handled
    extra = handled - set(SERVICE_REGISTRY)
    if missing or extra:
        raise RuntimeError(
            f"bridge handlers out of sync with SERVICE_REGISTRY: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )


_assert_handlers_cover_registry()

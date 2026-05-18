"""Python bridge server endpoint (issue #542, E4-3).

A single authenticated, namespaced WebSocket surface that Node Minecraft bots
connect to, mounted into the existing FastAPI app alongside ``/ws``. This issue
is *only* the bridge surface: handshake auth, envelope/version/contract
validation, and a dispatch table whose handlers return contract-valid **stub**
payloads. Real memory/management/cost wiring is explicitly out of scope (E5/E8);
the perception/action inbound channel is E4-5/E4-6.

Everything here is fixed by ADR ``docs/decisions/0010-bridge-protocol.md``
(#540, E4-1) and validated against the versioned contract from
:mod:`core.bridge.contract` (#541, E4-2):

* ADR §1 — endpoint is ``/api/minecraft/bridge/ws``, one WebSocket per bot.
* ADR §4 — **fail-closed** shared-secret bearer auth. A missing/empty server
  token, or a missing/malformed/wrong presented token, closes the socket with
  code ``1008`` *before* ``accept()``. No ``service`` is ever dispatched on an
  unauthenticated connection: there is no anonymous or "auth optional in dev"
  path to spend or in-world actions. This mirrors the constant-time check in
  ``core/admin/kill_switch_routes.py``.
* ADR §2/§3/§6 — every inbound frame is parsed as a :class:`BridgeRequest`,
  version-negotiated fail-closed on an unknown major, and validated against the
  closed per-verb registry. Every failure after ``accept()`` goes back as a
  contract-valid :class:`BridgeResponse` (``ok=false`` + typed error); only the
  handshake closes the socket.

There is no LLM runtime path in this issue: the endpoint dispatches to pure
stubs with no model calls. The nearest local smoke path is the dependency-free
``pnpm verify:bridge-server`` (``tests/backend/test_bridge_server.py``), which
exercises the real endpoint over an in-process WebSocket with no Docker/network.
"""

from __future__ import annotations

import hmac
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from core.bridge.contract import (
    ERR_INVALID_PAYLOAD,
    ERR_UNSUPPORTED_SERVICE,
    BridgeRequest,
    BridgeResponse,
    UnsupportedServiceError,
    is_supported_version,
    make_error_response,
    service_key,
    unsupported_version_response,
    validate_request,
    validate_response,
)

logger = logging.getLogger(__name__)

bridge_router = APIRouter(tags=["bridge"])

# ADR §1: the one namespaced bridge surface. Kept as a constant so the wiring
# test and the route declaration cannot drift.
BRIDGE_WS_PATH = "/api/minecraft/bridge/ws"

# ADR §4: the env var the Node client and this server share the secret through.
BRIDGE_TOKEN_ENV = "MINECRAFT_BRIDGE_TOKEN"

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


# ── Stub dispatch table (no business logic — E5/E8 own the real wiring) ──────

StubHandler = Callable[[BridgeRequest], dict[str, Any]]

# Each handler returns a payload that satisfies the verb's *response* schema in
# core/bridge/contract.py and nothing more. They run only after
# ``validate_request`` has accepted the inbound payload, so ``bridge.ping`` can
# safely index ``env.payload["message"]``. Keys must exactly match
# SERVICE_REGISTRY (asserted below + covered by the contract-parity test).
STUB_HANDLERS: dict[str, StubHandler] = {
    "bridge.ping": lambda env: {"pong": env.payload["message"]},
    "memory.recall": lambda env: {"results": []},
    "memory.write": lambda env: {"memory_id": env.request_id},
    "management.review": lambda env: {
        "verdict": "allow",
        "reason": "stub",
        "sanitized_text": None,
    },
    "cost.gate": lambda env: {
        "allowed": True,
        "reason": "stub",
        "remaining_budget_usd": 0.0,
    },
    "perception.report": lambda env: {"accepted": True},
    "action.result": lambda env: {"accepted": True},
}


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


def build_bridge_response(raw: Any) -> BridgeResponse:
    """Turn one decoded inbound frame into a contract-valid response envelope.

    Pure and synchronous so the dispatch policy is unit-testable without a
    socket. Order mirrors ADR §2→§3→§6: envelope shape, then version, then the
    closed per-verb registry, then the stub handler. Every branch returns a
    :class:`BridgeResponse`; the socket is never closed from here (handshake
    auth is the only path that closes it).
    """
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

    payload = STUB_HANDLERS[service_key(env.service, env.method)](env)
    response = BridgeResponse(request_id=env.request_id, ok=True, payload=payload)
    # Prove the stub honours the verb's response schema before it goes on the
    # wire — a stub that drifts from the contract should fail loudly here, not
    # silently ship an invalid frame to the Node side.
    validate_response(response, service=env.service, method=env.method)
    return response


def _extract_bearer_token(websocket: WebSocket) -> str | None:
    """Read the presented bearer token from the WS handshake (ADR §4).

    Prefer the ``Authorization: Bearer <token>`` header; fall back to a
    ``token`` query param for clients that cannot set WebSocket request headers.
    Returns ``None`` when no usable token is present.
    """
    auth = websocket.headers.get("authorization")
    if auth:
        scheme, _, param = auth.partition(" ")
        if scheme.lower() == "bearer" and param:
            return param
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
                response = make_error_response(
                    UNKNOWN_REQUEST_ID,
                    ERR_INVALID_PAYLOAD,
                    f"frame was not valid JSON: {exc}",
                )
            else:
                response = build_bridge_response(raw)
            await websocket.send_json(response.model_dump())
    except WebSocketDisconnect:
        pass


# Defensive parity check: the dispatch table must cover exactly the closed
# registry. Importing SERVICE_REGISTRY here (rather than at module top) keeps
# the failure message local to this invariant.
def _assert_handlers_cover_registry() -> None:
    from core.bridge.contract import SERVICE_REGISTRY

    missing = set(SERVICE_REGISTRY) - set(STUB_HANDLERS)
    extra = set(STUB_HANDLERS) - set(SERVICE_REGISTRY)
    if missing or extra:
        raise RuntimeError(
            f"STUB_HANDLERS out of sync with SERVICE_REGISTRY: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )


_assert_handlers_cover_registry()

"""Tests for the Python bridge server endpoint (issue #542, E4-3).

Acceptance bar: *the bridge endpoint accepts a valid signed message and echoes
a contract-valid stub response; it rejects unauthenticated calls.* These tests
exercise the **real** endpoint mounted on ``core.main:app`` over an in-process
Starlette ``TestClient`` WebSocket.

Dependency-free by design: ``TestClient(app)`` is used *without* its context
manager, so the FastAPI ``lifespan`` (which bootstraps Postgres/Redis) never
runs — the bridge endpoint touches no ``app.state``/services. No Docker, no
network, no LLM, so this runs in the existing ``backend-test`` CI job and is
the nearest local smoke path for this issue (which has no LLM runtime path).

What is covered:

* **Fail-closed auth (ADR §4)** — no token, wrong token, malformed header,
  *and* a server with no token configured are all rejected with WS close
  ``1008`` before ``accept()``; nothing is dispatched.
* **Authenticated happy path** — every one of the 7 closed-registry verbs
  round-trips a committed valid fixture and gets a contract-valid stub
  response (re-validated through ``contract.validate_response``).
* **Fail-closed protocol errors (ADR §2/§3/§6)** — bad envelope, unknown
  major version, unknown service, and a non-JSON frame each come back as a
  contract-valid ``ok=false`` response on a still-open socket.
* **Wiring** — the route is registered on the app and the stub table matches
  the closed registry exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.bridge import contract as c
from core.bridge.server import (
    BRIDGE_QUERY_TOKEN_ENV,
    BRIDGE_TOKEN_ENV,
    BRIDGE_WS_PATH,
    STUB_HANDLERS,
    UNKNOWN_REQUEST_ID,
    build_bridge_response,
)
from core.main import app

TOKEN = "test-bridge-secret"
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "bridge"

# Verb dir -> the exact stub payload core/bridge/server.py promises for it.
# request_id/message come from the committed request.valid.json fixtures.
_EXPECTED_STUB_PAYLOAD: dict[str, dict[str, Any]] = {
    "bridge.ping": {"pong": "hello"},
    "memory.recall": {"results": []},
    "memory.write": {"memory_id": "req-memory-write-0001"},
    "management.review": {"verdict": "allow", "reason": "stub", "sanitized_text": None},
    "cost.gate": {"allowed": True, "reason": "stub", "remaining_budget_usd": 0.0},
    "perception.report": {"accepted": True},
    "action.result": {"accepted": True},
}

ALL_VERBS = sorted(c.SERVICE_REGISTRY)


def _fixture(verb: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / verb / name).read_text())


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Configure the server-side shared secret for a test."""
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    return TOKEN


@pytest.fixture
def client() -> TestClient:
    # No `with TestClient(app)`: lifespan/bootstrap must not run (keeps this
    # dependency-free). websocket_connect works without it.
    return TestClient(app)


# ── Fail-closed authentication (ADR §4) ─────────────────────────────────────


def test_rejects_when_no_token_presented(token_env: str, client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(BRIDGE_WS_PATH):
            pass
    assert exc.value.code == 1008


def test_rejects_wrong_token(token_env: str, client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            BRIDGE_WS_PATH, headers={"Authorization": "Bearer not-the-secret"}
        ):
            pass
    assert exc.value.code == 1008


def test_rejects_malformed_authorization_header(token_env: str, client: TestClient) -> None:
    # Token value present but no "Bearer " scheme -> not a usable bearer token.
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(BRIDGE_WS_PATH, headers={"Authorization": TOKEN}):
            pass
    assert exc.value.code == 1008


def test_rejects_when_server_token_unset(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    # Even a "correct-looking" token must be refused when the server has no
    # secret configured: fail-closed, no anonymous/dev bypass (ADR §4).
    monkeypatch.delenv(BRIDGE_TOKEN_ENV, raising=False)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}):
            pass
    assert exc.value.code == 1008


def test_unauthenticated_socket_dispatches_nothing(token_env: str, client: TestClient) -> None:
    """A rejected handshake must never reach a service handler."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(BRIDGE_WS_PATH) as ws:
            # If we somehow got here, prove no verb was served.
            ws.send_json(_fixture("bridge.ping", "request.valid.json"))
            ws.receive_json()


# ── Authenticated happy path: every verb round-trips a stub ─────────────────


@pytest.mark.parametrize("verb", ALL_VERBS)
def test_valid_signed_message_echoes_contract_valid_stub(
    verb: str, token_env: str, client: TestClient
) -> None:
    request = _fixture(verb, "request.valid.json")
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        raw_response = ws.receive_json()

    response = c.BridgeResponse.model_validate(raw_response)
    assert response.ok is True
    assert response.error is None
    # request_id is echoed (ADR §2) for correlation.
    assert response.request_id == request["request_id"]
    assert response.payload == _EXPECTED_STUB_PAYLOAD[verb]

    # The stub payload must satisfy the verb's *response* schema in the
    # committed contract — re-validate independently of the server.
    parsed = c.validate_response(response, service=request["service"], method=request["method"])
    assert parsed is not None


def test_query_param_token_rejected_by_default(token_env: str, client: TestClient) -> None:
    """Bearer-in-URL auth is disabled by default to avoid token leakage."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{BRIDGE_WS_PATH}?token={TOKEN}"):
            pass
    assert exc.value.code == 1008


def test_token_accepted_via_query_param_when_explicitly_enabled(
    token_env: str, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """Constrained local clients may opt into ?token=, still using the same secret."""
    monkeypatch.setenv(BRIDGE_QUERY_TOKEN_ENV, "1")
    request = _fixture("bridge.ping", "request.valid.json")
    with client.websocket_connect(f"{BRIDGE_WS_PATH}?token={TOKEN}") as ws:
        ws.send_json(request)
        response = ws.receive_json()
    assert response["ok"] is True
    assert response["payload"] == {"pong": "hello"}


def test_connection_handles_multiple_sequential_messages(
    token_env: str, client: TestClient
) -> None:
    """One authenticated socket serves a stream of requests (the loop works)."""
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        for verb in ("bridge.ping", "memory.recall", "cost.gate"):
            ws.send_json(_fixture(verb, "request.valid.json"))
            response = ws.receive_json()
            assert response["ok"] is True, verb
            assert response["payload"] == _EXPECTED_STUB_PAYLOAD[verb], verb


# ── Fail-closed protocol errors come back as ok=false, socket stays open ─────


def test_invalid_payload_returns_typed_error(token_env: str, client: TestClient) -> None:
    # bridge.ping invalid fixture: valid envelope, payload missing "message".
    request = _fixture("bridge.ping", "request.invalid.json")
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == c.ERR_INVALID_PAYLOAD
    assert response["request_id"] == request["request_id"]
    assert response["retryable"] is False


def test_unknown_major_version_is_fail_closed(token_env: str, client: TestClient) -> None:
    request = _fixture("bridge.ping", "request.valid.json")
    request["version"] = "2.0"  # unknown major
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == c.ERR_UNSUPPORTED_VERSION
    assert response["retryable"] is False


def test_unknown_service_is_rejected(token_env: str, client: TestClient) -> None:
    request = _fixture("bridge.ping", "request.valid.json")
    request["service"] = "filesystem"
    request["method"] = "delete"
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == c.ERR_UNSUPPORTED_SERVICE


def test_unparseable_envelope_uses_sentinel_request_id(token_env: str, client: TestClient) -> None:
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json({"not": "an envelope"})
        response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == c.ERR_INVALID_PAYLOAD
    # request_id absent/unparseable -> non-empty sentinel (contract requires
    # min_length=1, so "" is impossible here).
    assert response["request_id"] == UNKNOWN_REQUEST_ID


def test_non_json_frame_returns_typed_error(token_env: str, client: TestClient) -> None:
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_text("this is not json {")
        response = ws.receive_json()

        assert response["ok"] is False
        assert response["error"]["code"] == c.ERR_INVALID_PAYLOAD
        assert response["request_id"] == UNKNOWN_REQUEST_ID

        # Socket still open: a parse failure is a typed response, not a
        # disconnect. Reuse the same socket to prove the loop continues.
        ws_request = _fixture("bridge.ping", "request.valid.json")
        ws.send_json(ws_request)
        assert ws.receive_json()["ok"] is True


# ── Pure dispatch policy (no socket) ────────────────────────────────────────


@pytest.mark.parametrize("verb", ALL_VERBS)
def test_build_bridge_response_is_contract_valid_per_verb(verb: str) -> None:
    request = _fixture(verb, "request.valid.json")
    response = build_bridge_response(request)
    assert response.ok is True
    assert response.payload == _EXPECTED_STUB_PAYLOAD[verb]
    c.validate_response(response, service=request["service"], method=request["method"])


def test_build_bridge_response_rejects_bad_envelope() -> None:
    response = build_bridge_response("definitely not an envelope")
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == c.ERR_INVALID_PAYLOAD
    assert response.request_id == UNKNOWN_REQUEST_ID


# ── Wiring guards ───────────────────────────────────────────────────────────


def test_bridge_route_is_mounted_on_app() -> None:
    paths = {route.path for route in app.routes if isinstance(getattr(route, "path", None), str)}
    assert BRIDGE_WS_PATH in paths


def test_stub_table_matches_closed_registry_exactly() -> None:
    assert set(STUB_HANDLERS) == set(c.SERVICE_REGISTRY)

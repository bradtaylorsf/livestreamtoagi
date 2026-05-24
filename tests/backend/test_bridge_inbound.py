"""Tests for the Node->Python perception/action-result channel (issue #545, E4-6).

Acceptance bar: *an in-game action produces a perception/result event
observable on the Python side; schema-validated.* These tests prove that end
to end by driving the **real** bridge endpoint mounted on ``core.main:app``
over an in-process Starlette ``TestClient`` WebSocket and asserting the event
is observed on the shared :data:`core.event_bus.event_bus` singleton *before*
the contract ack returns on the wire.

Dependency-free by design (same rationale as ``test_bridge_server.py``):
``TestClient(app)`` is used without its context manager so the FastAPI
``lifespan`` never runs; no Docker, network, or LLM. This is the nearest local
smoke path for this issue, which has no LLM runtime path — it is pure event
plumbing.

What is covered:

* **Acceptance** — ``perception.report`` and ``action.result`` each emit a
  schema-validated, fully attributed event on the bus, observable before the
  ``{"accepted": true}`` ack is sent; the response stays the unchanged E4-3
  stub.
* **Scope boundary** — a non-inbound verb (``bridge.ping``) emits no bridge
  event; an invalid inbound payload returns the typed ``ok=false`` error and
  emits nothing (the event is only ever emitted from a validated payload).
* **Schema validation** — the handlers re-parse the payload into the typed
  contract model and reject one that does not match it.
* **Wiring** — the inbound verb set agrees with the handler map and the closed
  contract registry.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from core.bridge import contract as c
from core.bridge import inbound
from core.bridge.server import BRIDGE_TOKEN_ENV, BRIDGE_WS_PATH
from core.event_bus import EventType, event_bus
from core.main import app
from core.redis_keys import ScopedRedis
from core.shared_state import SharedWorkingState

TOKEN = "test-bridge-secret"
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "backend" / "fixtures" / "bridge"


class _MemoryRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}

    async def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def rpush(self, key: str, *values: str) -> int:
        self.lists.setdefault(key, []).extend(values)
        return len(self.lists[key])

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        data = self.lists.get(key, [])
        if start < 0:
            start = max(len(data) + start, 0)
        if stop < 0:
            stop = len(data) + stop
        return data[start : stop + 1]

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        data = self.lists.get(key, [])
        if start < 0:
            start = max(len(data) + start, 0)
        if stop < 0:
            stop = len(data) + stop
        self.lists[key] = data[start : stop + 1]
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            removed += int(self.hashes.pop(key, None) is not None)
            removed += int(self.lists.pop(key, None) is not None)
        return removed


def _fixture(verb: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / verb / name).read_text())


@pytest.fixture
def token_env(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    return TOKEN


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # No `with TestClient(app)`: lifespan/bootstrap must not run.
    monkeypatch.delattr(app.state, "services", raising=False)
    return TestClient(app)


@pytest.fixture
def captured() -> Iterator[dict[str, list[dict[str, Any]]]]:
    """Subscribe to both bridge event types on the singleton bus.

    Yields a {"perception": [...], "action": [...]} record of every event
    *data* body seen, and unsubscribes on teardown so the module-level
    ``event_bus`` singleton does not leak callbacks across tests.
    """
    seen: dict[str, list[dict[str, Any]]] = {"perception": [], "action": []}

    async def on_perception(event: dict[str, Any]) -> None:
        seen["perception"].append(event["data"])

    async def on_action(event: dict[str, Any]) -> None:
        seen["action"].append(event["data"])

    event_bus.on(EventType.BRIDGE_PERCEPTION, on_perception)
    event_bus.on(EventType.BRIDGE_ACTION_RESULT, on_action)
    try:
        yield seen
    finally:
        event_bus.off(EventType.BRIDGE_PERCEPTION, on_perception)
        event_bus.off(EventType.BRIDGE_ACTION_RESULT, on_action)


def _envelope(verb: str, name: str = "request.valid.json") -> c.BridgeRequest:
    return c.BridgeRequest.model_validate(_fixture(verb, name))


# ── Acceptance: an in-world report is observable on the Python side ──────────


def test_perception_report_emits_observable_schema_valid_event(
    token_env: str, client: TestClient, captured: dict[str, list[dict[str, Any]]]
) -> None:
    request = _fixture("perception.report", "request.valid.json")
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        raw_response = ws.receive_json()

    # The event was emitted/observed *before* the ack reached the client:
    # emit() is awaited before send_json in the receive loop.
    assert len(captured["perception"]) == 1
    assert not captured["action"]
    data = captured["perception"][0]
    # Full attribution off the envelope.
    assert data["request_id"] == request["request_id"]
    assert data["agent_id"] == request["agent_id"]
    assert data["run_id"] == request["run_id"]
    assert data["simulation_id"] == request["simulation_id"]
    assert data["observations"] == request["payload"]["observations"]
    # The emitted body is schema-valid against the typed contract model.
    c.PerceptionReportRequest.model_validate({"observations": data["observations"]})

    # The wire response is the unchanged E4-3 contract-valid stub.
    response = c.BridgeResponse.model_validate(raw_response)
    assert response.ok is True
    assert response.payload == {"accepted": True}
    assert response.request_id == request["request_id"]
    c.validate_response(response, service="perception", method="report")


def test_action_result_emits_observable_schema_valid_event(
    token_env: str, client: TestClient, captured: dict[str, list[dict[str, Any]]]
) -> None:
    request = _fixture("action.result", "request.valid.json")
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        raw_response = ws.receive_json()

    assert len(captured["action"]) == 1
    assert not captured["perception"]
    data = captured["action"][0]
    assert data["request_id"] == request["request_id"]
    assert data["agent_id"] == request["agent_id"]
    assert data["run_id"] == request["run_id"]
    assert data["simulation_id"] == request["simulation_id"]
    # Typed action fields are spread in, not a raw payload dict.
    assert data["action_id"] == request["payload"]["action_id"]
    assert data["status"] == request["payload"]["status"]
    assert data["detail"] == request["payload"]["detail"]
    c.ActionResultRequest.model_validate(
        {"action_id": data["action_id"], "status": data["status"], "detail": data["detail"]}
    )

    response = c.BridgeResponse.model_validate(raw_response)
    assert response.ok is True
    assert response.payload == {"accepted": True}
    c.validate_response(response, service="action", method="result")


def test_sequential_reports_each_emit_one_event(
    token_env: str, client: TestClient, captured: dict[str, list[dict[str, Any]]]
) -> None:
    """One socket carrying several reports emits one event per report."""
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        for _ in range(3):
            ws.send_json(_fixture("perception.report", "request.valid.json"))
            assert ws.receive_json()["ok"] is True
        ws.send_json(_fixture("action.result", "request.valid.json"))
        assert ws.receive_json()["ok"] is True

    assert len(captured["perception"]) == 3
    assert len(captured["action"]) == 1


# ── Scope boundary: only the two inbound verbs emit, only when valid ────────


def test_non_inbound_verb_emits_no_bridge_event(
    token_env: str, client: TestClient, captured: dict[str, list[dict[str, Any]]]
) -> None:
    request = _fixture("bridge.ping", "request.valid.json")
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        assert ws.receive_json()["ok"] is True

    assert captured["perception"] == []
    assert captured["action"] == []


def test_invalid_perception_payload_emits_nothing_and_typed_error(
    token_env: str, client: TestClient, captured: dict[str, list[dict[str, Any]]]
) -> None:
    """A payload that fails the verb schema is rejected before any emit."""
    request = _fixture("perception.report", "request.invalid.json")
    with client.websocket_connect(
        BRIDGE_WS_PATH, headers={"Authorization": f"Bearer {TOKEN}"}
    ) as ws:
        ws.send_json(request)
        response = ws.receive_json()

    assert response["ok"] is False
    assert response["error"]["code"] == c.ERR_INVALID_PAYLOAD
    assert captured["perception"] == []
    assert captured["action"] == []


# ── Handler-level units ─────────────────────────────────────────────────────


async def test_handle_perception_report_emits_validated_event(
    captured: dict[str, list[dict[str, Any]]],
) -> None:
    env = _envelope("perception.report")
    ack = await inbound.handle_perception_report(env)

    assert ack == {"accepted": True}
    assert len(captured["perception"]) == 1
    assert captured["perception"][0]["observations"] == env.payload["observations"]


async def test_handle_perception_report_canonicalizes_agent_id(
    captured: dict[str, list[dict[str, Any]]],
) -> None:
    env = _envelope("perception.report")
    env.agent_id = "Alpha"

    ack = await inbound.handle_perception_report(env)

    assert ack == {"accepted": True}
    assert len(captured["perception"]) == 1
    assert captured["perception"][0]["agent_id"] == "alpha"


async def test_handle_action_result_emits_validated_event(
    captured: dict[str, list[dict[str, Any]]],
) -> None:
    env = _envelope("action.result")
    ack = await inbound.handle_action_result(env)

    assert ack == {"accepted": True}
    assert len(captured["action"]) == 1
    assert captured["action"][0]["status"] == env.payload["status"]


async def test_repeated_blocked_action_results_emit_distress_to_shared_state(
    captured: dict[str, list[dict[str, Any]]],
) -> None:
    sim_id = uuid.uuid4()
    redis = _MemoryRedis()
    services = SimpleNamespace(redis=redis)
    distress: list[dict[str, Any]] = []

    async def on_distress(event: dict[str, Any]) -> None:
        distress.append(event["data"])

    event_bus.on(EventType.DISTRESS_REPORTED, on_distress)
    try:
        for idx in range(inbound.REPEATED_FAILURE_THRESHOLD):
            env = _envelope("action.result")
            env.simulation_id = str(sim_id)
            env.agent_id = "Pixel"
            env.request_id = f"req-action-blocked-{idx}"
            env.payload = {
                "action_id": f"path-{idx}",
                "status": "failure",
                "outcome_class": "blocked",
                "detail": "path blocked by terrain",
            }
            assert await inbound.handle_action_result(env, services=services) == {
                "accepted": True
            }
    finally:
        event_bus.off(EventType.DISTRESS_REPORTED, on_distress)

    assert len(captured["action"]) == inbound.REPEATED_FAILURE_THRESHOLD
    assert distress
    assert distress[0]["danger"]["kind"] == "repeated_failure"
    state = SharedWorkingState(ScopedRedis(redis, sim_id))
    dangers = await state.get_unresolved_dangers()
    tasks = await state.get_tasks()
    assert dangers[0].agent_id == "pixel"
    assert dangers[0].recovery_status == "rescue_dispatched"
    assert tasks[0].id == f"rescue-{dangers[0].danger_id}"


async def test_dispatch_inbound_routes_by_verb(
    captured: dict[str, list[dict[str, Any]]],
) -> None:
    assert await inbound.dispatch_inbound(_envelope("perception.report")) == {"accepted": True}
    assert await inbound.dispatch_inbound(_envelope("action.result")) == {"accepted": True}
    assert len(captured["perception"]) == 1
    assert len(captured["action"]) == 1


async def test_handler_rejects_payload_not_matching_typed_schema(
    captured: dict[str, list[dict[str, Any]]],
) -> None:
    """The handler re-parses the payload, so a non-schema body fails closed.

    The envelope itself is valid (``payload`` is an opaque object), so this can
    only be caught by the handler's typed re-parse — which is the guarantee
    that the emitted event is schema-validated.
    """
    env = _envelope("perception.report")
    env.payload = {"observations": "not-a-list"}
    with pytest.raises(ValidationError):
        await inbound.handle_perception_report(env)
    assert captured["perception"] == []


# ── Wiring guards ───────────────────────────────────────────────────────────


def test_inbound_verbs_match_handlers_and_registry() -> None:
    assert set(inbound.INBOUND_HANDLERS) == set(inbound.INBOUND_VERBS)
    assert set(inbound.INBOUND_VERBS) <= set(c.SERVICE_REGISTRY)
    assert sorted(inbound.INBOUND_VERBS) == ["action.result", "perception.report"]


def test_bridge_event_types_exist() -> None:
    assert EventType.BRIDGE_PERCEPTION.value == "bridge_perception"
    assert EventType.BRIDGE_ACTION_RESULT.value == "bridge_action_result"

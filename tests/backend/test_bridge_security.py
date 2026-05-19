"""Security review tests for the Minecraft bridge (issue #548, E4-9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from core.bridge.contract import PROTOCOL_VERSION, BridgeRequest, CostContext
from core.bridge.server import (
    BRIDGE_QUERY_TOKEN_ENV,
    BRIDGE_TOKEN_ENV,
    BRIDGE_WS_PATH,
    STUB_HANDLERS,
    bridge_router,
)

TOKEN = "test-bridge-security-secret"  # noqa: S105 - test-only shared secret
REPO_ROOT = Path(__file__).resolve().parents[2]
THREAT_MODEL = REPO_ROOT / "docs" / "minecraft" / "bridge-threat-model.md"


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(bridge_router)
    return TestClient(app)


def _request(service: str, method: str) -> dict[str, Any]:
    payload = (
        {"agent_id": "fake-node", "action": "test-spend", "estimated_cost_usd": 1.0}
        if service == "cost"
        else {"action_id": "act-1", "status": "success", "detail": "ok"}
    )
    return BridgeRequest(
        version=PROTOCOL_VERSION,
        request_id=f"security-{service}-{method}",
        agent_id="fake-node",
        run_id="run-security",
        simulation_id="00000000-0000-0000-0000-000000000000",
        service=service,
        method=method,
        payload=payload,
        deadline_ms=5000,
        cost_context=CostContext(
            agent_tier="conversation",
            budget_bucket="bridge-security",
            estimated_cost_usd=0.0,
        ),
    ).model_dump()


def test_threat_model_documents_required_mitigations() -> None:
    doc = THREAT_MODEL.read_text().lower()
    required = [
        "minecraft_bridge_token",
        "authorization: bearer",
        "minecraft_bridge_allow_query_token",
        "replay",
        "request_id",
        "injection",
        "closed service registry",
        "denial of service",
        "minecraft_bridge_max_inflight",
        "no unauthenticated path",
    ]
    for phrase in required:
        assert phrase in doc


def test_query_token_auth_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    monkeypatch.delenv(BRIDGE_QUERY_TOKEN_ENV, raising=False)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"{BRIDGE_WS_PATH}?token={TOKEN}"):
            pass

    assert exc.value.code == 1008


@pytest.mark.parametrize(("service", "method"), [("cost", "gate"), ("action", "result")])
def test_unauthenticated_spend_or_action_messages_dispatch_nothing(
    service: str,
    method: str,
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    called: list[str] = []

    def _record_dispatch(env: BridgeRequest) -> dict[str, Any]:
        called.append(f"{env.service}.{env.method}")
        if env.service == "cost":
            return {"allowed": True, "reason": "test", "remaining_budget_usd": 1.0}
        return {"accepted": True}

    monkeypatch.setitem(STUB_HANDLERS, f"{service}.{method}", _record_dispatch)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(BRIDGE_WS_PATH) as ws:
            ws.send_json(_request(service, method))
            ws.receive_json()

    assert exc.value.code == 1008
    assert called == []

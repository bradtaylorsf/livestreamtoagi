"""Tests for the E13-3 livestream stream overlay status feed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventType
from core.models import AgentConfig, AgentStatus
from core.public_routes import router as public_router

STREAM_STATUSES = {"idle", "talking", "building", "active", "waiting", "error"}


def _make_agent_config(**overrides: object) -> AgentConfig:
    defaults = {
        "id": "vera",
        "display_name": "Vera",
        "role": "Showrunner",
        "model_conversation": "anthropic/claude-haiku-4.5",
        "model_building": "anthropic/claude-sonnet-4.5",
        "voice_id": "en-US-AriaNeural",
        "color_hex": "#00FFFF",
        "chattiness": 0.7,
        "initiative": 0.8,
        "interrupt_tendency": 0.2,
        "eavesdrop_tendency": 0.1,
        "closing_weight": 0.3,
        "status": AgentStatus.active,
        "system_prompt": "You are Vera.",
        "behaviors": {},
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


@pytest.fixture
def overlay_client():
    vera = _make_agent_config()
    rex = _make_agent_config(id="rex", display_name="Rex", role="Engineer")

    registry = MagicMock()
    registry.get_all_agents.return_value = [vera, rex]

    db = MagicMock()
    db.fetch = AsyncMock(return_value=[])

    now = datetime.now(UTC).timestamp()
    event_bus = SimpleNamespace(
        _history=[
            {
                "event_type": EventType.AGENT_SPEAK.value,
                "timestamp": now,
                "data": {"agent_id": "vera", "topic": "opening the stream"},
            },
            {
                "event_type": EventType.AGENT_ACTION.value,
                "timestamp": now,
                "data": {"agent_id": "rex", "action": "building"},
            },
        ],
    )

    services = SimpleNamespace(
        db=db,
        agent_registry=registry,
        agent_state_manager=None,
        event_bus=event_bus,
    )

    app = FastAPI()
    app.include_router(public_router)

    with patch("core.public_routes._get_services", return_value=services):
        with TestClient(app) as client:
            yield client, db, registry


def test_agent_status_endpoint_returns_overlay_schema(overlay_client) -> None:
    client, *_ = overlay_client

    response = client.get("/api/stream/agent-status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"agents", "updated_at"}
    assert payload["updated_at"]
    assert payload["agents"] == [
        {
            "id": "vera",
            "display_name": "Vera",
            "status": "talking",
            "last_action_at": payload["agents"][0]["last_action_at"],
            "current_topic": "opening the stream",
        },
        {
            "id": "rex",
            "display_name": "Rex",
            "status": "building",
            "last_action_at": payload["agents"][1]["last_action_at"],
            "current_topic": None,
        },
    ]
    assert payload["agents"][0]["last_action_at"]
    assert payload["agents"][1]["last_action_at"]


def test_agent_status_endpoint_surfaces_registry_ids(overlay_client) -> None:
    client, *_ = overlay_client

    response = client.get("/api/stream/agent-status")

    assert [agent["id"] for agent in response.json()["agents"]] == ["vera", "rex"]


def test_agent_status_endpoint_uses_stream_status_enum(overlay_client) -> None:
    client, *_ = overlay_client

    response = client.get("/api/stream/agent-status")

    statuses = {agent["status"] for agent in response.json()["agents"]}
    assert statuses <= STREAM_STATUSES


def test_agent_status_endpoint_sets_cors_and_cache_headers(overlay_client) -> None:
    client, *_ = overlay_client

    response = client.get("/api/stream/agent-status", headers={"Origin": "http://127.0.0.1:8765"})
    options = client.options("/api/stream/agent-status")

    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert options.status_code == 204
    assert options.headers["access-control-allow-origin"] == "*"
    assert "GET" in options.headers["access-control-allow-methods"]


def test_overlay_static_files_have_obs_mount_points() -> None:
    root = Path(__file__).resolve().parents[2]
    overlay_dir = root / "scripts" / "livestream" / "overlay"
    index = (overlay_dir / "index.html").read_text()
    script = (overlay_dir / "overlay.js").read_text()
    styles = (overlay_dir / "overlay.css").read_text()

    assert (overlay_dir / "index.html").is_file()
    assert (overlay_dir / "overlay.js").is_file()
    assert (overlay_dir / "overlay.css").is_file()
    assert 'id="overlay-top-bar"' in index
    assert 'id="overlay-agents"' in index
    assert "DEFAULT_API_BASE" in script
    assert "http://127.0.0.1:8010" in script
    assert 'params.get("api")' in script
    assert "background: transparent" in styles

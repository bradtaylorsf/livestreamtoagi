"""Tests for the public ``/api/simulations/{sim_id}/replay-cues`` endpoint.

The endpoint feeds the headless replay page (``website/src/app/.../replay``)
that the render pipeline captures into MP4. It must agree byte-for-byte
with the render-script's audio cue parser, otherwise bubbles drift out of
sync with the TTS audio.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_app():
    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.disconnect = AsyncMock()
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetchrow = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.disconnect = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    mock_registry = MagicMock()
    mock_registry.get_all_agents.return_value = []
    mock_registry.get_agent.side_effect = lambda aid: None

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis
    mock_services.agent_registry = mock_registry

    mock_lifespan_services = MagicMock()
    mock_lifespan_services.db = mock_db
    mock_lifespan_services.redis = mock_redis
    mock_lifespan_services.agent_registry = mock_registry
    mock_lifespan_services.llm_client = None
    mock_lifespan_services.core_memory = None
    mock_lifespan_services.config_loader = MagicMock(
        start_watching=AsyncMock(),
        stop_watching=AsyncMock(),
    )
    mock_lifespan_services.cost_repo = MagicMock()
    mock_lifespan_services.memory_repo = MagicMock()
    mock_lifespan_services.token_counter = MagicMock()
    mock_lifespan_services.goal_manager = MagicMock()
    mock_lifespan_services.agent_state_manager = MagicMock()
    mock_lifespan_services.dream_manager = MagicMock()
    mock_lifespan_services.event_bus = MagicMock()

    env_overrides = {
        "OPENROUTER_API_KEY": "sk-test-fake-key",
        "DATABASE_URL": "postgresql://agi:devpassword@localhost:5434/livestream_agi",
        "ADMIN_PASSWORD": "test-admin",
    }

    with (
        patch.dict(os.environ, env_overrides),
        patch("core.public_routes._get_services", return_value=mock_services),
        patch("core.public_routes._get_db", return_value=mock_db),
        patch("core.public_routes._get_registry", return_value=mock_registry),
        patch("core.public_routes._get_redis", return_value=mock_redis),
        patch("core.main.bootstrap_services", AsyncMock(return_value=mock_lifespan_services)),
        patch("core.main.shutdown_services", AsyncMock()),
        patch("core.main.init_core_memories", AsyncMock(return_value=[])),
        patch("core.main.start_scheduler"),
        patch("core.main.stop_scheduler"),
    ):
        from core.main import app

        with TestClient(app) as client:
            yield client, mock_db


class TestReplayCuesEndpoint:
    def test_returns_ordered_cues_with_start_seconds(self, mock_app):
        client, mock_db = mock_app
        sim_id = uuid.uuid4()
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "participants": ["vera", "rex"],
                    "content": "[vera]: morning team",
                    "created_at": base,
                },
                {
                    "participants": ["vera", "rex"],
                    "content": "[rex]: hi vera",
                    "created_at": base.replace(second=12),
                },
                {
                    "participants": ["vera", "rex"],
                    "content": "[vera]: let's go over the plan",
                    "created_at": base.replace(second=20),
                },
            ]
        )

        resp = client.get(f"/api/simulations/{sim_id}/replay-cues")
        assert resp.status_code == 200
        body = resp.json()
        cues = body["cues"]
        assert [c["agent_id"] for c in cues] == ["vera", "rex", "vera"]
        assert [c["text"] for c in cues] == [
            "morning team",
            "hi vera",
            "let's go over the plan",
        ]
        assert [c["start_seconds"] for c in cues] == [0.0, 12.0, 20.0]
        assert body["duration_seconds"] == 20.0

    def test_skips_rows_without_speaker_prefix(self, mock_app):
        client, mock_db = mock_app
        base = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "participants": ["vera"],
                    "content": "system: budget warning",
                    "created_at": base,
                },
                {
                    "participants": ["vera"],
                    "content": "[vera]: noted",
                    "created_at": base.replace(second=3),
                },
            ]
        )
        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        cues = resp.json()["cues"]
        assert len(cues) == 1
        assert cues[0]["agent_id"] == "vera"

    def test_empty_simulation_returns_empty_cues(self, mock_app):
        client, mock_db = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cues"] == []
        assert body["duration_seconds"] == 0.0

    def test_speaker_normalized_to_lowercase(self, mock_app):
        client, mock_db = mock_app
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "participants": ["vera"],
                    "content": "[VERA]: hello",
                    "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
                }
            ]
        )
        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        cues = resp.json()["cues"]
        assert cues[0]["agent_id"] == "vera"

    def test_payload_shape_matches_typescript_interface(self, mock_app):
        """Cue objects expose only the three fields ReplayCue declares."""
        client, mock_db = mock_app
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "participants": ["vera"],
                    "content": "[vera]: hi",
                    "created_at": datetime(2026, 5, 8, 12, 0, tzinfo=UTC),
                }
            ]
        )
        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        cue = resp.json()["cues"][0]
        assert set(cue.keys()) == {"agent_id", "text", "start_seconds"}

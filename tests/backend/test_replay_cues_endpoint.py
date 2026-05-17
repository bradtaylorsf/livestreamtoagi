"""Tests for ``GET /api/simulations/{sim_id}/replay-cues``.

The endpoint must split intra-row multi-speaker turns into per-cue
entries (so the replay page renders short bubbles instead of giant
transcript dumps), strip any ``[speaker]`` prefix fragments from cue
text, and return a ``duration_seconds`` that reflects the end of the
replay (last cue start + estimated read-time of its text).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _sim_row(
    *,
    config: dict | None = None,
    agents_participated: list[str] | None = None,
) -> dict:
    return {
        "id": uuid.uuid4(),
        "name": "replay-test",
        "config": config or {},
        "agents_participated": agents_participated or [],
    }


@pytest.fixture
def replay_client():
    """A TestClient with public-routes deps mocked, like ``test_public_api``."""
    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.disconnect = AsyncMock()
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetchrow = AsyncMock(return_value=_sim_row())

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.disconnect = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()

    mock_registry = MagicMock()

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
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "") or "sk-test-fake-key",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "")
        or "postgresql://agi:devpassword@localhost:5434/livestream_agi",
        "ADMIN_PASSWORD": "test-admin-password",
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

        try:
            with TestClient(app) as client:
                yield client, mock_db
        finally:
            app.dependency_overrides.clear()


def _row(content: str, second: int) -> dict:
    return {
        "participants": ["vera", "rex", "grok", "sentinel"],
        "content": content,
        "created_at": datetime(2026, 5, 8, 12, 0, second, tzinfo=UTC),
    }


class TestReplayCuesEndpoint:
    def test_multi_speaker_row_yields_one_cue_per_speaker(self, replay_client):
        client, mock_db = replay_client
        # One transcript row containing three bracketed speakers.
        mock_db.fetch = AsyncMock(
            return_value=[
                _row("[vera]: morning team [rex]: budget update [grok]: I object", 0),
            ]
        )

        sim_id = uuid.uuid4()
        resp = client.get(f"/api/simulations/{sim_id}/replay-cues")
        assert resp.status_code == 200
        body = resp.json()

        assert body["sim_id"] == str(sim_id)
        cues = body["cues"]
        assert len(cues) == 3
        assert [c["agent_id"] for c in cues] == ["vera", "rex", "grok"]
        assert cues[0]["text"] == "morning team"
        assert cues[1]["text"] == "budget update"
        assert cues[2]["text"] == "I object"

    def test_no_cue_text_contains_speaker_fragments(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(
            return_value=[
                _row("[vera]: hello [rex]: world", 0),
                _row("[grok]: chaos [sentinel]: stop", 5),
            ]
        )

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        cues = resp.json()["cues"]
        for cue in cues:
            assert "[" not in cue["text"]
            assert "]" not in cue["text"]

    def test_unknown_speaker_skipped(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(
            return_value=[
                _row("[vera]: hi [unknown]: ??? [rex]: ok", 0),
            ]
        )

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        cues = resp.json()["cues"]
        assert [c["agent_id"] for c in cues] == ["vera", "rex"]

    def test_duration_exceeds_last_cue_start(self, replay_client):
        """duration_seconds must reflect the end of replay, not last start."""
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(
            return_value=[
                _row("[vera]: opening line", 0),
                _row("[rex]: a few sentences worth of closing remarks", 30),
            ]
        )

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        body = resp.json()
        last_start = body["cues"][-1]["start_seconds"]
        assert body["duration_seconds"] > last_start

    def test_empty_transcripts_returns_empty_cues_zero_duration(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(return_value=[])

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        body = resp.json()
        assert body["cues"] == []
        assert body["duration_seconds"] == 0.0
        assert body["agent_roster"] == []

    def test_agent_roster_prefers_effective_agents(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchrow = AsyncMock(
            return_value=_sim_row(
                config={
                    "effective_agents": ["vera", "rex"],
                    "scenario_agents": ["vera", "rex", "grok"],
                    "excluded_agents": ["rex"],
                },
                agents_participated=["grok"],
            )
        )

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        assert resp.json()["agent_roster"] == ["vera", "rex"]

    def test_agent_roster_uses_scenario_agents_minus_exclusions(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchrow = AsyncMock(
            return_value=_sim_row(
                config={
                    "scenario_agents": ["vera", "rex", "grok", "rex"],
                    "excluded_agents": ["grok"],
                },
                agents_participated=["pixel"],
            )
        )

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        assert resp.json()["agent_roster"] == ["vera", "rex"]

    def test_agent_roster_falls_back_to_agents_participated(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchrow = AsyncMock(
            return_value=_sim_row(agents_participated=["pixel", "aurora", "pixel"])
        )

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        assert resp.json()["agent_roster"] == ["pixel", "aurora"]

    def test_agent_roster_falls_back_to_unique_cue_agents(self, replay_client):
        client, mock_db = replay_client
        mock_db.fetch = AsyncMock(
            return_value=[
                _row("[vera]: hello [rex]: hi [vera]: back again", 0),
            ]
        )
        mock_db.fetchrow = AsyncMock(return_value=_sim_row())

        resp = client.get(f"/api/simulations/{uuid.uuid4()}/replay-cues")
        assert resp.status_code == 200
        assert resp.json()["agent_roster"] == ["vera", "rex"]

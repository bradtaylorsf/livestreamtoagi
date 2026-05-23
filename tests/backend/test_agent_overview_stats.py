"""Tests for the agent overview stat-card endpoints (issue #406).

The Overview tab on /agents/<id> shows three numbers (conversations,
artifacts, total cost) that must all share the same scope. With no
`simulation_id` query param, each endpoint aggregates across every
simulation the agent has participated in. With an explicit `simulation_id`,
each endpoint scopes to that single simulation.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.models import AgentConfig, AgentStatus


def _make_agent_config(**overrides) -> AgentConfig:
    defaults = {
        "id": "vera",
        "display_name": "Vera",
        "role": "Showrunner",
        "model_conversation": "claude-haiku-4-5",
        "model_building": "claude-sonnet-4-6",
        "voice_id": "en-US-AriaNeural",
        "color_hex": "#00FFFF",
        "chattiness": 0.7,
        "initiative": 0.8,
        "interrupt_tendency": 0.2,
        "eavesdrop_tendency": 0.1,
        "closing_weight": 0.3,
        "status": AgentStatus.active,
        "system_prompt": "You are Vera.",
        "behaviors": {"tone": "professional"},
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


@pytest.fixture
def stats_app():
    """TestClient with mocks tuned for the conversations/artifacts/costs endpoints."""
    vera = _make_agent_config()

    mock_registry = MagicMock()
    mock_registry.get_all_agents.return_value = [vera]
    mock_registry.get_agent.side_effect = lambda aid: {"vera": vera}.get(aid)

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.disconnect = AsyncMock()
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchrow = AsyncMock(return_value=None)
    mock_db.fetchval = AsyncMock(return_value=0)

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.disconnect = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()

    mock_artifact_repo = MagicMock()
    mock_artifact_repo.count_by_agent = AsyncMock(return_value=0)
    mock_artifact_repo.get_all_artifacts = AsyncMock(return_value=([], 0))

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis
    mock_services.agent_registry = mock_registry
    mock_services.artifact_repo = mock_artifact_repo
    mock_services.relationship_repo = None
    mock_services.world_repo = None
    mock_services.llm_client = None

    mock_lifespan_services = MagicMock()
    mock_lifespan_services.db = mock_db
    mock_lifespan_services.redis = mock_redis
    mock_lifespan_services.agent_registry = mock_registry
    mock_lifespan_services.llm_client = None
    mock_lifespan_services.core_memory = None
    mock_lifespan_services.config_loader = MagicMock(
        start_watching=AsyncMock(), stop_watching=AsyncMock()
    )

    env_overrides = {
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "") or "sk-test-fake",
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

        with TestClient(app) as client:
            yield client, mock_db, mock_artifact_repo


def test_agent_conversations_unscoped_counts_across_all_sims(stats_app):
    """An agent in 5 conversations across 2 simulations returns total=5
    when /api/agents/{id}/conversations is called without simulation_id."""
    client, mock_db, _ = stats_app

    sim_a = uuid.uuid4()
    sim_b = uuid.uuid4()
    rows = []
    for sid in [sim_a, sim_a, sim_a, sim_b, sim_b]:
        rows.append(
            {
                "id": uuid.uuid4(),
                "trigger_type": "audience",
                "trigger_details": {},
                "initial_energy": 0.5,
                "final_energy": 0.4,
                "turn_count": 3,
                "participating_agents": ["vera", "rex"],
                "topics_discussed": [],
                "closed_by": "natural",
                "location": "town_square",
                "audience_events_during": 0,
                "config_hash": "hash",
                "started_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
                "ended_at": datetime(2026, 5, 1, tzinfo=timezone.utc),
                "simulation_id": sid,
            }
        )

    mock_db.fetch = AsyncMock(return_value=rows)
    mock_db.fetchval = AsyncMock(return_value=len(rows))

    resp = client.get("/api/agents/vera/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5

    # Sanity check: the count query did NOT scope to a simulation_id
    count_queries = [
        call for call in mock_db.fetchval.call_args_list
        if "COUNT" in call[0][0].upper() and "conversations" in call[0][0]
    ]
    assert count_queries, "Expected a COUNT query against conversations"
    for call in count_queries:
        assert "simulation_id" not in call[0][0]


def test_agent_conversations_scoped_filters_to_one_sim(stats_app):
    """When simulation_id is provided, the count is filtered to that sim."""
    client, mock_db, _ = stats_app
    sim_id = uuid.uuid4()
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchval = AsyncMock(return_value=2)

    resp = client.get(f"/api/agents/vera/conversations?simulation_id={sim_id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

    count_queries = [
        call for call in mock_db.fetchval.call_args_list
        if "COUNT" in call[0][0].upper() and "conversations" in call[0][0]
    ]
    assert count_queries
    for call in count_queries:
        assert "simulation_id" in call[0][0]


def test_agent_artifacts_unscoped_counts_across_all_sims(stats_app):
    """Artifacts endpoint returns lifetime total when no simulation_id given."""
    client, _, mock_artifact_repo = stats_app
    mock_artifact_repo.get_all_artifacts = AsyncMock(return_value=([], 12))

    resp = client.get("/api/agents/vera/artifacts")
    assert resp.status_code == 200
    assert resp.json()["total"] == 12

    # The repo call must not pass a simulation_id when one isn't requested.
    call_kwargs = mock_artifact_repo.get_all_artifacts.call_args.kwargs
    assert call_kwargs.get("simulation_id") is None


def test_agent_artifacts_scoped_passes_sim_id_to_repo(stats_app):
    """When simulation_id is provided, it is passed through to the repo."""
    client, _, mock_artifact_repo = stats_app
    sim_id = uuid.uuid4()
    mock_artifact_repo.get_all_artifacts = AsyncMock(return_value=([], 4))

    resp = client.get(f"/api/agents/vera/artifacts?simulation_id={sim_id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 4

    call_kwargs = mock_artifact_repo.get_all_artifacts.call_args.kwargs
    assert call_kwargs.get("simulation_id") == sim_id


def test_overview_stats_use_consistent_lifetime_scope(stats_app):
    """The three queries that drive the overview stat card (conversations,
    artifacts, costs) must all run unscoped when no simulation_id is given —
    matching the cost number's current behavior so no stat is misleading."""
    client, mock_db, mock_artifact_repo = stats_app
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetchrow = AsyncMock(return_value={
        "total": "0", "input_tokens": 0, "output_tokens": 0,
    })
    mock_artifact_repo.get_all_artifacts = AsyncMock(return_value=([], 0))

    # These are the three calls the AgentDetailClient overview useEffect makes.
    convs = client.get("/api/agents/vera/conversations?limit=1&offset=0")
    arts = client.get("/api/agents/vera/artifacts?limit=1&offset=0")
    costs = client.get("/api/agents/vera/costs")
    assert convs.status_code == 200
    assert arts.status_code == 200
    assert costs.status_code == 200

    # None of these should have scoped to a simulation_id.
    for call in mock_db.fetchval.call_args_list:
        assert "simulation_id" not in call[0][0]
    for call in mock_db.fetch.call_args_list:
        assert "simulation_id" not in call[0][0]
    art_kwargs = mock_artifact_repo.get_all_artifacts.call_args.kwargs
    assert art_kwargs.get("simulation_id") is None

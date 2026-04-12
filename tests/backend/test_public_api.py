"""Tests for public API endpoints (core/public_routes.py)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.models import AgentConfig, AgentStatus


# ── Fixtures ───────────────────────────────────────────────────


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
        "system_prompt": "You are Vera, the showrunner.",
        "behaviors": {"tone": "professional"},
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


@pytest.fixture
def mock_app():
    """Create a TestClient with fully mocked dependencies."""
    vera = _make_agent_config()
    rex = _make_agent_config(
        id="rex", display_name="Rex", role="Engineer",
        color_hex="#FF0000", chattiness=0.5, initiative=0.6,
    )

    mock_registry = MagicMock()
    mock_registry.get_all_agents.return_value = [vera, rex]
    mock_registry.get_agent.side_effect = lambda aid: {"vera": vera, "rex": rex}.get(aid)

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.disconnect = AsyncMock()
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchrow = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.disconnect = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis
    mock_services.agent_registry = mock_registry
    mock_services.relationship_repo = None
    mock_services.artifact_repo = None
    mock_services.config_version_repo = None
    mock_services.world_repo = None
    mock_services.llm_client = None

    env_overrides = {
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "") or "sk-test-fake-key",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "") or "postgresql://agi:devpassword@localhost:5434/livestream_agi",
        "ADMIN_PASSWORD": "test-admin-password",
    }
    with (
        patch.dict(os.environ, env_overrides),
        patch("core.public_routes._get_services", return_value=mock_services),
        patch("core.public_routes._get_db", return_value=mock_db),
        patch("core.public_routes._get_registry", return_value=mock_registry),
        patch("core.public_routes._get_redis", return_value=mock_redis),
    ):
        from core.admin.dependencies import get_db, get_llm, get_redis, get_registry, require_admin
        from core.main import app

        # Override admin sub-router dependencies (admin_routes.py was split into core/admin/)
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_redis] = lambda: mock_redis
        app.dependency_overrides[get_registry] = lambda: mock_registry
        app.dependency_overrides[get_llm] = lambda: MagicMock()
        app.dependency_overrides[require_admin] = lambda: None

        try:
            with TestClient(app) as client:
                yield client, mock_db, mock_registry, mock_redis, mock_services
        finally:
            app.dependency_overrides.clear()


# ── Agent Endpoints ───────────────────────────────────────────


class TestAgentEndpoints:
    def test_list_agents(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "vera"
        assert data[0]["display_name"] == "Vera"
        assert data[0]["role"] == "Showrunner"
        assert data[0]["color"] == "#00FFFF"

    def test_get_agent(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents/vera")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "vera"
        assert data["display_name"] == "Vera"
        assert data["conversation_model"] == "claude-haiku-4-5"

    def test_get_agent_not_found(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents/nonexistent")
        assert resp.status_code == 404

    def test_get_agent_journal(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[
            {
                "id": 1,
                "agent_id": "vera",
                "reflection_type": "daily",
                "content": "A good day.",
                "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
        ])
        resp = client.get("/api/agents/vera/journal")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_id"] == "vera"
        assert data[0]["content"] == "A good day."

    def test_get_agent_relationships_empty(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents/vera/relationships")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_agent_conversations(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/agents/vera/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_agent_artifacts_empty(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents/vera/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    def test_get_agent_evolution_empty(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents/vera/evolution")
        assert resp.status_code == 200
        assert resp.json() == []


# ── Chat Endpoint ─────────────────────────────────────────────


class TestChatEndpoint:
    def test_chat_no_llm(self, mock_app):
        client, *_ = mock_app
        resp = client.post(
            "/api/agents/vera/chat",
            json={"message": "Hello Vera"},
        )
        assert resp.status_code == 503

    def test_chat_rate_limit(self, mock_app):
        client, _, _, mock_redis, mock_services = mock_app
        mock_redis.incr = AsyncMock(return_value=11)
        resp = client.post(
            "/api/agents/vera/chat",
            json={"message": "Hello Vera"},
        )
        assert resp.status_code == 429


# ── Conversation Endpoints ────────────────────────────────────


class TestConversationEndpoints:
    def test_list_conversations(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_conversation_not_found(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}")
        assert resp.status_code == 404

    def test_get_conversation_invalid_id(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/conversations/not-a-uuid")
        assert resp.status_code == 400

    def test_get_conversation_selections(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}/selections")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_conversation_filters_by_simulation_id(self, mock_app):
        """GET /api/conversations/{id} must filter by LIVE_SIMULATION_ID."""
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}")
        assert resp.status_code == 404
        # Verify the query included simulation_id filter
        call_args = mock_db.fetchrow.call_args
        query = call_args[0][0]
        assert "simulation_id" in query

    def test_get_selections_filters_by_simulation_id(self, mock_app):
        """GET /api/conversations/{id}/selections must filter by LIVE_SIMULATION_ID."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        conv_id = str(uuid.uuid4())
        resp = client.get(f"/api/conversations/{conv_id}/selections")
        assert resp.status_code == 200
        # Verify the query included simulation_id filter
        call_args = mock_db.fetch.call_args
        query = call_args[0][0]
        assert "simulation_id" in query


# ── Blog Endpoints ────────────────────────────────────────────


class TestBlogEndpoints:
    def test_list_blog_posts(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/blog")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert "slug" in data[0]
        assert "title" in data[0]

    def test_get_blog_post(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/blog/why-agi-is-tongue-in-cheek")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "why-agi-is-tongue-in-cheek"
        assert "content" in data

    def test_get_blog_post_not_found(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/blog/nonexistent-post")
        assert resp.status_code == 404


# ── Eval Endpoints ────────────────────────────────────────────


class TestEvalEndpoints:
    def test_get_evals_summary(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/evals/summary")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_evals_history(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/evals/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_eval_categories(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[
            {"category": "creativity"},
            {"category": "safety"},
        ])
        resp = client.get("/api/evals/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert "creativity" in data
        assert "safety" in data

    def test_get_eval_runs_empty(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/evals/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_eval_runs_with_model_versions(self, mock_app):
        client, mock_db, *_ = mock_app
        run_id = uuid.uuid4()
        sim_id = uuid.uuid4()
        mock_db.fetch = AsyncMock(side_effect=[
            # First call: get_all_eval_runs
            [{
                "id": run_id,
                "simulation_id": sim_id,
                "eval_suite": "full",
                "status": "completed",
                "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "overall_score": 72.5,
                "cost": 0.05,
                "model_versions": (
                    '{"vera": {"conversation": "anthropic/claude-haiku-4.5",'
                    ' "building": "anthropic/claude-sonnet-4.6"}}'
                ),
                "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            }],
            # Second call: get_eval_results for this run
            [],
        ])
        resp = client.get("/api/evals/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["model_versions"]["vera"] == "anthropic/claude-haiku-4.5"

    def test_get_eval_latest_empty(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/evals/latest")
        assert resp.status_code == 200
        assert resp.json() is None

    def test_get_eval_run_detail_not_found(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        run_id = str(uuid.uuid4())
        resp = client.get(f"/api/evals/runs/{run_id}")
        assert resp.status_code == 404


# ── World Endpoints ───────────────────────────────────────────


class TestWorldEndpoints:
    def test_get_world_chunks_empty(self, mock_app):
        client, _, _, _, mock_services = mock_app
        mock_services.world_repo = None
        resp = client.get("/api/world/chunks")
        assert resp.status_code == 200
        assert resp.json() == []


# ── Challenge Endpoints ───────────────────────────────────────


class TestChallengeEndpoints:
    def test_get_challenges(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/challenges")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_challenges_with_filters(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/challenges?status=pending&sort=most_upvoted")
        assert resp.status_code == 200

    def test_submit_challenge(self, mock_app):
        client, mock_db, _, mock_redis, _ = mock_app
        mock_redis.incr = AsyncMock(return_value=1)
        mock_db.fetchrow = AsyncMock(return_value={
            "id": 1,
            "description": "Build a garden",
            "submitted_by": "viewer1",
            "source": "website",
            "status": "pending",
            "assigned_agents": None,
            "result": None,
            "cost_estimate": None,
            "actual_cost": None,
            "votes": 0,
            "category": "building",
            "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "completed_at": None,
        })
        resp = client.post("/api/challenges", json={
            "description": "Build a garden",
            "category": "building",
            "submitter_name": "viewer1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Build a garden"
        assert data["category"] == "building"
        assert data["votes"] == 0

    def test_submit_challenge_rate_limit(self, mock_app):
        client, _, _, mock_redis, _ = mock_app
        mock_redis.incr = AsyncMock(return_value=6)
        resp = client.post("/api/challenges", json={
            "description": "Too many requests",
        })
        assert resp.status_code == 429

    def test_upvote_challenge(self, mock_app):
        client, mock_db, _, mock_redis, _ = mock_app
        mock_redis.get = AsyncMock(return_value=None)
        mock_db.fetchrow = AsyncMock(return_value={
            "id": 1,
            "description": "Build a garden",
            "submitted_by": "viewer1",
            "source": "website",
            "status": "pending",
            "assigned_agents": None,
            "result": None,
            "cost_estimate": None,
            "actual_cost": None,
            "votes": 1,
            "category": "building",
            "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "completed_at": None,
        })
        resp = client.post("/api/challenges/1/upvote")
        assert resp.status_code == 200
        assert resp.json()["votes"] == 1

    def test_upvote_challenge_duplicate(self, mock_app):
        client, _, _, mock_redis, _ = mock_app
        mock_redis.get = AsyncMock(return_value="1")
        resp = client.post("/api/challenges/1/upvote")
        assert resp.status_code == 409

    def test_upvote_challenge_not_found(self, mock_app):
        client, mock_db, _, mock_redis, _ = mock_app
        mock_redis.get = AsyncMock(return_value=None)
        mock_db.fetchrow = AsyncMock(return_value=None)
        resp = client.post("/api/challenges/999/upvote")
        assert resp.status_code == 404


# ── Stats Endpoint ────────────────────────────────────────────


class TestStatsEndpoint:
    def test_get_stats(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_simulations" in data
        assert "total_agents" in data
        assert data["total_agents"] == 2


# ── Lore Endpoint ─────────────────────────────────────────────


class TestLoreEndpoint:
    def test_get_lore(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/lore")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_lore_with_filters(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/lore?agent=vera&event_type=discovery")
        assert resp.status_code == 200


# ── CORS Headers ──────────────────────────────────────────────


class TestCORS:
    def test_cors_headers_present(self, mock_app):
        client, *_ = mock_app
        resp = client.options(
            "/api/agents",
            headers={
                "Origin": "http://localhost:4000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") in (
            "http://localhost:4000", "*",
        )

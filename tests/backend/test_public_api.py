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
    # Mock services object for the FastAPI lifespan to use instead of a real
    # bootstrap. Dependency-injection overrides below are what the route
    # handlers actually consume; this is just enough shape for startup/shutdown.
    mock_lifespan_services = MagicMock()
    mock_lifespan_services.db = mock_db
    mock_lifespan_services.redis = mock_redis
    mock_lifespan_services.agent_registry = mock_registry
    mock_lifespan_services.llm_client = None
    mock_lifespan_services.core_memory = None
    mock_lifespan_services.config_loader = MagicMock(
        start_watching=AsyncMock(), stop_watching=AsyncMock(),
    )
    mock_lifespan_services.cost_repo = MagicMock()
    mock_lifespan_services.memory_repo = MagicMock()
    mock_lifespan_services.token_counter = MagicMock()
    mock_lifespan_services.goal_manager = MagicMock()
    mock_lifespan_services.agent_state_manager = MagicMock()
    mock_lifespan_services.dream_manager = MagicMock()
    mock_lifespan_services.event_bus = MagicMock()

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

    def test_list_agents_no_filter_does_not_scope_costs(self, mock_app):
        """`GET /api/agents` (no sim_id) must not scope cost lookup to LIVE_SIMULATION_ID."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" not in call[0][0]

    def test_list_agents_with_simulation_id_scopes_costs(self, mock_app):
        """When `simulation_id` is provided, cost lookup is scoped to that simulation."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)
        sim_id = uuid.uuid4()
        resp = client.get(f"/api/agents?simulation_id={sim_id}")
        assert resp.status_code == 200
        cost_queries = [
            c for c in mock_db.fetch.call_args_list
            if "cost_events" in c[0][0]
        ]
        assert cost_queries, "Expected at least one cost_events query"
        for call in cost_queries:
            assert "simulation_id" in call[0][0]

    def test_list_agents_includes_conversation_and_artifact_counts(self, mock_app):
        """Agent card returns conversation_count and artifact_count populated from DB."""
        client, mock_db, _, _, mock_services = mock_app
        mock_artifact_repo = MagicMock()
        mock_artifact_repo.count_by_agent = AsyncMock(return_value=7)
        mock_services.artifact_repo = mock_artifact_repo
        mock_db.fetch = AsyncMock(return_value=[])

        async def fetchval_side_effect(query: str, *args, **kwargs):
            if "conversations" in query:
                return 11
            return 0

        mock_db.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert all(a["conversation_count"] == 11 for a in data)
        assert all(a["artifact_count"] == 7 for a in data)

    def test_get_agent_core_memory_unscoped(self, mock_app):
        """Core memory endpoint must not default-scope to LIVE_SIMULATION_ID."""
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/agents/vera/core-memory")
        assert resp.status_code == 200
        for call in mock_db.fetchrow.call_args_list:
            assert "simulation_id" not in call[0][0]
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" not in call[0][0]

    def test_get_agent_core_memory_scoped(self, mock_app):
        """When simulation_id is provided, core-memory query filters by it."""
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        mock_db.fetch = AsyncMock(return_value=[])
        sim_id = uuid.uuid4()
        resp = client.get(f"/api/agents/vera/core-memory?simulation_id={sim_id}")
        assert resp.status_code == 200
        # The fetchrow query for current core memory must scope by simulation_id
        assert any(
            "simulation_id" in call[0][0] for call in mock_db.fetchrow.call_args_list
        )

    def test_get_agent_recall_memories_unscoped(self, mock_app):
        """Recall-memories endpoint defaults to all simulations (no LIVE filter)."""
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/agents/vera/recall-memories")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" not in call[0][0]
        for call in mock_db.fetchval.call_args_list:
            assert "simulation_id" not in call[0][0]

    def test_get_agent_recall_memories_scoped(self, mock_app):
        """Recall-memories endpoint with explicit simulation_id scopes correctly."""
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        sim_id = uuid.uuid4()
        resp = client.get(f"/api/agents/vera/recall-memories?simulation_id={sim_id}")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" in call[0][0]

    def test_get_agent_costs_unscoped(self, mock_app):
        """Costs endpoint without simulation_id aggregates across all sims."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchrow = AsyncMock(return_value={
            "total": 0, "input_tokens": 0, "output_tokens": 0,
        })
        resp = client.get("/api/agents/vera/costs")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" not in call[0][0]
        for call in mock_db.fetchrow.call_args_list:
            assert "simulation_id" not in call[0][0]

    def test_get_agent_costs_scoped(self, mock_app):
        """Costs endpoint with simulation_id filters by it."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchrow = AsyncMock(return_value={
            "total": 0, "input_tokens": 0, "output_tokens": 0,
        })
        sim_id = uuid.uuid4()
        resp = client.get(f"/api/agents/vera/costs?simulation_id={sim_id}")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" in call[0][0]

    def test_get_agent_journal_unscoped(self, mock_app):
        """Journal endpoint without simulation_id returns all-sim entries."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/agents/vera/journal")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" not in call[0][0]

    def test_get_agent_conversations_unscoped(self, mock_app):
        """Conversations-by-agent without simulation_id is unfiltered."""
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/agents/vera/conversations")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            assert "simulation_id" not in call[0][0]
        for call in mock_db.fetchval.call_args_list:
            assert "simulation_id" not in call[0][0]


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

    def test_list_conversations_no_filter_returns_all_simulations(self, mock_app):
        """Without simulation_id, the list endpoint must not scope to LIVE_SIMULATION_ID."""
        client, mock_db, *_ = mock_app
        sim_a = uuid.uuid4()
        sim_b = uuid.uuid4()
        rows = [
            {
                "id": uuid.uuid4(),
                "trigger_type": "audience",
                "trigger_details": {},
                "initial_energy": 0.5,
                "final_energy": None,
                "participating_agents": ["vera"],
                "topics_discussed": [],
                "turn_count": 0,
                "closed_by": None,
                "location": None,
                "config_hash": None,
                "simulation_id": sim_a,
                "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "ended_at": None,
            },
            {
                "id": uuid.uuid4(),
                "trigger_type": "scheduled",
                "trigger_details": {},
                "initial_energy": 0.5,
                "final_energy": None,
                "participating_agents": ["rex"],
                "topics_discussed": [],
                "turn_count": 0,
                "closed_by": None,
                "location": None,
                "config_hash": None,
                "simulation_id": sim_b,
                "started_at": datetime(2026, 4, 2, tzinfo=timezone.utc),
                "ended_at": None,
            },
        ]
        mock_db.fetchval = AsyncMock(return_value=2)
        mock_db.fetch = AsyncMock(return_value=rows)
        resp = client.get("/api/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        sim_ids = {item["simulation_id"] for item in data["items"]}
        assert sim_ids == {str(sim_a), str(sim_b)}
        # Neither query should filter by simulation_id
        list_query = mock_db.fetch.call_args[0][0]
        assert "simulation_id" not in list_query
        count_query = mock_db.fetchval.call_args[0][0]
        assert "simulation_id" not in count_query

    def test_list_conversations_with_simulation_id_scopes(self, mock_app):
        """When simulation_id IS provided, results are scoped to that simulation."""
        client, mock_db, *_ = mock_app
        sim_a = uuid.uuid4()
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get(f"/api/conversations?simulation_id={sim_a}")
        assert resp.status_code == 200
        list_query = mock_db.fetch.call_args[0][0]
        assert "simulation_id" in list_query
        count_query = mock_db.fetchval.call_args[0][0]
        assert "simulation_id" in count_query

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

    def test_get_conversation_resolves_for_non_live_simulation(self, mock_app):
        """GET /api/conversations/{id} must resolve regardless of simulation_id."""
        client, mock_db, *_ = mock_app
        conv_id = uuid.uuid4()
        non_live_sim_id = uuid.uuid4()
        conversation_row = {
            "id": conv_id,
            "trigger_type": "audience",
            "trigger_details": {},
            "initial_energy": 0.5,
            "final_energy": None,
            "participating_agents": ["vera"],
            "topics_discussed": [],
            "turn_count": 0,
            "closed_by": None,
            "location": None,
            "config_hash": None,
            "simulation_id": non_live_sim_id,
            "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "ended_at": None,
        }
        fetchrow_calls: list[str] = []

        async def fetchrow_side_effect(query: str, *args, **kwargs):
            fetchrow_calls.append(query)
            if "FROM conversations" in query:
                return conversation_row
            return None

        mock_db.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get(f"/api/conversations/{conv_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(conv_id)
        assert data["simulation_id"] == str(non_live_sim_id)
        # Conversation lookup query must NOT filter on simulation_id
        conv_query = next(q for q in fetchrow_calls if "FROM conversations" in q)
        assert "simulation_id" not in conv_query

    def test_get_selections_resolves_for_non_live_simulation(self, mock_app):
        """GET /api/conversations/{id}/selections must not filter by simulation_id."""
        client, mock_db, *_ = mock_app
        conv_id = uuid.uuid4()
        non_live_sim_id = uuid.uuid4()
        mock_db.fetch = AsyncMock(return_value=[
            {
                "id": 1,
                "conversation_id": conv_id,
                "turn_number": 1,
                "selected_agent_id": "vera",
                "was_interrupt": False,
                "agent_scores": {},
                "active_agents": [],
                "detected_topic": None,
                "previous_speaker_id": None,
                "conversation_energy": 0.5,
                "trigger_type": None,
                "config_hash": None,
                "simulation_id": non_live_sim_id,
                "timestamp": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
        ])
        resp = client.get(f"/api/conversations/{conv_id}/selections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["selected_agent_id"] == "vera"
        # The list query must NOT filter on simulation_id
        call_args = mock_db.fetch.call_args
        query = call_args[0][0]
        assert "simulation_id" not in query


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
            # Second call: batch-fetch simulation names
            [{"id": sim_id, "name": "Test Simulation"}],
            # Third call: get_eval_results for this run
            [],
        ])
        resp = client.get("/api/evals/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["model_versions"]["vera"] == "anthropic/claude-haiku-4.5"
        assert data[0]["simulation_name"] == "Test Simulation"

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

    def test_get_eval_run_detail_includes_status(self, mock_app):
        """Frontend polls this endpoint and reads `status` to detect completion."""
        client, mock_db, *_ = mock_app
        run_id = uuid.uuid4()
        sim_id = uuid.uuid4()
        mock_db.fetchrow = AsyncMock(side_effect=[
            # eval_repo.get_eval_run -> single eval run row
            {
                "id": run_id,
                "simulation_id": sim_id,
                "eval_suite": "full",
                "status": "completed",
                "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "overall_score": 80.0,
                "cost": 0.10,
                "model_versions": "{}",
                "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
            # simulations name lookup
            {"name": "Test Sim"},
        ])
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get(f"/api/evals/runs/{run_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"


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

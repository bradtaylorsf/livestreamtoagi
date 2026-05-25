"""Tests for public API endpoints (core/public_routes.py)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timezone
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
        id="rex",
        display_name="Rex",
        role="Engineer",
        color_hex="#FF0000",
        chattiness=0.5,
        initiative=0.6,
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
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "")
        or "test-openrouter-key-for-unit-tests",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "")
        or "postgresql://agi:devpassword@localhost:5434/livestream_agi",
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


# ── Local Video Serving ─────────────────────────────────────────


class TestLocalVideoServing:
    def test_serves_uuid_mp4_from_configured_output_dir(self, mock_app, tmp_path, monkeypatch):
        client, *_ = mock_app
        sim_id = uuid.uuid4()
        video_path = tmp_path / f"{sim_id}.mp4"
        video_path.write_bytes(b"fake mp4 bytes")
        monkeypatch.setenv("VIDEO_STORAGE", "local")
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path))

        resp = client.get(f"/videos/{sim_id}.mp4")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("video/mp4")
        assert resp.content == b"fake mp4 bytes"

    def test_video_head_returns_mp4_content_type(self, mock_app, tmp_path, monkeypatch):
        client, *_ = mock_app
        sim_id = uuid.uuid4()
        (tmp_path / f"{sim_id}.mp4").write_bytes(b"fake mp4 bytes")
        monkeypatch.setenv("VIDEO_STORAGE", "local")
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path))

        resp = client.head(f"/videos/{sim_id}.mp4")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("video/mp4")

    def test_rejects_non_uuid_and_traversal_video_paths(self, mock_app, tmp_path, monkeypatch):
        client, *_ = mock_app
        monkeypatch.setenv("VIDEO_STORAGE", "local")
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path))

        assert client.get("/videos/not-a-uuid.mp4").status_code == 404
        assert client.get("/videos/%2E%2E%2Fsecret.mp4").status_code == 404

    def test_local_video_route_disabled_for_s3_storage(self, mock_app, tmp_path, monkeypatch):
        client, *_ = mock_app
        sim_id = uuid.uuid4()
        (tmp_path / f"{sim_id}.mp4").write_bytes(b"fake mp4 bytes")
        monkeypatch.setenv("VIDEO_STORAGE", "s3")
        monkeypatch.setenv("VIDEO_OUTPUT_DIR", str(tmp_path))

        resp = client.get(f"/videos/{sim_id}.mp4")

        assert resp.status_code == 404


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
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "agent_id": "vera",
                    "reflection_type": "daily",
                    "content": "A good day.",
                    "token_count": 12,
                    "image_url": "https://example.com/journals/vera.png",
                    "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                },
            ]
        )
        resp = client.get("/api/agents/vera/journal")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_id"] == "vera"
        assert data[0]["content"] == "A good day."
        assert data[0]["image_url"] == "https://example.com/journals/vera.png"

    def test_get_agent_journal_returns_embodied_entries(self, mock_app, monkeypatch):
        """Journal publishing returns embodied-run reflections and dreams unchanged."""
        monkeypatch.setenv("CONVERSATION_MODE", "embodied")
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "id": 2,
                    "agent_id": "vera",
                    "reflection_type": "6hour",
                    "content": "Placed oak planks to finish the workshop doorway.",
                    "token_count": 18,
                    "image_url": "data:image/png;base64,embodied",
                    "created_at": datetime(2026, 4, 2, 8, 0, tzinfo=UTC),
                },
                {
                    "id": 3,
                    "agent_id": "vera",
                    "reflection_type": "dream",
                    "content": "Dreamed of expanding the workshop into a theater.",
                    "token_count": 14,
                    "image_url": None,
                    "created_at": datetime(2026, 4, 2, 2, 0, tzinfo=UTC),
                },
            ]
        )

        resp = client.get("/api/agents/vera/journal")

        assert resp.status_code == 200
        data = resp.json()
        assert [entry["reflection_type"] for entry in data] == ["6hour", "dream"]
        assert data[0]["content"] == "Placed oak planks to finish the workshop doorway."
        assert data[0]["image_url"] == "data:image/png;base64,embodied"
        assert data[1]["content"] == "Dreamed of expanding the workshop into a theater."
        assert data[1]["image_url"] is None

    def test_get_agent_relationships_empty(self, mock_app):
        client, *_ = mock_app
        resp = client.get("/api/agents/vera/relationships")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.parametrize(
        "sentiment_in, trust_in, sentiment_out, trust_out",
        [
            # Decimal("0.0") and Decimal("0") are falsy in Python — must still
            # be reported as 0.0, not silently replaced by the default.
            ("0.0", "0.0", 0.0, 0.0),
            ("0", "0", 0.0, 0.0),
            ("-0.5", "0.5", -0.5, 0.5),
            (None, None, 0.0, 0.0),
        ],
    )
    def test_get_agent_relationships_preserves_zero_scores(
        self, mock_app, sentiment_in, trust_in, sentiment_out, trust_out
    ):
        from decimal import Decimal

        from core.models import Relationship

        client, *_, mock_services = mock_app
        rel = Relationship(
            id=uuid.uuid4(),
            simulation_id=uuid.uuid4(),
            agent_id="vera",
            target_agent_id="rex",
            sentiment_score=Decimal(sentiment_in) if sentiment_in is not None else None,
            trust_score=Decimal(trust_in) if trust_in is not None else None,
            interaction_count=3,
            relationship_summary="ok",
        )
        mock_repo = MagicMock()
        mock_repo.get_all_for_agent = AsyncMock(return_value=[rel])
        mock_services.relationship_repo = mock_repo

        resp = client.get("/api/agents/vera/relationships")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["sentiment_score"] == sentiment_out
        assert data[0]["trust_score"] == trust_out

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
        cost_queries = [c for c in mock_db.fetch.call_args_list if "cost_events" in c[0][0]]
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
        assert any("simulation_id" in call[0][0] for call in mock_db.fetchrow.call_args_list)

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
        mock_db.fetchrow = AsyncMock(
            return_value={
                "total": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
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
        mock_db.fetchrow = AsyncMock(
            return_value={
                "total": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
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
        mock_db.fetch = AsyncMock(
            return_value=[
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
            ]
        )
        resp = client.get(f"/api/conversations/{conv_id}/selections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["selected_agent_id"] == "vera"
        # The list query must NOT filter on simulation_id
        call_args = mock_db.fetch.call_args
        query = call_args[0][0]
        assert "simulation_id" not in query


# ── Simulations Endpoints ──────────────────────────────────────


class TestSimulationsEndpoint:
    def test_list_simulations_excludes_live_by_default(self, mock_app):
        """The seeded live channel row must not show up in /api/simulations."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations")
        assert resp.status_code == 200

        # The list query and the count query must both filter out live rows
        list_sql = mock_db.fetch.call_args[0][0]
        count_sql = mock_db.fetchval.call_args[0][0]
        assert "is_live IS NOT TRUE" in list_sql
        assert "is_live IS NOT TRUE" in count_sql

    def test_list_simulations_include_live_param_drops_filter(self, mock_app):
        """Pass include_live=true to opt back in to seeing the live channel row."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations?include_live=true")
        assert resp.status_code == 200

        list_sql = mock_db.fetch.call_args[0][0]
        count_sql = mock_db.fetchval.call_args[0][0]
        assert "is_live" not in list_sql
        assert "is_live" not in count_sql

    def test_list_simulations_is_featured_filter(self, mock_app):
        """is_featured=true filters both the list and count queries."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations?is_featured=true")
        assert resp.status_code == 200

        list_call = mock_db.fetch.call_args
        count_call = mock_db.fetchval.call_args
        assert "is_featured" in list_call[0][0]
        assert "is_featured" in count_call[0][0]
        # the bound parameter for is_featured should be True
        assert True in list_call[0][1:]
        assert True in count_call[0][1:]

    def test_list_simulations_is_featured_omitted_does_not_filter(self, mock_app):
        """No is_featured query param means the column is NOT in the WHERE clause."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations")
        assert resp.status_code == 200

        list_sql = mock_db.fetch.call_args[0][0]
        count_sql = mock_db.fetchval.call_args[0][0]
        assert "is_featured" not in list_sql
        assert "is_featured" not in count_sql

    def test_list_simulations_response_includes_is_featured_and_video_url(self, mock_app):
        """Each item in the response has is_featured and video_url fields."""
        client, mock_db, *_ = mock_app
        sim_id = uuid.uuid4()
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "id": sim_id,
                    "name": "Featured run",
                    "description": "desc",
                    "config": {},
                    "status": "completed",
                    "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    "completed_at": datetime(2026, 4, 1, 1, tzinfo=timezone.utc),
                    "simulated_duration": None,
                    "real_duration": None,
                    "total_conversations": 0,
                    "total_turns": 0,
                    "total_tokens": 0,
                    "total_cost": "0",
                    "total_artifacts": 0,
                    "total_management_flags": 0,
                    "agents_participated": ["vera"],
                    "error_log": None,
                    "model_versions": {},
                    "is_live": False,
                    "created_at": None,
                    "hypothesis": None,
                    "outcomes": {},
                    "learnings": [],
                    "factions": [],
                    "submitted_by_user_id": None,
                    "video_url": "https://example.com/video.mp4",
                    "video_render_status": "done",
                    "video_rendered_at": None,
                    "is_featured": True,
                    "submitter_display_name": None,
                }
            ]
        )
        mock_db.fetchval = AsyncMock(return_value=1)

        resp = client.get("/api/simulations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["is_featured"] is True
        assert item["video_url"] == "https://example.com/video.mp4"

    def test_list_simulations_completed_within_hours_filter(self, mock_app):
        """Wall of Simulations 'Recent' tab maps completed_within_hours into SQL."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations?completed_within_hours=1")
        assert resp.status_code == 200

        list_sql = mock_db.fetch.call_args[0][0]
        count_sql = mock_db.fetchval.call_args[0][0]
        assert "completed_at" in list_sql
        assert "completed_at" in count_sql
        # The bound interval value should be present in both calls
        assert 1 in mock_db.fetch.call_args[0][1:]
        assert 1 in mock_db.fetchval.call_args[0][1:]

    def test_list_simulations_completed_within_hours_omitted_does_not_filter(self, mock_app):
        """No completed_within_hours param means no completed_at predicate is added."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations")
        assert resp.status_code == 200
        list_sql = mock_db.fetch.call_args[0][0]
        count_sql = mock_db.fetchval.call_args[0][0]
        assert "completed_at" not in list_sql
        assert "completed_at" not in count_sql

    def test_list_simulations_joins_users_for_submitter_display_name(self, mock_app):
        """The list query LEFT JOINs users so the response carries display name."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchval = AsyncMock(return_value=0)

        resp = client.get("/api/simulations")
        assert resp.status_code == 200
        list_sql = mock_db.fetch.call_args[0][0]
        assert "LEFT JOIN users" in list_sql
        assert "submitter_display_name" in list_sql

    def test_list_simulations_response_includes_submitter_display_name(self, mock_app):
        """Submitter display name flows through to the response (None == anonymous)."""
        client, mock_db, *_ = mock_app
        sim_id = uuid.uuid4()
        base_row = {
            "id": sim_id,
            "name": "User-submitted run",
            "description": None,
            "config": {},
            "status": "running",
            "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
            "completed_at": None,
            "simulated_duration": None,
            "real_duration": None,
            "total_conversations": 0,
            "total_turns": 0,
            "total_tokens": 0,
            "total_cost": "0",
            "total_artifacts": 0,
            "total_management_flags": 0,
            "agents_participated": ["vera"],
            "error_log": None,
            "model_versions": {},
            "is_live": False,
            "created_at": None,
            "hypothesis": None,
            "outcomes": {},
            "learnings": [],
            "factions": [],
            "submitted_by_user_id": None,
            "video_url": None,
            "video_render_status": None,
            "video_rendered_at": None,
            "is_featured": False,
        }
        mock_db.fetch = AsyncMock(
            return_value=[
                {**base_row, "submitter_display_name": "brad"},
                {
                    **base_row,
                    "id": uuid.uuid4(),
                    "submitter_display_name": None,
                },
            ]
        )
        mock_db.fetchval = AsyncMock(return_value=2)

        resp = client.get("/api/simulations")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert items[0]["submitter_display_name"] == "brad"
        assert items[1]["submitter_display_name"] is None

    def test_simulation_detail_includes_video_render_status_and_failure(self, mock_app):
        """Detail response exposes enough video render state for the workspace."""
        client, mock_db, *_ = mock_app
        sim_id = uuid.uuid4()
        rendered_at = datetime(2026, 4, 1, 2, tzinfo=timezone.utc)
        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": sim_id,
                "name": "Render failed run",
                "description": "desc",
                "config": {},
                "status": "completed",
                "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 4, 1, 1, tzinfo=timezone.utc),
                "simulated_duration": None,
                "real_duration": None,
                "total_conversations": 0,
                "total_turns": 0,
                "total_tokens": 0,
                "total_cost": "0",
                "total_artifacts": 0,
                "total_management_flags": 0,
                "agents_participated": ["vera"],
                "error_log": None,
                "model_versions": {},
                "is_live": False,
                "created_at": None,
                "hypothesis": None,
                "outcomes": {},
                "learnings": [],
                "factions": [],
                "submitted_by_user_id": None,
                "video_url": None,
                "video_render_status": "failed",
                "video_rendered_at": rendered_at,
                "video_render_failure_reason": "Playwright timed out",
                "is_featured": False,
                "publish_to_youtube": False,
                "youtube_url": None,
                "youtube_publish_status": None,
                "youtube_published_at": None,
                "youtube_publish_attempts": 0,
                "youtube_failure_reason": None,
            }
        )
        mock_db.fetchval = AsyncMock(side_effect=[2, 12, "0.25", 1, 0])

        resp = client.get(f"/api/simulations/{sim_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["video_render_status"] == "failed"
        assert data["video_rendered_at"] == rendered_at.isoformat()
        assert data["video_render_failure_reason"] == "Playwright timed out"
        assert data["video_render_cancellation_reason"] is None

    def test_simulation_detail_includes_cost_limited_cancellation_reason(self, mock_app):
        """Cancelled cost-limited runs tell the UI why no render is coming."""
        client, mock_db, *_ = mock_app
        sim_id = uuid.uuid4()
        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": sim_id,
                "name": "Cost limited run",
                "description": None,
                "config": {},
                "status": "cancelled",
                "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 4, 1, 1, tzinfo=timezone.utc),
                "simulated_duration": None,
                "real_duration": None,
                "total_conversations": 0,
                "total_turns": 0,
                "total_tokens": 0,
                "total_cost": "0",
                "total_artifacts": 0,
                "total_management_flags": 0,
                "agents_participated": ["vera"],
                "error_log": {"reason": "cost_limit_exceeded", "total_cost": "1.23"},
                "model_versions": {},
                "is_live": False,
                "created_at": None,
                "hypothesis": None,
                "outcomes": {},
                "learnings": [],
                "factions": [],
                "submitted_by_user_id": None,
                "video_url": None,
                "video_render_status": None,
                "video_rendered_at": None,
                "video_render_failure_reason": None,
                "is_featured": False,
                "publish_to_youtube": False,
                "youtube_url": None,
                "youtube_publish_status": None,
                "youtube_published_at": None,
                "youtube_publish_attempts": 0,
                "youtube_failure_reason": None,
            }
        )
        mock_db.fetchval = AsyncMock(side_effect=[0, 0, "1.23", 0, 0])

        resp = client.get(f"/api/simulations/{sim_id}")

        assert resp.status_code == 200
        assert resp.json()["video_render_cancellation_reason"] == (
            "Cost limit reached after $1.23."
        )

    def test_energy_timeline_returns_grouped_series(self, mock_app):
        client, mock_db, *_ = mock_app
        sim_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        ts1 = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 5, 1, 10, 0, 5, tzinfo=timezone.utc)
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "agent_id": "vera",
                    "conversation_id": conv_id,
                    "turn_number": 0,
                    "energy": 50.0,
                    "timestamp": ts1,
                },
                {
                    "agent_id": "vera",
                    "conversation_id": conv_id,
                    "turn_number": 1,
                    "energy": 47.5,
                    "timestamp": ts2,
                },
                {
                    "agent_id": "rex",
                    "conversation_id": conv_id,
                    "turn_number": 0,
                    "energy": 50.0,
                    "timestamp": ts1,
                },
            ]
        )
        resp = client.get(f"/api/simulations/{sim_id}/energy-timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"vera", "rex"}
        assert len(data["vera"]) == 2
        assert data["vera"][0]["t"] == ts1.isoformat()
        assert data["vera"][0]["energy"] == 50.0
        assert data["vera"][0]["turn"] == 0

    def test_energy_timeline_filters_by_agent(self, mock_app):
        client, mock_db, *_ = mock_app
        sim_id = uuid.uuid4()
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get(f"/api/simulations/{sim_id}/energy-timeline?agent_id=vera")
        assert resp.status_code == 200
        # the per-agent path filters with $2
        sql = mock_db.fetch.call_args[0][0]
        assert "AND agent_id = $2" in sql


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
        mock_db.fetch = AsyncMock(
            return_value=[
                {"category": "creativity"},
                {"category": "safety"},
            ]
        )
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
        mock_db.fetch = AsyncMock(
            side_effect=[
                # First call: get_all_eval_runs
                [
                    {
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
                    }
                ],
                # Second call: batch-fetch simulation names
                [{"id": sim_id, "name": "Test Simulation"}],
                # Third call: get_eval_results for this run
                [],
            ]
        )
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

    def test_get_eval_runs_unscoped_omits_simulation_filter(self, mock_app):
        """`GET /api/evals/runs` (no sim_id) must not filter by simulation_id."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/evals/runs")
        assert resp.status_code == 200
        # The eval_runs list query must NOT mention simulation_id
        eval_run_queries = [c for c in mock_db.fetch.call_args_list if "FROM eval_runs" in c[0][0]]
        assert eval_run_queries, "Expected an eval_runs query"
        for call in eval_run_queries:
            assert "simulation_id" not in call[0][0]

    def test_get_eval_runs_scoped_filters_by_simulation_id(self, mock_app):
        """When simulation_id is provided, the eval_runs query filters by it."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        sim_id = uuid.uuid4()
        resp = client.get(f"/api/evals/runs?simulation_id={sim_id}")
        assert resp.status_code == 200
        eval_run_queries = [c for c in mock_db.fetch.call_args_list if "FROM eval_runs" in c[0][0]]
        assert eval_run_queries, "Expected an eval_runs query"
        scoped = [c for c in eval_run_queries if "simulation_id" in c[0][0]]
        assert scoped, "Expected eval_runs query to filter by simulation_id"
        # The bound parameter should equal the requested simulation UUID.
        assert sim_id in scoped[0][0]

    def test_get_eval_latest_unscoped_omits_simulation_filter(self, mock_app):
        """`GET /api/evals/latest` (no sim_id) must not filter by simulation_id."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/evals/latest")
        assert resp.status_code == 200
        for call in mock_db.fetch.call_args_list:
            if "FROM eval_runs" in call[0][0]:
                assert "simulation_id" not in call[0][0]

    def test_get_eval_latest_scoped_filters_by_simulation_id(self, mock_app):
        """When simulation_id is provided, /evals/latest scopes to it."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        sim_id = uuid.uuid4()
        resp = client.get(f"/api/evals/latest?simulation_id={sim_id}")
        assert resp.status_code == 200
        eval_run_queries = [c for c in mock_db.fetch.call_args_list if "FROM eval_runs" in c[0][0]]
        assert eval_run_queries
        scoped = [c for c in eval_run_queries if "simulation_id" in c[0][0]]
        assert scoped, "Expected /evals/latest query to filter by simulation_id"
        assert sim_id in scoped[0][0]

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
        mock_db.fetchrow = AsyncMock(
            side_effect=[
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
            ]
        )
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


def _shared_challenge_row(**overrides):
    base = {
        "id": 1,
        "description": "Try this scenario",
        "submitted_by": "viewer1",
        "source": "shared_simulation",
        "status": "pending",
        "assigned_agents": None,
        "result": None,
        "cost_estimate": None,
        "actual_cost": None,
        "votes": 1,
        "category": None,
        "tags": ["creative"],
        "simulation_id": uuid.UUID("00000000-0000-0000-0000-000000000099"),
        "shared_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "completed_at": None,
        "simulation_name": "Garden build",
        "simulation_video_url": "https://cdn/v.mp4",
        "simulation_total_turns": 25,
        "simulation_agents": ["vera", "rex"],
    }
    base.update(overrides)
    return base


class TestChallengeEndpoints:
    def test_get_challenges_filters_to_shared_only(self, mock_app):
        """The default feed only joins simulations where shared_as_challenge=TRUE."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/challenges")
        assert resp.status_code == 200
        sql = mock_db.fetch.call_args[0][0]
        assert "shared_as_challenge = TRUE" in sql
        assert "JOIN simulations" in sql

    def test_get_challenges_include_legacy_drops_filter(self, mock_app):
        """Pass include_legacy=true to surface legacy challenge rows too."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/challenges?include_legacy=true")
        assert resp.status_code == 200
        sql = mock_db.fetch.call_args[0][0]
        assert "shared_as_challenge" not in sql

    def test_get_challenges_returns_simulation_context(self, mock_app):
        """Each row carries the joined simulation fields for the card view."""
        client, mock_db, *_ = mock_app
        mock_db.fetch = AsyncMock(return_value=[_shared_challenge_row()])
        resp = client.get("/api/challenges")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["simulation_id"] == "00000000-0000-0000-0000-000000000099"
        assert item["simulation_name"] == "Garden build"
        assert item["simulation_video_url"] == "https://cdn/v.mp4"
        assert item["simulation_total_turns"] == 25
        assert item["tags"] == ["creative"]

    def test_get_challenge_detail(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=_shared_challenge_row())
        resp = client.get("/api/challenges/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["simulation_id"] == "00000000-0000-0000-0000-000000000099"

    def test_get_challenge_detail_not_found(self, mock_app):
        client, mock_db, *_ = mock_app
        mock_db.fetchrow = AsyncMock(return_value=None)
        resp = client.get("/api/challenges/999")
        assert resp.status_code == 404

    def test_legacy_post_challenge_route_is_gone(self, mock_app):
        """The raw-text POST /api/challenges flow is no longer accepted."""
        client, *_ = mock_app
        resp = client.post(
            "/api/challenges",
            json={"description": "x", "category": "building"},
        )
        # FastAPI returns 405 when the path exists for other verbs only
        assert resp.status_code in (404, 405)

    def test_upvote_challenge(self, mock_app):
        client, mock_db, _, mock_redis, _ = mock_app
        mock_redis.get = AsyncMock(return_value=None)
        mock_db.fetchrow = AsyncMock(
            side_effect=[
                {
                    "id": 1,
                    "description": "Try this scenario",
                    "submitted_by": "viewer1",
                    "source": "shared_simulation",
                    "status": "pending",
                    "assigned_agents": None,
                    "result": None,
                    "cost_estimate": None,
                    "actual_cost": None,
                    "votes": 2,
                    "category": None,
                    "tags": ["creative"],
                    "simulation_id": uuid.UUID("00000000-0000-0000-0000-000000000099"),
                    "shared_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
                    "completed_at": None,
                },
                _shared_challenge_row(votes=2),
            ]
        )
        resp = client.post("/api/challenges/1/upvote")
        assert resp.status_code == 200
        assert resp.json()["votes"] == 2

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

    def test_get_lore_no_simulation_filter_by_default(self, mock_app):
        """Without simulation_id, the query should not filter by simulation
        — letting events from any simulation surface, since live has none."""
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        resp = client.get("/api/lore")
        assert resp.status_code == 200
        # Inspect the SQL that was issued — should not reference simulation_id
        called_sql = mock_db.fetchval.await_args.args[0]
        assert "simulation_id" not in called_sql

    def test_get_lore_with_simulation_id(self, mock_app):
        """When simulation_id is supplied, the filter should be applied."""
        client, mock_db, *_ = mock_app
        mock_db.fetchval = AsyncMock(return_value=0)
        mock_db.fetch = AsyncMock(return_value=[])
        sim_id = "00000000-0000-0000-0000-000000000042"
        resp = client.get(f"/api/lore?simulation_id={sim_id}")
        assert resp.status_code == 200
        called_sql = mock_db.fetchval.await_args.args[0]
        assert "simulation_id" in called_sql
        # The bound param should be the parsed UUID
        params = mock_db.fetchval.await_args.args[1:]
        assert uuid.UUID(sim_id) in params


# ── Snapshots ─────────────────────────────────────────────────


class TestSnapshotEndpoints:
    def test_snapshot_at_falls_back_to_file_mtime(self, mock_app, tmp_path, monkeypatch):
        """When a snapshot JSON lacks `snapshot_at`, the API returns the file's
        mtime as an ISO 8601 string so the UI can render a date instead of '—'."""
        import json
        import os
        from datetime import UTC, datetime

        client, *_ = mock_app
        monkeypatch.chdir(tmp_path)
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        snap_path = snapshots_dir / "snapshot-legacy.json"
        # Older snapshots may not have snapshot_at persisted.
        snap_path.write_text(json.dumps({"agents": {"vera": {}}}))
        # Pin a known mtime to make the assertion deterministic.
        target_dt = datetime(2026, 4, 15, 12, 30, 0, tzinfo=UTC)
        ts = target_dt.timestamp()
        os.utime(snap_path, (ts, ts))

        sim_id = "00000000-0000-0000-0000-000000000123"
        resp = client.get(f"/api/simulations/{sim_id}/snapshots")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        snapshot_at = items[0]["snapshot_at"]
        assert snapshot_at, "snapshot_at must not be empty when file exists"
        parsed = datetime.fromisoformat(snapshot_at)
        assert parsed == target_dt

    def test_snapshot_at_uses_persisted_value_when_present(self, mock_app, tmp_path, monkeypatch):
        """When `snapshot_at` is persisted in the file, it is preferred over mtime."""
        import json

        client, *_ = mock_app
        monkeypatch.chdir(tmp_path)
        snapshots_dir = tmp_path / "snapshots"
        snapshots_dir.mkdir()
        persisted = "2026-03-01T08:00:00+00:00"
        (snapshots_dir / "snapshot-new.json").write_text(
            json.dumps({"snapshot_at": persisted, "agents": {}})
        )

        sim_id = "00000000-0000-0000-0000-000000000456"
        resp = client.get(f"/api/simulations/{sim_id}/snapshots")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["snapshot_at"] == persisted


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
            "http://localhost:4000",
            "*",
        )

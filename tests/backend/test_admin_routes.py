"""Tests for admin API endpoints (core/admin/ sub-routers)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.models import (
    AgentConfig,
    AgentStatus,
    Conversation,
    CoreMemory,
    CoreMemoryHistory,
    CostEvent,
    JournalEntry,
    RecallMemory,
    SelectionLog,
    Simulation,
)

# Env vars needed by core.main import are set inside the mock_app fixture
# via patch.dict to avoid polluting other test modules.


# ── Fixtures ───────────────────────────────────────────────────


def _make_agent_config(**overrides) -> AgentConfig:
    defaults = {
        "id": "vera",
        "display_name": "Vera",
        "model_conversation": "claude-haiku-4-5",
        "model_building": "claude-sonnet-4-6",
        "voice_id": "en-US-AriaNeural",
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


def _make_conversation(**overrides) -> Conversation:
    defaults = {
        "id": uuid.uuid4(),
        "started_at": datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc),
        "ended_at": None,
        "trigger_type": "idle",
        "trigger_details": None,
        "initial_energy": 0.8,
        "final_energy": None,
        "turn_count": 5,
        "participating_agents": ["vera", "rex"],
        "topics_discussed": ["architecture"],
        "closed_by": None,
        "location": "main_hall",
    }
    defaults.update(overrides)
    return Conversation(**defaults)


def _make_simulation(**overrides) -> Simulation:
    defaults = {
        "id": uuid.uuid4(),
        "name": "test-sim",
        "config": {"seed": 42},
        "status": "completed",
        "started_at": datetime(2026, 4, 1, tzinfo=timezone.utc),
        "total_conversations": 10,
        "total_turns": 50,
        "total_tokens": 5000,
        "total_cost": Decimal("1.50"),
        "total_artifacts": 3,
        "total_management_flags": 0,
        "agents_participated": ["vera", "rex"],
    }
    defaults.update(overrides)
    return Simulation(**defaults)


@pytest.fixture
def mock_app():
    """Create a TestClient with fully mocked dependencies."""
    vera = _make_agent_config()
    rex = _make_agent_config(
        id="rex",
        display_name="Rex",
        chattiness=0.5,
        initiative=0.6,
        interrupt_tendency=0.4,
    )

    mock_registry = MagicMock()
    mock_registry.get_all_agents.return_value = [vera, rex]
    mock_registry.get_agent.side_effect = lambda aid: {"vera": vera, "rex": rex}.get(aid)
    mock_registry.load_all = AsyncMock()

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.disconnect = AsyncMock()
    mock_db.fetchval = AsyncMock(return_value=1)
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.fetchrow = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.disconnect = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)

    mock_llm = MagicMock()

    env_overrides = {
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "")
        or "test-openrouter-key-for-unit-tests",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "")
        or "postgresql://agi:devpassword@localhost:5434/livestream_agi",
        "ADMIN_PASSWORD": "test-admin-password",
    }

    # Build a Services-like stub the FastAPI lifespan can use without ever
    # touching a real DB / Redis / LLM. The endpoints don't read from
    # `app.state.services` directly — they go through dependency-injection
    # overrides set below — but the lifespan still needs *something* with the
    # right shape to avoid attribute errors on shutdown.
    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis
    mock_services.agent_registry = mock_registry
    mock_services.llm_client = mock_llm
    mock_services.core_memory = None
    mock_services.config_loader = MagicMock(
        start_watching=AsyncMock(),
        stop_watching=AsyncMock(),
    )
    mock_services.cost_repo = MagicMock()
    mock_services.memory_repo = MagicMock()
    mock_services.token_counter = MagicMock()
    mock_services.goal_manager = MagicMock()
    mock_services.agent_state_manager = MagicMock()
    mock_services.dream_manager = MagicMock()
    mock_services.event_bus = MagicMock()

    with (
        patch.dict(os.environ, env_overrides),
        patch("core.main.bootstrap_services", AsyncMock(return_value=mock_services)),
        patch("core.main.shutdown_services", AsyncMock()),
        patch("core.main.init_core_memories", AsyncMock(return_value=[])),
        patch("core.main.start_scheduler"),
        patch("core.main.stop_scheduler"),
    ):
        from core.admin.dependencies import get_db, get_llm, get_registry, require_admin
        from core.main import app

        # Override FastAPI dependency injection for the new sub-router architecture
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_registry] = lambda: mock_registry
        app.dependency_overrides[get_llm] = lambda: mock_llm
        app.dependency_overrides[require_admin] = lambda: None

        try:
            with TestClient(app) as raw_client:
                raw_client.headers["Authorization"] = "Bearer test-admin-password"
                yield raw_client, mock_db, mock_registry
        finally:
            app.dependency_overrides.clear()


# ── Agent Endpoint Tests ───────────────────────────────────────


class TestAgentEndpoints:
    def test_list_agents(self, mock_app):
        client, mock_db, _ = mock_app
        mock_db.fetch = AsyncMock(return_value=[])

        with patch(
            "core.repos.cost_repo.CostRepo.get_costs_by_agent",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/admin/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "vera"
        assert data[1]["id"] == "rex"

    def test_get_agent_detail(self, mock_app):
        client, _, _ = mock_app
        resp = client.get("/api/admin/agents/vera")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "vera"
        assert data["display_name"] == "Vera"
        assert data["conversation_model"] == "claude-haiku-4-5"
        assert data["personality_traits"]["chattiness"] == 0.7
        assert data["behaviors"] == {"tone": "professional"}
        assert data["voice"] is not None

    def test_get_agent_not_found(self, mock_app):
        client, _, _ = mock_app
        resp = client.get("/api/admin/agents/nonexistent")
        assert resp.status_code == 404

    def test_get_agent_system_prompt(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.memory_repo.MemoryRepo.get_core_memory",
            new_callable=AsyncMock,
            return_value=CoreMemory(
                agent_id="vera", content="I am Vera's core memory.", token_count=10
            ),
        ):
            resp = client.get("/api/admin/agents/vera/system-prompt")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["layers"], list)
        layer_names = [l["name"] for l in data["layers"]]
        assert "Infrastructure" in layer_names
        assert "Character" in layer_names
        assert "Memory Context" in layer_names
        char_layer = next(l for l in data["layers"] if l["name"] == "Character")
        assert char_layer["content"] == "You are Vera, the showrunner."
        assert char_layer["token_count"] > 0
        assert data["total_tokens"] > 0
        # Assembled prompt should contain all non-empty layers
        assert "You are Vera" in data["assembled_prompt"]

    def test_get_agent_core_memory(self, mock_app):
        client, mock_db, _ = mock_app

        core_mem = CoreMemory(agent_id="vera", content="core content", token_count=5, version=2)
        history = [
            CoreMemoryHistory(id=1, agent_id="vera", content="v1", version=1),
            CoreMemoryHistory(id=2, agent_id="vera", content="core content", version=2),
        ]

        with (
            patch(
                "core.repos.memory_repo.MemoryRepo.get_core_memory",
                new_callable=AsyncMock,
                return_value=core_mem,
            ),
            patch(
                "core.repos.memory_repo.MemoryRepo.get_core_memory_history",
                new_callable=AsyncMock,
                return_value=history,
            ),
        ):
            resp = client.get("/api/admin/agents/vera/core-memory")

        assert resp.status_code == 200
        data = resp.json()
        assert data["current_content"] == "core content"
        assert data["current_version"] == 2
        assert data["token_count"] == 5
        assert len(data["version_history"]) == 2

    def test_get_agent_recall_memories_paginated(self, mock_app):
        client, mock_db, _ = mock_app

        memories = [
            RecallMemory(
                id=1,
                agent_id="vera",
                summary="test memory",
                embedding=[0.1, 0.2],
                importance_score=0.8,
            ),
        ]

        with patch(
            "core.repos.memory_repo.MemoryRepo.get_recall_memories_paginated",
            new_callable=AsyncMock,
            return_value=(memories, 1),
        ):
            resp = client.get("/api/admin/agents/vera/recall-memories?limit=10&offset=0")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        # Embeddings should be stripped
        assert "embedding" not in data["items"][0]
        assert data["items"][0]["summary"] == "test memory"

    def test_get_agent_recall_memories_with_search(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.memory_repo.MemoryRepo.search_recall_memories_by_keyword",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_search:
            resp = client.get("/api/admin/agents/vera/recall-memories?search=budget")

        assert resp.status_code == 200
        mock_search.assert_called_once_with(
            "vera",
            "budget",
            limit=50,
            offset=0,
            simulation_id=None,
        )

    def test_get_agent_conversations(self, mock_app):
        client, mock_db, _ = mock_app
        conv = _make_conversation()

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get_conversations_by_agent",
            new_callable=AsyncMock,
            return_value=([conv], 1),
        ):
            resp = client.get("/api/admin/agents/vera/conversations?limit=5")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["limit"] == 5

    def test_get_agent_costs(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.cost_repo.CostRepo.get_costs_by_agent_grouped",
            new_callable=AsyncMock,
            return_value={
                "by_day": [{"day": "2026-04-01", "total": "0.50"}],
                "by_type": [{"type": "conversation", "total": "0.50"}],
                "total": "0.50",
            },
        ):
            resp = client.get("/api/admin/agents/vera/costs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == "0.50"
        assert len(data["by_day"]) == 1

    def test_get_agent_journal(self, mock_app):
        client, mock_db, _ = mock_app

        entries = [
            JournalEntry(
                id=1,
                agent_id="vera",
                reflection_type="daily",
                content="Today was productive.",
                token_count=10,
                image_url="https://example.com/journals/vera.png",
            ),
        ]

        with patch(
            "core.repos.memory_repo.MemoryRepo.get_journal_entries",
            new_callable=AsyncMock,
            return_value=(entries, 1),
        ):
            resp = client.get("/api/admin/agents/vera/journal?limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["content"] == "Today was productive."
        assert data["items"][0]["image_url"] == "https://example.com/journals/vera.png"


# ── Simulation Endpoint Tests ──────────────────────────────────


class TestSimulationEndpoints:
    def test_list_simulations(self, mock_app):
        client, mock_db, _ = mock_app
        sim = _make_simulation()

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.list",
                new_callable=AsyncMock,
                return_value=[sim],
            ),
            patch(
                "core.repos.simulation_repo.SimulationRepo.count",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            resp = client.get("/api/admin/simulations?limit=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "test-sim"

    def test_list_simulations_with_status_filter(self, mock_app):
        client, mock_db, _ = mock_app

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.list",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_list,
            patch(
                "core.repos.simulation_repo.SimulationRepo.count",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            resp = client.get("/api/admin/simulations?status=completed")

        assert resp.status_code == 200
        mock_list.assert_called_once_with(status="completed", limit=20, offset=0)

    def test_get_simulation(self, mock_app):
        client, mock_db, _ = mock_app
        sim = _make_simulation()

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.get(f"/api/admin/simulations/{sim.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-sim"
        assert data["total_conversations"] == 10

    def test_get_simulation_returns_research_fields(self, mock_app):
        client, _, _ = mock_app
        sim = _make_simulation(
            hypothesis="builders will dominate",
            outcomes={"key_metrics": {"total_turns": 12}, "surprises": []},
            learnings=[
                {
                    "author": "system",
                    "text": "factions formed by phase 2",
                    "created_at": "2026-05-08T00:00:00Z",
                }
            ],
        )
        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.get(f"/api/admin/simulations/{sim.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["hypothesis"] == "builders will dominate"
        assert data["outcomes"]["key_metrics"]["total_turns"] == 12
        assert data["learnings"][0]["text"] == "factions formed by phase 2"

    def test_patch_simulation_updates_research_fields(self, mock_app):
        client, _, _ = mock_app
        sim = _make_simulation(
            hypothesis="initial",
            outcomes={"key_metrics": {"x": 1}},
            learnings=[],
        )
        updated = sim.model_copy(
            update={
                "outcomes": {"key_metrics": {"x": 99}, "surprises": ["unexpected"]},
                "learnings": [
                    {
                        "author": "user",
                        "text": "ran out of cost",
                        "created_at": "2026-05-08T00:00:00Z",
                    }
                ],
            }
        )
        with patch(
            "core.repos.simulation_repo.SimulationRepo.update_research_fields",
            new_callable=AsyncMock,
            return_value=updated,
        ) as mock_update:
            resp = client.patch(
                f"/api/admin/simulations/{sim.id}",
                json={
                    "outcomes": {"key_metrics": {"x": 99}, "surprises": ["unexpected"]},
                    "learnings": [
                        {
                            "author": "user",
                            "text": "ran out of cost",
                            "created_at": "2026-05-08T00:00:00Z",
                        }
                    ],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcomes"]["key_metrics"]["x"] == 99
        assert data["learnings"][0]["author"] == "user"
        mock_update.assert_awaited_once()
        kwargs = mock_update.call_args.kwargs
        assert kwargs["hypothesis"] is None
        assert kwargs["outcomes"]["surprises"] == ["unexpected"]

    def test_patch_simulation_not_found(self, mock_app):
        client, _, _ = mock_app
        with patch(
            "core.repos.simulation_repo.SimulationRepo.update_research_fields",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.patch(
                f"/api/admin/simulations/{uuid.uuid4()}",
                json={"hypothesis": "anything"},
            )
        assert resp.status_code == 404

    def test_get_simulation_not_found(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/admin/simulations/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_get_simulation_timeline(self, mock_app):
        client, mock_db, _ = mock_app
        sim_id = uuid.uuid4()
        events = [
            {
                "timestamp": "2026-04-01T12:00:00",
                "event_type": "conversation_started",
                "agent_id": None,
                "details": {"conversation_id": str(uuid.uuid4())},
            },
        ]

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get_timeline_events",
            new_callable=AsyncMock,
            return_value=events,
        ):
            resp = client.get(f"/api/admin/simulations/{sim_id}/timeline")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "conversation_started"

    def test_get_simulation_conversations(self, mock_app):
        client, mock_db, _ = mock_app
        conv = _make_conversation()

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get_conversations_by_simulation",
            new_callable=AsyncMock,
            return_value=([conv], 1),
        ):
            resp = client.get(f"/api/admin/simulations/{uuid.uuid4()}/conversations")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_get_simulation_artifacts(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.artifact_repo.ArtifactRepo.get_artifacts_by_simulation",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(f"/api/admin/simulations/{uuid.uuid4()}/artifacts")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_simulation_management_log(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get_management_log",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(
                f"/api/admin/simulations/{uuid.uuid4()}/management-log?severity_min=3"
            )

        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_simulation_costs(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.cost_repo.CostRepo.get_costs_by_simulation",
            new_callable=AsyncMock,
            return_value={
                "by_agent": [],
                "by_type": [{"type": "imagen_generation", "cost": "0.02", "tokens": 0}],
                "total": "0.02",
            },
        ):
            resp = client.get(f"/api/admin/simulations/{uuid.uuid4()}/costs")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == "0.02"
        assert data["by_type"][0] == {
            "type": "imagen_generation",
            "cost": "0.02",
            "tokens": 0,
        }


# ── Scenario / Simulation Launcher Tests ───────────────────────


def _patch_project_root(monkeypatch, tmp_path):
    """Point simulation_routes._project_root() at tmp_path with the right layout.

    Returns the scenarios/ directory so callers can drop fixture YAMLs in.
    """
    from core.admin import simulation_routes as sr

    scenarios = tmp_path / "scenarios"
    scenarios.mkdir(exist_ok=True)
    scripts = tmp_path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "run_simulation.py").write_text("# stub")
    (scripts / "watch_conversations.py").write_text("# stub")
    monkeypatch.setattr(sr, "_project_root", lambda: tmp_path)
    return scenarios


class TestScenarioListing:
    def test_list_scenarios_returns_yaml_files(self, mock_app, tmp_path, monkeypatch):
        client, _, _ = mock_app
        scenarios = _patch_project_root(monkeypatch, tmp_path)
        (scenarios / "alpha.yaml").write_text(
            "# Alpha scenario\n# More description\n\nphases: []\n"
        )
        (scenarios / "beta.yaml").write_text("phases: []\n")
        # Subdirs and non-yaml files must be ignored
        (scenarios / "seeds").mkdir()
        (scenarios / "notes.txt").write_text("ignore me")

        resp = client.get("/api/admin/scenarios")
        assert resp.status_code == 200
        items = resp.json()
        names = [s["filename"] for s in items]
        assert "alpha.yaml" in names
        assert "beta.yaml" in names
        assert "seeds" not in names
        assert "notes.txt" not in names

        alpha = next(s for s in items if s["filename"] == "alpha.yaml")
        assert alpha["name"] == "alpha"
        assert alpha["description"] is not None
        assert "Alpha scenario" in alpha["description"]
        beta = next(s for s in items if s["filename"] == "beta.yaml")
        assert beta["description"] is None


class TestCreateSimulationWithSeedFile:
    def test_seed_file_outside_scenarios_rejected(self, mock_app, tmp_path, monkeypatch):
        client, _, _ = mock_app
        _patch_project_root(monkeypatch, tmp_path)

        resp = client.post(
            "/api/admin/simulations",
            json={"seed_file": "../etc/passwd"},
        )
        assert resp.status_code == 400
        assert "scenarios" in resp.json().get("detail", "").lower()

    def test_seed_file_absolute_path_rejected(self, mock_app, tmp_path, monkeypatch):
        client, _, _ = mock_app
        _patch_project_root(monkeypatch, tmp_path)

        resp = client.post(
            "/api/admin/simulations",
            json={"seed_file": "/etc/passwd"},
        )
        assert resp.status_code == 400

    def test_seed_file_missing_returns_400(self, mock_app, tmp_path, monkeypatch):
        client, _, _ = mock_app
        _patch_project_root(monkeypatch, tmp_path)

        resp = client.post(
            "/api/admin/simulations",
            json={"seed_file": "doesnotexist.yaml"},
        )
        assert resp.status_code == 400

    def test_seed_file_launches_run_simulation_subprocess(self, mock_app, tmp_path, monkeypatch):
        client, _, _ = mock_app
        scenarios = _patch_project_root(monkeypatch, tmp_path)
        (scenarios / "smoke.yaml").write_text("phases: []\n")

        sim = _make_simulation(name="dashboard-smoke-x", status="created")

        captured: dict = {}

        def fake_popen(cmd, *args, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs

            class _P:
                pid = 1234

            return _P()

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.create",
                new_callable=AsyncMock,
                return_value=sim,
            ),
            patch("subprocess.Popen", side_effect=fake_popen),
        ):
            resp = client.post(
                "/api/admin/simulations",
                json={"seed_file": "smoke.yaml", "max_cost": 1.5},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["simulation_id"] == str(sim.id)
        cmd = captured["cmd"]
        assert any("run_simulation.py" in str(c) for c in cmd)
        assert "--seed-file" in cmd
        assert "--sim-id" in cmd
        assert str(sim.id) in cmd
        assert "--max-cost" in cmd
        assert "1.5" in cmd

    def test_seed_file_passes_hypothesis_to_simulation_create(
        self, mock_app, tmp_path, monkeypatch
    ):
        """POST /admin/simulations forwards `hypothesis` into SimulationCreate."""
        client, _, _ = mock_app
        scenarios = _patch_project_root(monkeypatch, tmp_path)
        (scenarios / "smoke.yaml").write_text("phases: []\n")

        sim = _make_simulation(name="dashboard-smoke-y", status="created")

        captured: dict = {}

        def fake_popen(cmd, *args, **kwargs):
            class _P:
                pid = 7

            return _P()

        async def fake_create(self, sc):
            captured["sc"] = sc
            return sim

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.create",
                new=fake_create,
            ),
            patch("subprocess.Popen", side_effect=fake_popen),
        ):
            resp = client.post(
                "/api/admin/simulations",
                json={
                    "seed_file": "smoke.yaml",
                    "hypothesis": "alliances will form by hour 12",
                },
            )

        assert resp.status_code == 200
        assert captured["sc"].hypothesis == "alliances will form by hour 12"

    def test_max_cost_above_ten_rejected(self, mock_app, tmp_path, monkeypatch):
        client, _, _ = mock_app
        scenarios = _patch_project_root(monkeypatch, tmp_path)
        (scenarios / "smoke.yaml").write_text("phases: []\n")

        resp = client.post(
            "/api/admin/simulations",
            json={"seed_file": "smoke.yaml", "max_cost": 50},
        )
        assert resp.status_code == 422


# ── Conversation Endpoint Tests ────────────────────────────────


class TestConversationEndpoints:
    def test_get_conversation_detail(self, mock_app):
        client, mock_db, _ = mock_app
        conv = _make_conversation()

        with (
            patch(
                "core.repos.conversation_repo.ConversationRepo.get",
                new_callable=AsyncMock,
                return_value=conv,
            ),
            patch(
                "core.repos.conversation_repo.ConversationRepo.get_energy_log",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "core.repos.transcript_repo.TranscriptRepo.get_by_conversation",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.get(f"/api/admin/conversations/{conv.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["trigger_type"] == "idle"
        assert data["participating_agents"] == ["vera", "rex"]
        assert data["energy_history"] == []
        assert data["total_tokens"] == 0
        assert data["total_cost"] == "0"

    def test_get_conversation_not_found(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/admin/conversations/{uuid.uuid4()}")

        assert resp.status_code == 404

    def test_get_conversation_turns(self, mock_app):
        client, mock_db, _ = mock_app
        conv_id = uuid.uuid4()
        logs = [
            SelectionLog(
                id=1,
                conversation_id=conv_id,
                turn_number=1,
                selected_agent_id="vera",
                was_interrupt=False,
                agent_scores={"vera": 0.8, "rex": 0.6},
                detected_topic="architecture",
                conversation_energy=0.75,
            ),
        ]

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get_selection_log",
            new_callable=AsyncMock,
            return_value=logs,
        ):
            resp = client.get(f"/api/admin/conversations/{conv_id}/turns")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["selected_agent_id"] == "vera"
        assert data[0]["agent_scores"]["vera"] == 0.8

    def test_get_conversation_selection_log(self, mock_app):
        client, mock_db, _ = mock_app
        conv_id = uuid.uuid4()

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get_selection_log",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(f"/api/admin/conversations/{conv_id}/selection-log")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_conversation_management_flags(self, mock_app):
        client, mock_db, _ = mock_app
        conv_id = uuid.uuid4()
        flags = [
            {
                "id": str(uuid.uuid4()),
                "agent_id": "grok",
                "original_content": "test content",
                "filter_layer": 1,
                "severity": 3,
                "action_would_take": "block",
                "reason": "Potentially harmful",
                "flagged_keywords": ["test"],
                "created_at": "2026-04-01T12:00:00+00:00",
            },
        ]

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get_management_flags",
            new_callable=AsyncMock,
            return_value=flags,
        ):
            resp = client.get(f"/api/admin/conversations/{conv_id}/management-flags")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_id"] == "grok"
        assert data[0]["severity"] == 3

    def test_get_conversation_interrupts(self, mock_app):
        client, mock_db, _ = mock_app
        conv_id = uuid.uuid4()
        interrupts = [
            {
                "id": 1,
                "attempting_agent_id": "fork",
                "would_have_spoken_id": "vera",
                "interrupt_score": 0.85,
                "threshold_at_time": 0.7,
                "succeeded": True,
                "reason": "High urgency topic",
                "timestamp": "2026-04-01T12:01:00+00:00",
            },
        ]

        with patch(
            "core.repos.conversation_repo.ConversationRepo.get_interrupts",
            new_callable=AsyncMock,
            return_value=interrupts,
        ):
            resp = client.get(f"/api/admin/conversations/{conv_id}/interrupts")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["attempting_agent_id"] == "fork"
        assert data[0]["succeeded"] is True
        assert data[0]["interrupt_score"] == 0.85


# ── Global Artifact Endpoint Tests ─────────────────────────────


class TestGlobalArtifactEndpoints:
    def test_list_artifacts_no_filters(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.artifact_repo.ArtifactRepo.get_all_artifacts",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_get:
            resp = client.get("/api/admin/artifacts")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        mock_get.assert_called_once_with(
            simulation_id=None,
            agent_ids=None,
            artifact_type=None,
            status=None,
            since=None,
            until=None,
            search=None,
            sort="newest",
            limit=50,
            offset=0,
        )

    def test_list_artifacts_with_filters(self, mock_app):
        client, mock_db, _ = mock_app
        from core.models import Artifact

        artifact = Artifact(
            id=uuid.uuid4(),
            simulation_id=uuid.uuid4(),
            agent_id="rex",
            tool_name="post_to_social",
            tool_input={"content": "Hello world"},
            tool_output={"posted": True},
            artifact_type="social_post",
            status="executed",
            metadata={},
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

        with patch(
            "core.repos.artifact_repo.ArtifactRepo.get_all_artifacts",
            new_callable=AsyncMock,
            return_value=([artifact], 1),
        ) as mock_get:
            resp = client.get(
                "/api/admin/artifacts"
                "?agent_id=rex,fork"
                "&type=social_post,email"
                "&status=executed"
                "&sort=oldest"
                "&limit=10&offset=5"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["agent_id"] == "rex"
        assert data["items"][0]["artifact_type"] == "social_post"

        mock_get.assert_called_once_with(
            simulation_id=None,
            agent_ids=["rex", "fork"],
            artifact_type=["social_post", "email"],
            status=["executed"],
            since=None,
            until=None,
            search=None,
            sort="oldest",
            limit=10,
            offset=5,
        )

    def test_list_artifacts_with_search(self, mock_app):
        client, mock_db, _ = mock_app

        with patch(
            "core.repos.artifact_repo.ArtifactRepo.get_all_artifacts",
            new_callable=AsyncMock,
            return_value=([], 0),
        ) as mock_get:
            resp = client.get("/api/admin/artifacts?search=hello")

        assert resp.status_code == 200
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["search"] == "hello"


# ── Eval Endpoint Tests ────────────────────────────────────────


class TestEvalEndpoints:
    def test_get_simulation_evals(self, mock_app):
        client, _, _ = mock_app
        with patch(
            "core.repos.eval_repo.EvalRepo.get_eval_runs",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get(f"/api/admin/simulations/{uuid.uuid4()}/evals")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_run_simulation_evals(self, mock_app):
        client, _, _ = mock_app
        run_id = uuid.uuid4()
        sim_id = uuid.uuid4()
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)

        from core.models import EvalRun

        mock_run = EvalRun(
            id=run_id,
            simulation_id=sim_id,
            eval_suite="quick",
            status="running",
            started_at=now,
        )
        with (
            patch(
                "core.eval.engine.EvalEngine.run",
                new_callable=AsyncMock,
                return_value=run_id,
            ),
            patch(
                "core.repos.eval_repo.EvalRepo.create_eval_run",
                new_callable=AsyncMock,
                return_value=mock_run,
            ),
        ):
            resp = client.post(
                f"/api/admin/simulations/{sim_id}/evals/run",
                json={"eval_suite": "quick"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["eval_run_id"] == str(run_id)
        assert data["status"] == "running"

    def test_get_eval_not_found(self, mock_app):
        client, _, _ = mock_app
        with patch(
            "core.repos.eval_repo.EvalRepo.get_eval_run",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/admin/evals/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_list_all_eval_runs(self, mock_app):
        client, _, _ = mock_app
        from core.models import EvalRun

        run = EvalRun(
            id=uuid.uuid4(),
            simulation_id=uuid.uuid4(),
            eval_suite="full",
            status="completed",
            started_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 4, 1, 0, 5, tzinfo=timezone.utc),
            overall_score=Decimal("82.00"),
            cost=Decimal("0.05"),
        )
        with patch(
            "core.repos.eval_repo.EvalRepo.get_all_eval_runs",
            new_callable=AsyncMock,
            return_value=[run],
        ):
            resp = client.get("/api/admin/evals?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["eval_suite"] == "full"
        assert data[0]["status"] == "completed"

    def test_compare_evals(self, mock_app):
        client, _, _ = mock_app
        from core.models import EvalResult, EvalRun

        run_a_id = uuid.uuid4()
        run_b_id = uuid.uuid4()
        sim_id = uuid.uuid4()
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)

        run_a = EvalRun(
            id=run_a_id,
            simulation_id=sim_id,
            eval_suite="full",
            status="completed",
            started_at=now,
            overall_score=Decimal("80"),
        )
        run_b = EvalRun(
            id=run_b_id,
            simulation_id=sim_id,
            eval_suite="full",
            status="completed",
            started_at=now,
            overall_score=Decimal("85"),
        )
        result_a = EvalResult(
            id=uuid.uuid4(),
            eval_run_id=run_a_id,
            category="safety",
            score=Decimal("80"),
            reasoning="Good",
            tokens_used=100,
            cost=Decimal("0.01"),
        )
        result_b = EvalResult(
            id=uuid.uuid4(),
            eval_run_id=run_b_id,
            category="safety",
            score=Decimal("85"),
            reasoning="Better",
            tokens_used=120,
            cost=Decimal("0.012"),
        )

        with (
            patch(
                "core.repos.eval_repo.EvalRepo.get_eval_run",
                new_callable=AsyncMock,
                side_effect=lambda rid: run_a if rid == run_a_id else run_b,
            ),
            patch(
                "core.repos.eval_repo.EvalRepo.get_eval_results",
                new_callable=AsyncMock,
                side_effect=lambda rid: [result_a] if rid == run_a_id else [result_b],
            ),
        ):
            resp = client.get(f"/api/admin/evals/compare?run_a={run_a_id}&run_b={run_b_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "run_a" in data and "run_b" in data
        assert len(data["run_a"]["results"]) == 1
        assert len(data["run_b"]["results"]) == 1
        assert data["run_a"]["results"][0]["category"] == "safety"

    def test_compare_evals_invalid_uuid(self, mock_app):
        client, _, _ = mock_app
        resp = client.get("/api/admin/evals/compare?run_a=not-a-uuid&run_b=also-bad")
        assert resp.status_code == 400

    def test_compare_evals_not_found(self, mock_app):
        client, _, _ = mock_app
        with patch(
            "core.repos.eval_repo.EvalRepo.get_eval_run",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/admin/evals/compare?run_a={uuid.uuid4()}&run_b={uuid.uuid4()}")
        assert resp.status_code == 404

    def test_eval_history(self, mock_app):
        client, _, _ = mock_app
        history_data = [
            {
                "score": 75.0,
                "created_at": "2026-04-01T00:00:00",
                "simulation_id": str(uuid.uuid4()),
                "eval_run_id": str(uuid.uuid4()),
            },
            {
                "score": 82.0,
                "created_at": "2026-04-02T00:00:00",
                "simulation_id": str(uuid.uuid4()),
                "eval_run_id": str(uuid.uuid4()),
            },
        ]
        with patch(
            "core.repos.eval_repo.EvalRepo.get_eval_history",
            new_callable=AsyncMock,
            return_value=history_data,
        ):
            resp = client.get("/api/admin/evals/history?category=entertainment")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["score"] == 75.0
        assert data[1]["score"] == 82.0

    def test_export_eval(self, mock_app):
        client, _, _ = mock_app
        from core.models import EvalResult, EvalRun

        run_id = uuid.uuid4()
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)
        run = EvalRun(
            id=run_id,
            simulation_id=uuid.uuid4(),
            eval_suite="full",
            status="completed",
            started_at=now,
            overall_score=Decimal("80"),
        )
        result = EvalResult(
            id=uuid.uuid4(),
            eval_run_id=run_id,
            category="safety",
            score=Decimal("80"),
            reasoning="Good",
            tokens_used=100,
            cost=Decimal("0.01"),
        )

        with (
            patch(
                "core.repos.eval_repo.EvalRepo.get_eval_run",
                new_callable=AsyncMock,
                return_value=run,
            ),
            patch(
                "core.repos.eval_repo.EvalRepo.get_eval_results",
                new_callable=AsyncMock,
                return_value=[result],
            ),
        ):
            resp = client.get(f"/api/admin/evals/{run_id}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert "eval_run" in data
        assert "results" in data
        assert data["eval_run"]["status"] == "completed"
        assert len(data["results"]) == 1

    def test_export_eval_not_found(self, mock_app):
        client, _, _ = mock_app
        with patch(
            "core.repos.eval_repo.EvalRepo.get_eval_run",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(f"/api/admin/evals/{uuid.uuid4()}/export")
        assert resp.status_code == 404


# ── Pagination Tests ───────────────────────────────────────────


class TestPagination:
    def test_default_pagination(self, mock_app):
        client, mock_db, _ = mock_app

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.list",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "core.repos.simulation_repo.SimulationRepo.count",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            resp = client.get("/api/admin/simulations")

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 20
        assert data["offset"] == 0

    def test_custom_pagination(self, mock_app):
        client, mock_db, _ = mock_app

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.list",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "core.repos.simulation_repo.SimulationRepo.count",
                new_callable=AsyncMock,
                return_value=100,
            ),
        ):
            resp = client.get("/api/admin/simulations?limit=5&offset=10")

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit"] == 5
        assert data["offset"] == 10
        assert data["total"] == 100

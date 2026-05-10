"""Tests for the public simulation submission endpoint with cost/rate guardrails."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth.dependencies import get_current_user
from core.models import User
from core.public_routes import router as public_router


def _make_user(**overrides) -> User:
    defaults: dict = {
        "id": uuid.uuid4(),
        "email": "alice@example.com",
        "created_at": datetime.now(UTC),
        "last_login_at": datetime.now(UTC),
        "simulations_submitted": 0,
        "total_cost_spent": Decimal("0"),
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_sim_row(**overrides) -> dict:
    sim_id = overrides.pop("id", uuid.uuid4())
    row = {
        "id": sim_id,
        "name": overrides.pop("name", "test"),
        "description": None,
        "config": {},
        "status": overrides.pop("status", "queued"),
        "started_at": datetime.now(UTC),
        "completed_at": None,
        "simulated_duration": None,
        "real_duration": None,
        "total_conversations": 0,
        "total_turns": 0,
        "total_tokens": 0,
        "total_cost": Decimal("0"),
        "total_artifacts": 0,
        "total_management_flags": 0,
        "agents_participated": [],
        "error_log": None,
        "model_versions": {},
        "is_live": False,
        "created_at": datetime.now(UTC),
        "hypothesis": None,
        "outcomes": {},
        "learnings": [],
        "factions": [],
        "submitted_by_user_id": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def submit_app(tmp_path):
    """A minimal FastAPI app with the public router mounted and deps mocked."""
    user = _make_user()

    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(return_value=_make_sim_row())
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.execute = AsyncMock(return_value="UPDATE 1")

    mock_redis = MagicMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis
    mock_services.artifact_repo = None
    mock_services.relationship_repo = None
    mock_services.config_version_repo = None
    mock_services.world_repo = None
    mock_services.llm_client = None

    app = FastAPI()
    app.include_router(public_router)
    app.state.services = mock_services

    # Override get_current_user so we don't need to mint a real JWT
    app.dependency_overrides[get_current_user] = lambda: user

    env = {
        "PUBLIC_SIM_MAX_COST_USD": "1.00",
        "PUBLIC_USER_LIFETIME_CAP_USD": "10.00",
    }
    with (
        patch.dict(os.environ, env),
        patch(
            "core.public_routes._get_services", return_value=mock_services
        ),
        patch("core.public_routes._get_db", return_value=mock_db),
        patch("core.public_routes._get_redis", return_value=mock_redis),
    ):
        with TestClient(app) as client:
            yield client, mock_db, mock_redis, user, app


# ── Happy path ───────────────────────────────────────────────


class TestSubmitHappyPath:
    def test_creates_queued_simulation(self, submit_app) -> None:
        client, mock_db, _, user, _ = submit_app
        # Track fetchrow calls: simulation creation row
        new_sim = _make_sim_row(
            status="queued",
            submitted_by_user_id=user.id,
            name="my-sim",
        )
        # fetchrow is hit by SimulationRepo.create AND UserRepo.increment_sims_and_cost
        mock_db.fetchrow = AsyncMock(
            side_effect=[
                new_sim,
                {  # increment_sims_and_cost return — full user row
                    "id": user.id,
                    "email": user.email,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "simulations_submitted": user.simulations_submitted + 1,
                    "total_cost_spent": user.total_cost_spent + Decimal("0.5"),
                },
            ]
        )
        mock_db.fetchval = AsyncMock(return_value=0)  # 0 active sims

        resp = client.post(
            "/api/simulations/submit",
            json={
                "scenario_id": "awakening.yaml",
                "name": "my sim",
                "params": {"max_cost": 0.5},
                "hypothesis": "Will agents form factions?",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "simulation_id" in data
        assert data["status_url"].startswith("/api/simulations/")
        assert "estimated_completion_time" in data

        # Verify the create call had the right shape
        create_call = mock_db.fetchrow.call_args_list[0]
        sql = create_call.args[0]
        assert "INSERT INTO simulations" in sql
        # Check that the status was 'queued' and submitted_by_user_id was passed
        passed_args = create_call.args[1:]
        assert "queued" in passed_args
        assert user.id in passed_args

    def test_persists_effective_roster_and_user_visible_config(
        self,
        submit_app,
        tmp_path,
    ) -> None:
        client, mock_db, _, user, _ = submit_app
        sim_id = uuid.uuid4()
        mock_db.fetchrow = AsyncMock(
            side_effect=[
                _make_sim_row(
                    id=sim_id,
                    status="queued",
                    submitted_by_user_id=user.id,
                ),
                {
                    "id": user.id,
                    "email": user.email,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "simulations_submitted": 1,
                    "total_cost_spent": Decimal("0.5"),
                },
            ]
        )
        mock_db.fetchval = AsyncMock(return_value=0)

        env = {
            "PUBLIC_SIM_RUN_CONFIG_DIR": str(tmp_path),
            "PYTEST_CURRENT_TEST": "",
        }
        with patch.dict(os.environ, env), patch("subprocess.Popen") as popen:
            popen.return_value = MagicMock(pid=123)
            resp = client.post(
                "/api/simulations/submit",
                json={
                    "scenario_id": "awakening.yaml",
                    "name": "small cast",
                    "params": {
                        "max_cost": 0.5,
                        "agents": ["vera", "rex", "aurora", "pixel"],
                        "excluded_agents": ["grok"],
                        "factions": [
                            {
                                "name": "artists",
                                "members": ["aurora", "pixel"],
                                "goal": "make the show vivid",
                            }
                        ],
                        "memory_seed": {"mode": "none"},
                        "energy": {
                            "vera": 85,
                            "rex": 60,
                            "aurora": 90,
                            "pixel": 70,
                            "grok": 10,
                        },
                        "conversation_cadence": 1.25,
                    },
                },
            )

        assert resp.status_code == 200, resp.text
        create_call = mock_db.fetchrow.call_args_list[0]
        config = json.loads(create_call.args[3])
        assert config["scenario_agents"] == ["vera", "rex", "aurora", "pixel", "grok"]
        assert config["excluded_agents"] == ["grok"]
        assert config["effective_agents"] == ["vera", "rex", "aurora", "pixel"]
        assert config["agents"] == ["vera", "rex", "aurora", "pixel"]
        assert config["factions"] == [
            {
                "name": "artists",
                "members": ["aurora", "pixel"],
                "goal": "make the show vivid",
            }
        ]
        assert config["memory_seed"] == {"mode": "none"}
        assert config["energy"] == {
            "vera": 85.0,
            "rex": 60.0,
            "aurora": 90.0,
            "pixel": 70.0,
        }
        assert config["conversation_cadence"] == 1.25
        assert create_call.args[6] == ["vera", "rex", "aurora", "pixel"]

        run_config = json.loads((tmp_path / str(sim_id) / "run_config.json").read_text())
        assert run_config["agents"] == ["vera", "rex", "aurora", "pixel"]
        assert run_config["excluded_agents"] == ["grok"]
        cmd = popen.call_args.args[0]
        assert "--agents" in cmd
        assert cmd[cmd.index("--agents") + 1] == "vera,rex,aurora,pixel"
        assert "--run-config-file" in cmd

    def test_clamps_max_cost_to_per_submission_cap(self, submit_app) -> None:
        client, mock_db, *_, user, _ = submit_app
        mock_db.fetchrow = AsyncMock(
            side_effect=[
                _make_sim_row(),
                {
                    "id": user.id,
                    "email": user.email,
                    "created_at": user.created_at,
                    "last_login_at": user.last_login_at,
                    "simulations_submitted": 1,
                    "total_cost_spent": Decimal("1.0"),
                },
            ]
        )

        resp = client.post(
            "/api/simulations/submit",
            json={
                "scenario_id": "awakening.yaml",
                "name": "high-cost",
                "params": {"max_cost": 999.0},  # way above cap
            },
        )
        assert resp.status_code == 200
        # The config dict passed to INSERT should clamp max_cost to 1.0
        create_call = mock_db.fetchrow.call_args_list[0]
        config_arg = create_call.args[3]  # 3rd positional after name, description
        # config is serialized to JSON string
        assert "1.0" in config_arg


# ── Cap violations ───────────────────────────────────────────


class TestSubmitCaps:
    def test_lifetime_cap_returns_429(self, submit_app) -> None:
        client, mock_db, mock_redis, user, app = submit_app
        # User has already spent close to the lifetime cap
        big_user = _make_user(total_cost_spent=Decimal("9.95"))
        app.dependency_overrides[get_current_user] = lambda: big_user

        resp = client.post(
            "/api/simulations/submit",
            json={
                "scenario_id": "awakening.yaml",
                "name": "over-cap",
                "params": {"max_cost": 1.0},  # would push to 10.95
            },
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"]["error"] == "lifetime_cap"

    def test_concurrent_limit_returns_429(self, submit_app) -> None:
        client, mock_db, *_ = submit_app
        # 1 active simulation already in queued/running
        mock_db.fetchval = AsyncMock(return_value=1)

        resp = client.post(
            "/api/simulations/submit",
            json={"scenario_id": "awakening.yaml", "name": "second-sim"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["error"] == "concurrent_limit"

    def test_daily_limit_returns_429(self, submit_app) -> None:
        client, mock_db, mock_redis, *_ = submit_app
        mock_db.fetchval = AsyncMock(return_value=0)
        # 6th submission today — Redis incr returns 6, over the limit of 5
        mock_redis.incr = AsyncMock(return_value=6)

        resp = client.post(
            "/api/simulations/submit",
            json={"scenario_id": "awakening.yaml", "name": "burst"},
        )
        assert resp.status_code == 429
        assert resp.json()["detail"]["error"] == "daily_limit"


# ── Validation errors ────────────────────────────────────────


class TestSubmitValidation:
    def test_unauthenticated_returns_401(self) -> None:
        # Build an app WITHOUT overriding get_current_user
        mock_db = MagicMock()
        mock_db.fetchrow = AsyncMock(return_value=None)

        mock_services = MagicMock()
        mock_services.db = mock_db
        mock_services.redis = None
        mock_services.artifact_repo = None
        mock_services.relationship_repo = None
        mock_services.config_version_repo = None
        mock_services.world_repo = None
        mock_services.llm_client = None

        app = FastAPI()
        app.include_router(public_router)
        app.state.services = mock_services

        with patch("core.public_routes._get_services", return_value=mock_services):
            with TestClient(app) as client:
                resp = client.post(
                    "/api/simulations/submit",
                    json={"scenario_id": "awakening.yaml", "name": "x"},
                )
                assert resp.status_code == 401

    def test_path_traversal_rejected(self, submit_app) -> None:
        client, *_ = submit_app
        resp = client.post(
            "/api/simulations/submit",
            json={"scenario_id": "../../etc/passwd", "name": "evil"},
        )
        assert resp.status_code == 400

    def test_unknown_scenario_returns_400(self, submit_app) -> None:
        client, *_ = submit_app
        resp = client.post(
            "/api/simulations/submit",
            json={"scenario_id": "nope_does_not_exist.yaml", "name": "x"},
        )
        assert resp.status_code == 400

    def test_hypothesis_too_long_returns_422(self, submit_app) -> None:
        client, *_ = submit_app
        resp = client.post(
            "/api/simulations/submit",
            json={
                "scenario_id": "awakening.yaml",
                "name": "x",
                "hypothesis": "z" * 2001,
            },
        )
        assert resp.status_code == 422

    def test_empty_name_after_sanitize_returns_400(self, submit_app) -> None:
        client, *_ = submit_app
        resp = client.post(
            "/api/simulations/submit",
            json={"scenario_id": "awakening.yaml", "name": "!@#$%"},
        )
        assert resp.status_code == 400


# ── Repo unit tests ───────────────────────────────────────────


class TestSimulationRepoUserCounts:
    async def test_count_active_for_user(self) -> None:
        from core.repos.simulation_repo import SimulationRepo

        mock_db = MagicMock()
        mock_db.fetchval = AsyncMock(return_value=2)
        repo = SimulationRepo(mock_db)
        result = await repo.count_active_for_user(uuid.uuid4())
        assert result == 2
        sql = mock_db.fetchval.call_args.args[0]
        assert "submitted_by_user_id" in sql
        assert "queued" in sql
        assert "running" in sql

    async def test_count_today_for_user(self) -> None:
        from core.repos.simulation_repo import SimulationRepo

        mock_db = MagicMock()
        mock_db.fetchval = AsyncMock(return_value=3)
        repo = SimulationRepo(mock_db)
        result = await repo.count_today_for_user(uuid.uuid4())
        assert result == 3
        sql = mock_db.fetchval.call_args.args[0]
        assert "interval '1 day'" in sql


class TestUserRepoIncrement:
    async def test_increment_sims_and_cost(self) -> None:
        from core.repos.user_repo import UserRepo

        uid = uuid.uuid4()
        mock_db = MagicMock()
        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": uid,
                "email": "x@y.com",
                "created_at": datetime.now(UTC),
                "last_login_at": datetime.now(UTC),
                "simulations_submitted": 1,
                "total_cost_spent": Decimal("0.5"),
            }
        )
        repo = UserRepo(mock_db)
        result = await repo.increment_sims_and_cost(uid, cost_delta=Decimal("0.5"))
        assert result is not None
        assert result.simulations_submitted == 1
        assert result.total_cost_spent == Decimal("0.5")

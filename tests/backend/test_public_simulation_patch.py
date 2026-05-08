"""Tests for PATCH /api/simulations/{sim_id} (owner-authenticated research fields).

Covers hypothesis/outcomes/learnings updates by the simulation submitter.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth.dependencies import get_current_user
from core.models import Simulation, User
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


def _make_sim(*, owner_id: uuid.UUID | None, **overrides) -> Simulation:
    base: dict = {
        "id": uuid.uuid4(),
        "name": "Run A",
        "description": None,
        "config": {},
        "status": "completed",
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "total_conversations": 0,
        "total_turns": 0,
        "total_tokens": 0,
        "total_cost": Decimal("0"),
        "total_artifacts": 0,
        "total_management_flags": 0,
        "agents_participated": [],
        "is_live": False,
        "submitted_by_user_id": owner_id,
        "hypothesis": "old hypothesis",
        "outcomes": {},
        "learnings": [],
    }
    base.update(overrides)
    return Simulation(**base)


@pytest.fixture
def patch_app():
    user = _make_user()

    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(return_value=None)
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.execute = AsyncMock(return_value="UPDATE 1")

    mock_redis = MagicMock()

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis

    app = FastAPI()
    app.include_router(public_router)
    app.state.services = mock_services
    app.dependency_overrides[get_current_user] = lambda: user

    with (
        patch("core.public_routes._get_services", return_value=mock_services),
        patch("core.public_routes._get_db", return_value=mock_db),
    ):
        with TestClient(app) as client:
            yield client, mock_db, user


class TestPatchSimulationResearch:
    def test_owner_can_update_hypothesis(self, patch_app) -> None:
        client, _mock_db, user = patch_app
        sim = _make_sim(owner_id=user.id)
        updated = _make_sim(owner_id=user.id, id=sim.id, hypothesis="new hypothesis")

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.get",
                new_callable=AsyncMock,
                return_value=sim,
            ),
            patch(
                "core.repos.simulation_repo.SimulationRepo.update_research_fields",
                new_callable=AsyncMock,
                return_value=updated,
            ) as update_mock,
        ):
            resp = client.patch(
                f"/api/simulations/{sim.id}",
                json={"hypothesis": "new hypothesis"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["hypothesis"] == "new hypothesis"
        assert update_mock.await_count == 1
        kwargs = update_mock.await_args.kwargs
        assert kwargs.get("hypothesis") == "new hypothesis"

    def test_owner_can_update_outcomes_and_learnings(self, patch_app) -> None:
        client, _mock_db, user = patch_app
        sim = _make_sim(owner_id=user.id)
        new_outcomes = {"verdict": "matched", "winner": "vera"}
        new_learnings = [{"author": "user", "text": "Aurora led"}]
        updated = _make_sim(
            owner_id=user.id,
            id=sim.id,
            outcomes=new_outcomes,
            learnings=new_learnings,
        )

        with (
            patch(
                "core.repos.simulation_repo.SimulationRepo.get",
                new_callable=AsyncMock,
                return_value=sim,
            ),
            patch(
                "core.repos.simulation_repo.SimulationRepo.update_research_fields",
                new_callable=AsyncMock,
                return_value=updated,
            ) as update_mock,
        ):
            resp = client.patch(
                f"/api/simulations/{sim.id}",
                json={"outcomes": new_outcomes, "learnings": new_learnings},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["outcomes"] == new_outcomes
        assert body["learnings"] == new_learnings
        assert update_mock.await_args.kwargs["outcomes"] == new_outcomes
        assert update_mock.await_args.kwargs["learnings"] == new_learnings

    def test_non_owner_forbidden(self, patch_app) -> None:
        client, _, user = patch_app
        other_owner = uuid.uuid4()
        sim = _make_sim(owner_id=other_owner)

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.patch(
                f"/api/simulations/{sim.id}",
                json={"hypothesis": "no"},
            )
        assert resp.status_code == 403

    def test_unknown_simulation_returns_404(self, patch_app) -> None:
        client, _, _ = patch_app
        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.patch(
                f"/api/simulations/{uuid.uuid4()}",
                json={"hypothesis": "x"},
            )
        assert resp.status_code == 404

    def test_invalid_uuid_returns_400(self, patch_app) -> None:
        client, _, _ = patch_app
        resp = client.patch(
            "/api/simulations/not-a-uuid",
            json={"hypothesis": "x"},
        )
        assert resp.status_code == 400

    def test_hypothesis_length_capped(self, patch_app) -> None:
        client, _, user = patch_app
        sim = _make_sim(owner_id=user.id)
        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.patch(
                f"/api/simulations/{sim.id}",
                json={"hypothesis": "x" * 3000},
            )
        assert resp.status_code == 422

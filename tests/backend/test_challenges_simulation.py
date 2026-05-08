"""Tests for the user-submitted challenge flow (issue #433).

Covers POST /api/simulations/{sim_id}/share-as-challenge plus the new
shape of GET /api/challenges that joins simulations and filters on
shared_as_challenge.
"""

from __future__ import annotations

import os
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
        "email": "brad@example.com",
        "created_at": datetime.now(UTC),
        "last_login_at": datetime.now(UTC),
        "simulations_submitted": 0,
        "total_cost_spent": Decimal("0"),
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_sim(*, owner_id: uuid.UUID | None, shared: bool = False) -> Simulation:
    return Simulation(
        id=uuid.uuid4(),
        name="My garden run",
        description="A user-submitted scenario",
        config={},
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        total_conversations=3,
        total_turns=20,
        total_tokens=1000,
        total_cost=Decimal("0.10"),
        total_artifacts=1,
        total_management_flags=0,
        agents_participated=["vera"],
        is_live=False,
        submitted_by_user_id=owner_id,
        shared_as_challenge=shared,
    )


def _shared_row(challenge_id: int, sim_id: uuid.UUID) -> dict:
    return {
        "id": challenge_id,
        "description": "Try to grow a garden",
        "submitted_by": "brad",
        "source": "shared_simulation",
        "status": "pending",
        "assigned_agents": None,
        "result": None,
        "cost_estimate": None,
        "actual_cost": None,
        "votes": 0,
        "category": None,
        "tags": ["creative"],
        "simulation_id": sim_id,
        "shared_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "completed_at": None,
        "simulation_name": "My garden run",
        "simulation_video_url": None,
        "simulation_total_turns": 20,
        "simulation_agents": ["vera"],
    }


@pytest.fixture
def share_app():
    """Minimal app with public router and an owning user pre-bound."""
    user = _make_user()

    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(return_value=None)
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetch = AsyncMock(return_value=[])
    mock_db.execute = AsyncMock(return_value="UPDATE 1")

    mock_redis = MagicMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis

    app = FastAPI()
    app.include_router(public_router)
    app.state.services = mock_services
    app.dependency_overrides[get_current_user] = lambda: user

    with (
        patch.dict(os.environ, {}),
        patch("core.public_routes._get_services", return_value=mock_services),
        patch("core.public_routes._get_db", return_value=mock_db),
    ):
        with TestClient(app) as client:
            yield client, mock_db, mock_redis, user, app


class TestShareAsChallenge:
    def test_owner_can_share_unshared_simulation(self, share_app) -> None:
        client, mock_db, _, user, _ = share_app
        sim = _make_sim(owner_id=user.id, shared=False)

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            mock_db.fetchrow = AsyncMock(
                side_effect=[
                    # ChallengeRepo.create_for_simulation INSERT RETURNING *
                    {
                        "id": 7,
                        "description": "Try to grow a garden",
                        "submitted_by": "brad",
                        "source": "shared_simulation",
                        "status": "pending",
                        "assigned_agents": None,
                        "result": None,
                        "cost_estimate": None,
                        "actual_cost": None,
                        "votes": 0,
                        "category": None,
                        "tags": ["creative"],
                        "simulation_id": sim.id,
                        "shared_at": datetime.now(UTC),
                        "created_at": datetime.now(UTC),
                        "completed_at": None,
                    },
                    # ChallengeRepo.get_shared joined fetch
                    _shared_row(7, sim.id),
                ]
            )
            resp = client.post(
                f"/api/simulations/{sim.id}/share-as-challenge",
                json={
                    "description": "Try to grow a garden",
                    "tags": ["creative"],
                },
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == 7
        assert body["simulation_id"] == str(sim.id)
        assert body["tags"] == ["creative"]
        # The simulation row was flipped to shared_as_challenge=TRUE
        update_calls = [
            call for call in mock_db.execute.await_args_list
            if "shared_as_challenge = TRUE" in call.args[0]
        ]
        assert update_calls, "expected an UPDATE setting shared_as_challenge=TRUE"

    def test_non_owner_cannot_share(self, share_app) -> None:
        client, _, _, user, _ = share_app
        # Simulation is owned by a *different* user
        other_id = uuid.uuid4()
        sim = _make_sim(owner_id=other_id, shared=False)

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.post(
                f"/api/simulations/{sim.id}/share-as-challenge",
                json={"description": "x"},
            )
        assert resp.status_code == 403

    def test_already_shared_simulation_rejected(self, share_app) -> None:
        client, _, _, user, _ = share_app
        sim = _make_sim(owner_id=user.id, shared=True)

        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.post(
                f"/api/simulations/{sim.id}/share-as-challenge",
                json={"description": "x"},
            )
        assert resp.status_code == 409

    def test_blank_description_rejected(self, share_app) -> None:
        client, _, _, user, _ = share_app
        sim = _make_sim(owner_id=user.id, shared=False)
        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=sim,
        ):
            resp = client.post(
                f"/api/simulations/{sim.id}/share-as-challenge",
                json={"description": "   ", "tags": []},
            )
        assert resp.status_code == 400

    def test_unknown_simulation_returns_404(self, share_app) -> None:
        client, _, _, user, _ = share_app
        with patch(
            "core.repos.simulation_repo.SimulationRepo.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post(
                f"/api/simulations/{uuid.uuid4()}/share-as-challenge",
                json={"description": "anything"},
            )
        assert resp.status_code == 404

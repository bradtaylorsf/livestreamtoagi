"""Roundtrip test for the assertions write → read path.

Issue #405: ensures that running the AssertionEngine writes rows to
phase_assertions, that AssertionRepo can read them back, and that the
FastAPI route renames DB columns (phase_name, assertion_name, error_message,
passed) into the shape the frontend consumes (phase, name, message, status).
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.repos.assertion_repo import AssertionRepo
from core.simulation.assertions import AssertionEngine
from core.simulation.phases import PhaseResult


class _FakeAssertionStore:
    """In-memory stand-in for the phase_assertions table."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def execute(self, query: str, *args) -> str:
        # Mirror AssertionRepo.save_results INSERT signature.
        if "INSERT INTO phase_assertions" in query:
            (
                simulation_id,
                phase_name,
                assertion_name,
                passed,
                expected,
                actual,
                severity,
                error_message,
            ) = args
            self.rows.append(
                {
                    "id": uuid.uuid4(),
                    "simulation_id": simulation_id,
                    "phase_name": phase_name,
                    "assertion_name": assertion_name,
                    "passed": passed,
                    "expected": expected,
                    "actual": actual,
                    "severity": severity,
                    "error_message": error_message,
                }
            )
        return "INSERT 0 1"

    async def fetch(self, query: str, *args) -> list[dict]:
        if "FROM phase_assertions" in query and "simulation_id = $1" in query:
            sim_id = args[0]
            return [dict(r) for r in self.rows if r["simulation_id"] == sim_id]
        return []

    async def fetchrow(self, query: str, *args) -> dict | None:
        return None

    async def fetchval(self, query: str, *args) -> int:
        return len(self.rows)


@pytest.mark.asyncio
async def test_engine_persists_baseline_assertions_then_repo_reads_them():
    """AssertionEngine → AssertionRepo full roundtrip with a fake DB."""
    store = _FakeAssertionStore()
    repo = AssertionRepo(store)
    engine = AssertionEngine(assertion_repo=repo)

    sim_id = uuid.uuid4()
    phase_result = PhaseResult(
        status="completed",
        turns=5,
        cost=Decimal("0.05"),
        artifacts=2,
        management_flags=0,
        agents_participated=["vera", "rex"],
    )

    written = await engine.evaluate_conversation_defaults(
        phase_result, sim_id, config={}, phase_name="auto_qa"
    )
    assert len(written) == 4  # min_turns, max_cost, no_errors, management_flags
    assert all(r.passed for r in written)

    # Round-trip read
    rows = await repo.get_by_simulation(sim_id)
    assert len(rows) == 4
    names = sorted(r["assertion_name"] for r in rows)
    assert names == sorted(["min_turns", "max_cost", "no_errors", "management_flags"])
    assert all(r["phase_name"] == "auto_qa" for r in rows)
    assert all(r["passed"] is True for r in rows)


def test_route_renames_phase_and_name_fields():
    """`/api/simulations/{id}/assertions` must rename DB columns to the
    `phase`, `name`, `status`, `message` shape the frontend expects."""
    sim_id = uuid.uuid4()
    db_rows = [
        {
            "id": uuid.uuid4(),
            "simulation_id": sim_id,
            "phase_name": "auto_qa",
            "assertion_name": "min_turns",
            "passed": True,
            "expected": 2,
            "actual": 5,
            "severity": "warning",
            "error_message": None,
        },
        {
            "id": uuid.uuid4(),
            "simulation_id": sim_id,
            "phase_name": "auto_qa",
            "assertion_name": "no_errors",
            "passed": False,
            "expected": 0,
            "actual": 2,
            "severity": "error",
            "error_message": "Phase had 2 errors",
        },
    ]

    mock_db = MagicMock()
    mock_db.connect = AsyncMock()
    mock_db.disconnect = AsyncMock()
    mock_db.fetch = AsyncMock(return_value=db_rows)
    mock_db.fetchval = AsyncMock(return_value=0)
    mock_db.fetchrow = AsyncMock(return_value=None)

    mock_redis = MagicMock()
    mock_redis.connect = AsyncMock()
    mock_redis.disconnect = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock()

    mock_services = MagicMock()
    mock_services.db = mock_db
    mock_services.redis = mock_redis
    mock_services.agent_registry = MagicMock()
    mock_services.relationship_repo = None
    mock_services.artifact_repo = None
    mock_services.world_repo = None
    mock_services.llm_client = None

    mock_lifespan_services = MagicMock()
    mock_lifespan_services.db = mock_db
    mock_lifespan_services.redis = mock_redis
    mock_lifespan_services.agent_registry = MagicMock()
    mock_lifespan_services.llm_client = None
    mock_lifespan_services.core_memory = None
    mock_lifespan_services.config_loader = MagicMock(
        start_watching=AsyncMock(), stop_watching=AsyncMock()
    )

    env_overrides = {
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY", "")
        or "test-openrouter-key-for-unit-tests",
        "DATABASE_URL": os.environ.get("DATABASE_URL", "")
        or "postgresql://agi:devpassword@localhost:5434/livestream_agi",
        "ADMIN_PASSWORD": "test-admin-password",
    }

    with (
        patch.dict(os.environ, env_overrides),
        patch("core.public_routes._get_services", return_value=mock_services),
        patch("core.public_routes._get_db", return_value=mock_db),
        patch("core.public_routes._get_redis", return_value=mock_redis),
        patch("core.main.bootstrap_services", AsyncMock(return_value=mock_lifespan_services)),
        patch("core.main.shutdown_services", AsyncMock()),
        patch("core.main.init_core_memories", AsyncMock(return_value=[])),
        patch("core.main.start_scheduler"),
        patch("core.main.stop_scheduler"),
    ):
        from core.main import app

        with TestClient(app) as client:
            resp = client.get(f"/api/simulations/{sim_id}/assertions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            # Renamed fields must be present
            assert all("phase" in row for row in data)
            assert all("name" in row for row in data)
            assert all("status" in row for row in data)
            # Original DB-only field names must be gone
            assert all("phase_name" not in row for row in data)
            assert all("assertion_name" not in row for row in data)
            assert all("error_message" not in row for row in data)
            assert all("passed" not in row for row in data)

            # Status mapping
            passed_row = next(r for r in data if r["name"] == "min_turns")
            failed_row = next(r for r in data if r["name"] == "no_errors")
            assert passed_row["status"] == "pass"
            assert passed_row["phase"] == "auto_qa"
            assert failed_row["status"] == "fail"
            assert failed_row["message"] == "Phase had 2 errors"

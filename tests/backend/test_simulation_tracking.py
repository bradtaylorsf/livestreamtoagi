"""Tests for simulation tracking: models, repo CRUD, and incremental stats."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from core.models import Simulation, SimulationCreate, SimulationStatus
from core.repos.simulation_repo import SimulationRepo

# ── Helpers ────────────────────────────────────────────────────


def make_mock_db() -> MagicMock:
    db = MagicMock()
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value="DELETE 1")
    return db


def make_simulation_row(**overrides: Any) -> dict:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "sim-2026-04-03-001",
        "description": "Test simulation run",
        "config": '{"max_turns": 50, "model": "haiku"}',
        "status": "running",
        "started_at": datetime(2026, 4, 3, 12, 0),
        "completed_at": None,
        "simulated_duration": None,
        "real_duration": None,
        "total_conversations": 5,
        "total_turns": 42,
        "total_tokens": 12000,
        "total_cost": Decimal("1.2500"),
        "total_artifacts": 3,
        "total_management_flags": 1,
        "agents_participated": ["vera", "rex", "aurora"],
        "error_log": None,
        "created_at": datetime(2026, 4, 3, 12, 0),
    }
    base.update(overrides)
    return base


# ── Model Tests ────────────────────────────────────────────────


class TestSimulationModels:
    def test_simulation_status_enum(self) -> None:
        assert SimulationStatus.running == "running"
        assert SimulationStatus.completed == "completed"
        assert SimulationStatus.failed == "failed"
        assert SimulationStatus.cancelled == "cancelled"

    def test_simulation_create_defaults(self) -> None:
        sc = SimulationCreate(
            name="test-sim",
            config={"max_turns": 10},
        )
        assert sc.status == "running"
        assert sc.agents_participated == []
        assert sc.description is None
        assert sc.error_log is None
        assert sc.simulated_duration is None

    def test_simulation_create_all_fields(self) -> None:
        sc = SimulationCreate(
            name="full-sim",
            description="A full simulation",
            config={"max_turns": 100},
            status="completed",
            simulated_duration=timedelta(hours=8),
            agents_participated=["vera", "rex"],
            error_log={"errors": []},
        )
        assert sc.name == "full-sim"
        assert sc.simulated_duration == timedelta(hours=8)
        assert sc.agents_participated == ["vera", "rex"]

    def test_simulation_from_attributes(self) -> None:
        row = make_simulation_row(
            config={"max_turns": 50, "model": "haiku"},
        )
        sim = Simulation(**row)
        assert sim.name == "sim-2026-04-03-001"
        assert sim.total_conversations == 5
        assert sim.total_cost == Decimal("1.2500")
        assert sim.agents_participated == ["vera", "rex", "aurora"]

    def test_simulation_default_values(self) -> None:
        sim = Simulation(
            id=uuid.uuid4(),
            name="min-sim",
            config={"key": "val"},
        )
        assert sim.total_conversations == 0
        assert sim.total_turns == 0
        assert sim.total_tokens == 0
        assert sim.total_cost == Decimal("0")
        assert sim.total_artifacts == 0
        assert sim.total_management_flags == 0
        assert sim.agents_participated == []


# ── SimulationRepo Tests ─────────────────────────────────────────


class TestSimulationRepo:
    async def test_create(self) -> None:
        db = make_mock_db()
        row = make_simulation_row()
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        create = SimulationCreate(
            name="sim-test",
            config={"max_turns": 10},
        )
        result = await repo.create(create)
        assert result.name == "sim-2026-04-03-001"
        assert result.status == "running"
        db.fetchrow.assert_awaited_once()
        sql = db.fetchrow.call_args[0][0]
        assert "INSERT INTO simulations" in sql

    async def test_get_found(self) -> None:
        db = make_mock_db()
        row = make_simulation_row()
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        result = await repo.get(row["id"])
        assert result is not None
        assert result.id == row["id"]
        sql = db.fetchrow.call_args[0][0]
        assert "SELECT * FROM simulations WHERE id = $1" in sql

    async def test_get_not_found(self) -> None:
        db = make_mock_db()
        db.fetchrow.return_value = None
        repo = SimulationRepo(db)

        result = await repo.get(uuid.uuid4())
        assert result is None

    async def test_list_no_filter(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = [make_simulation_row(), make_simulation_row()]
        repo = SimulationRepo(db)

        results = await repo.list()
        assert len(results) == 2
        sql = db.fetch.call_args[0][0]
        assert "ORDER BY started_at DESC" in sql
        assert "LIMIT $1 OFFSET $2" in sql

    async def test_list_with_status_filter(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = [make_simulation_row(status="completed")]
        repo = SimulationRepo(db)

        results = await repo.list(status="completed")
        assert len(results) == 1
        sql = db.fetch.call_args[0][0]
        assert "WHERE status = $1" in sql

    async def test_list_excludes_live_by_default(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = []
        repo = SimulationRepo(db)

        await repo.list()
        sql = db.fetch.call_args[0][0]
        assert "is_live IS NOT TRUE" in sql

    async def test_list_with_status_excludes_live_by_default(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = []
        repo = SimulationRepo(db)

        await repo.list(status="running")
        sql = db.fetch.call_args[0][0]
        assert "WHERE status = $1" in sql
        assert "is_live IS NOT TRUE" in sql

    async def test_list_include_live_drops_filter(self) -> None:
        db = make_mock_db()
        db.fetch.return_value = []
        repo = SimulationRepo(db)

        await repo.list(include_live=True)
        sql = db.fetch.call_args[0][0]
        assert "is_live" not in sql

    async def test_count_excludes_live_by_default(self) -> None:
        db = make_mock_db()
        db.fetchval.return_value = 7
        repo = SimulationRepo(db)

        result = await repo.count()
        assert result == 7
        sql = db.fetchval.call_args[0][0]
        assert "is_live IS NOT TRUE" in sql

    async def test_count_with_status_excludes_live_by_default(self) -> None:
        db = make_mock_db()
        db.fetchval.return_value = 3
        repo = SimulationRepo(db)

        result = await repo.count(status="completed")
        assert result == 3
        sql = db.fetchval.call_args[0][0]
        assert "WHERE status = $1" in sql
        assert "is_live IS NOT TRUE" in sql

    async def test_count_include_live_drops_filter(self) -> None:
        db = make_mock_db()
        db.fetchval.return_value = 8
        repo = SimulationRepo(db)

        result = await repo.count(include_live=True)
        assert result == 8
        sql = db.fetchval.call_args[0][0]
        assert "is_live" not in sql

    async def test_update_status(self) -> None:
        db = make_mock_db()
        completed_row = make_simulation_row(
            status="completed",
            completed_at=datetime(2026, 4, 3, 14, 0),
        )
        db.fetchrow.return_value = completed_row
        repo = SimulationRepo(db)

        result = await repo.update_status(
            completed_row["id"],
            "completed",
            completed_at=datetime(2026, 4, 3, 14, 0),
        )
        assert result is not None
        assert result.status == "completed"
        sql = db.fetchrow.call_args[0][0]
        assert "UPDATE simulations" in sql
        assert "SET status = $1" in sql

    async def test_update_status_not_found(self) -> None:
        db = make_mock_db()
        db.fetchrow.return_value = None
        repo = SimulationRepo(db)

        result = await repo.update_status(uuid.uuid4(), "failed")
        assert result is None

    async def test_increment_stats(self) -> None:
        db = make_mock_db()
        updated_row = make_simulation_row(
            total_conversations=6,
            total_turns=45,
            total_tokens=12500,
            total_cost=Decimal("1.3000"),
        )
        db.fetchrow.return_value = updated_row
        repo = SimulationRepo(db)

        result = await repo.increment_stats(
            updated_row["id"],
            conversations=1,
            turns=3,
            tokens=500,
            cost=Decimal("0.0500"),
        )
        assert result is not None
        assert result.total_conversations == 6
        sql = db.fetchrow.call_args[0][0]
        assert "total_conversations = total_conversations + $1" in sql
        assert "total_turns = total_turns + $2" in sql
        assert "total_tokens = total_tokens + $3" in sql
        assert "total_cost = total_cost + $4" in sql

    async def test_increment_stats_not_found(self) -> None:
        db = make_mock_db()
        db.fetchrow.return_value = None
        repo = SimulationRepo(db)

        result = await repo.increment_stats(uuid.uuid4(), turns=1)
        assert result is None

    async def test_update_agents_participated(self) -> None:
        db = make_mock_db()
        repo = SimulationRepo(db)

        sim_id = uuid.uuid4()
        await repo.update_agents_participated(sim_id, ["fork", "sentinel"])
        db.execute.assert_awaited_once()
        sql = db.execute.call_args[0][0]
        assert "DISTINCT" in sql
        assert "unnest" in sql

    async def test_update_durations(self) -> None:
        db = make_mock_db()
        row = make_simulation_row(
            simulated_duration=timedelta(hours=8),
            real_duration=timedelta(minutes=30),
        )
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        result = await repo.update_durations(
            row["id"],
            simulated_duration=timedelta(hours=8),
            real_duration=timedelta(minutes=30),
        )
        assert result is not None
        assert result.simulated_duration == timedelta(hours=8)
        assert result.real_duration == timedelta(minutes=30)

    async def test_delete_success(self) -> None:
        db = make_mock_db()
        db.execute.return_value = "DELETE 1"
        repo = SimulationRepo(db)

        result = await repo.delete(uuid.uuid4())
        assert result is True
        sql = db.execute.call_args[0][0]
        assert "DELETE FROM simulations" in sql

    async def test_delete_not_found(self) -> None:
        db = make_mock_db()
        db.execute.return_value = "DELETE 0"
        repo = SimulationRepo(db)

        result = await repo.delete(uuid.uuid4())
        assert result is False

    async def test_real_duration_fallback_when_null(self) -> None:
        """If `real_duration` is NULL but the timestamps exist, fall back to delta."""
        db = make_mock_db()
        started = datetime(2026, 4, 3, 12, 0)
        completed = datetime(2026, 4, 3, 19, 30)
        row = make_simulation_row(
            real_duration=None,
            started_at=started,
            completed_at=completed,
            status="completed",
        )
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        result = await repo.get(row["id"])
        assert result is not None
        assert result.real_duration == completed - started

    async def test_real_duration_persisted_value_preferred_over_fallback(self) -> None:
        """If `real_duration` is already set, do not overwrite with the timestamp delta."""
        db = make_mock_db()
        started = datetime(2026, 4, 3, 12, 0)
        completed = datetime(2026, 4, 3, 19, 30)
        persisted = timedelta(minutes=42)
        row = make_simulation_row(
            real_duration=persisted,
            started_at=started,
            completed_at=completed,
            status="completed",
        )
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        result = await repo.get(row["id"])
        assert result is not None
        assert result.real_duration == persisted

    async def test_create_sql_passes_serialized_jsonb(self) -> None:
        db = make_mock_db()
        row = make_simulation_row()
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        create = SimulationCreate(
            name="sim-test",
            config={"nested": {"key": "val"}},
            error_log=[{"msg": "oops"}],
        )
        await repo.create(create)
        args = db.fetchrow.call_args[0]
        # config should be JSON string
        assert '"nested"' in args[3]
        # error_log should be JSON string
        assert '"oops"' in args[7]

    async def test_update_status_with_error_log(self) -> None:
        db = make_mock_db()
        row = make_simulation_row(
            status="failed",
            error_log='[{"msg": "timeout"}]',
        )
        db.fetchrow.return_value = row
        repo = SimulationRepo(db)

        result = await repo.update_status(
            row["id"],
            "failed",
            error_log=[{"msg": "timeout"}],
        )
        assert result is not None
        assert result.status == "failed"
        assert result.error_log == [{"msg": "timeout"}]


# ── Import Tests ─────────────────────────────────────────────────


class TestSimulationImports:
    def test_repo_exported_from_init(self) -> None:
        from core.repos import SimulationRepo as Imported

        assert Imported is SimulationRepo

    def test_models_importable(self) -> None:
        from core.models import Simulation as SimModel
        from core.models import SimulationCreate as SimCreateModel

        assert SimModel is Simulation
        assert SimCreateModel is SimulationCreate

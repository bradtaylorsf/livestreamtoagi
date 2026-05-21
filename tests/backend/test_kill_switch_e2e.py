"""End-to-end proof that the phone kill switch stops the orchestrator loop."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.admin.dependencies import get_redis
from core.admin.kill_switch_routes import DEFAULT_KILL_SWITCH_TTL, router
from core.redis_keys import KILL_SWITCH_KEY
from core.simulation.orchestrator import SimulationOrchestrator


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.values:
                removed += 1
                self.values.pop(key)
                self.expirations.pop(key, None)
        return removed


def kill_switch_client(redis: FakeRedis) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")
    app.dependency_overrides[get_redis] = lambda: redis
    return TestClient(app)


def orchestrator_with_redis(redis: FakeRedis) -> SimulationOrchestrator:
    orchestrator = SimulationOrchestrator.__new__(SimulationOrchestrator)
    orchestrator._redis = redis
    orchestrator._cancelled = False
    orchestrator._config = SimpleNamespace(duration=None)
    orchestrator.clock = SimpleNamespace(elapsed=lambda: timedelta())
    return orchestrator


def test_phone_activate_and_delete_toggle_orchestrator_termination(monkeypatch) -> None:
    """The documented phone request sets the key that _terminated() reads."""
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "phone-key")
    redis = FakeRedis()
    orchestrator = orchestrator_with_redis(redis)

    assert asyncio.run(orchestrator._terminated()) is False

    with kill_switch_client(redis) as client:
        activate_response = client.post(
            "/api/admin/kill",
            headers={
                "X-Kill-Switch-Key": "phone-key",
                "Content-Type": "application/json",
            },
            json={"ttl": DEFAULT_KILL_SWITCH_TTL},
        )

        assert activate_response.status_code == 200
        assert activate_response.json() == {
            "status": "active",
            "ttl_seconds": DEFAULT_KILL_SWITCH_TTL,
        }
        assert redis.values[KILL_SWITCH_KEY] == "active"
        assert asyncio.run(orchestrator._terminated()) is True

        deactivate_response = client.delete(
            "/api/admin/kill",
            headers={"X-Kill-Switch-Key": "phone-key"},
        )

        assert deactivate_response.status_code == 200
        assert deactivate_response.json() == {"status": "deactivated"}
        assert asyncio.run(orchestrator._terminated()) is False

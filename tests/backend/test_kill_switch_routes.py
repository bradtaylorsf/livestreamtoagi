"""Tests for the dedicated kill-switch admin route."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.admin.dependencies import get_redis
from core.admin.kill_switch_routes import DEFAULT_KILL_SWITCH_TTL, router
from core.redis_keys import KILL_SWITCH_KEY


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int | None] = {}
        self.deleted: list[str] = []

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            self.deleted.append(key)
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


def test_activate_returns_503_when_server_key_is_missing(monkeypatch) -> None:
    """Server must fail closed if KILL_SWITCH_API_KEY is not configured."""
    monkeypatch.delenv("KILL_SWITCH_API_KEY", raising=False)
    redis = FakeRedis()

    with kill_switch_client(redis) as client:
        response = client.post(
            "/api/admin/kill",
            headers={"X-Kill-Switch-Key": "phone-key"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "KILL_SWITCH_API_KEY not configured on server"
    assert KILL_SWITCH_KEY not in redis.values


def test_activate_returns_403_for_bad_phone_key(monkeypatch) -> None:
    """The phone shortcut key must match KILL_SWITCH_API_KEY."""
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "expected-key")
    redis = FakeRedis()

    with kill_switch_client(redis) as client:
        response = client.post(
            "/api/admin/kill",
            headers={"X-Kill-Switch-Key": "wrong-key"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid kill switch key"
    assert KILL_SWITCH_KEY not in redis.values


def test_activate_with_default_ttl_writes_raw_kill_switch(monkeypatch) -> None:
    """Valid phone request writes the raw global kill-switch key."""
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "phone-key")
    redis = FakeRedis()

    with kill_switch_client(redis) as client:
        response = client.post(
            "/api/admin/kill",
            headers={"X-Kill-Switch-Key": "phone-key"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "active",
        "ttl_seconds": DEFAULT_KILL_SWITCH_TTL,
    }
    assert redis.values[KILL_SWITCH_KEY] == "active"
    assert redis.expirations[KILL_SWITCH_KEY] == DEFAULT_KILL_SWITCH_TTL


def test_activate_honors_json_ttl_used_by_phone_shortcuts(monkeypatch) -> None:
    """The documented JSON body can set the activation TTL."""
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "phone-key")
    redis = FakeRedis()

    with kill_switch_client(redis) as client:
        response = client.post(
            "/api/admin/kill",
            headers={"X-Kill-Switch-Key": "phone-key"},
            json={"ttl": 60},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "active", "ttl_seconds": 60}
    assert redis.values[KILL_SWITCH_KEY] == "active"
    assert redis.expirations[KILL_SWITCH_KEY] == 60


def test_activate_honors_existing_query_ttl(monkeypatch) -> None:
    """Existing query-string TTL callers remain supported."""
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "phone-key")
    redis = FakeRedis()

    with kill_switch_client(redis) as client:
        response = client.post(
            "/api/admin/kill?ttl=120",
            headers={"X-Kill-Switch-Key": "phone-key"},
            json={"ttl": 60},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "active", "ttl_seconds": 120}
    assert redis.expirations[KILL_SWITCH_KEY] == 120


def test_delete_clears_raw_kill_switch(monkeypatch) -> None:
    """DELETE deactivates the same raw global key activated by POST."""
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "phone-key")
    redis = FakeRedis()
    redis.values[KILL_SWITCH_KEY] = "active"

    with kill_switch_client(redis) as client:
        response = client.delete(
            "/api/admin/kill",
            headers={"X-Kill-Switch-Key": "phone-key"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "deactivated"}
    assert KILL_SWITCH_KEY not in redis.values
    assert redis.deleted == [KILL_SWITCH_KEY]

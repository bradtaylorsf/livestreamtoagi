from __future__ import annotations

from redis.exceptions import AuthenticationError

from core import redis_client
from core.redis_client import RedisClient


class _FakeRedis:
    def __init__(self, url: str, calls: list[str]) -> None:
        self.url = url
        self.calls = calls
        self.closed = False

    async def ping(self) -> bool:
        if self.url == "redis://localhost:6381":
            raise AuthenticationError("Authentication required.")
        return True

    async def aclose(self) -> None:
        self.closed = True


async def test_redis_client_uses_default_dev_password_for_local_bare_url(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def from_url(url: str, **_: object) -> _FakeRedis:
        calls.append(url)
        return _FakeRedis(url, calls)

    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setattr(redis_client.aioredis, "from_url", from_url)

    client = RedisClient(url="redis://localhost:6381")
    await client.connect(retries=1, delay=0)

    assert calls == ["redis://:devpassword@localhost:6381"]


async def test_redis_client_uses_env_password_for_auth_retry(monkeypatch) -> None:
    calls: list[str] = []

    def from_url(url: str, **_: object) -> _FakeRedis:
        calls.append(url)
        return _FakeRedis(url, calls)

    monkeypatch.setenv("REDIS_PASSWORD", "custom password")
    monkeypatch.setattr(redis_client.aioredis, "from_url", from_url)

    client = RedisClient(url="redis://localhost:6381")
    await client.connect(retries=1, delay=0)

    assert calls == ["redis://:custom%20password@localhost:6381"]

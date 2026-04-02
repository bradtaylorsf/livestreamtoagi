from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from core.main import app


def test_health_endpoint_degraded_without_services():
    """Health endpoint works and reports degraded when services are unreachable."""
    with (
        patch("core.main.db") as mock_db,
        patch("core.main.redis_client") as mock_redis,
        patch("core.main.agent_registry") as mock_registry,
    ):
        mock_db.connect = AsyncMock()
        mock_db.disconnect = AsyncMock()
        mock_db.fetchval = AsyncMock(side_effect=Exception("no db"))
        mock_redis.connect = AsyncMock()
        mock_redis.disconnect = AsyncMock()
        mock_redis.client = AsyncMock()
        mock_redis.client.ping = AsyncMock(side_effect=Exception("no redis"))
        mock_registry.load_all = AsyncMock()

        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["database"] == "error"
            assert data["redis"] == "error"


def test_health_endpoint_ok_with_services():
    """Health endpoint reports ok when services are reachable."""
    with (
        patch("core.main.db") as mock_db,
        patch("core.main.redis_client") as mock_redis,
        patch("core.main.agent_registry") as mock_registry,
    ):
        mock_db.connect = AsyncMock()
        mock_db.disconnect = AsyncMock()
        mock_db.fetchval = AsyncMock(return_value=1)
        mock_redis.connect = AsyncMock()
        mock_redis.disconnect = AsyncMock()
        mock_redis.client = AsyncMock()
        mock_redis.client.ping = AsyncMock(return_value=True)
        mock_registry.load_all = AsyncMock()

        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "ok"
            assert data["redis"] == "ok"

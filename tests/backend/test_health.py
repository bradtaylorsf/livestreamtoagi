from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from core.main import app


def _mock_services(*, db_side_effect=None, redis_side_effect=None):
    """Create a mock Services object for health endpoint tests."""
    svc = MagicMock()
    svc.db.fetchval = AsyncMock(
        side_effect=db_side_effect, return_value=1 if db_side_effect is None else None,
    )
    svc.redis.ping = AsyncMock(
        side_effect=redis_side_effect, return_value=True if redis_side_effect is None else None,
    )
    svc.config_loader.start_watching = AsyncMock()
    svc.config_loader.stop_watching = AsyncMock()
    svc.llm_client.close = AsyncMock()
    svc.http_client.aclose = AsyncMock()
    svc.redis.disconnect = AsyncMock()
    svc.db.disconnect = AsyncMock()
    return svc


def test_health_endpoint_degraded_without_services():
    """Health endpoint works and reports degraded when services are unreachable."""
    mock_svc = _mock_services(
        db_side_effect=Exception("no db"),
        redis_side_effect=Exception("no redis"),
    )

    with (
        patch("core.main.bootstrap_services", new_callable=AsyncMock, return_value=mock_svc),
        patch("core.main.shutdown_services", new_callable=AsyncMock),
        patch("core.main.start_scheduler"),
        patch("core.main.stop_scheduler"),
    ):
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["database"].startswith("error")
            assert data["redis"].startswith("error")


def test_health_endpoint_ok_with_services():
    """Health endpoint reports ok when services are reachable."""
    mock_svc = _mock_services()

    with (
        patch("core.main.bootstrap_services", new_callable=AsyncMock, return_value=mock_svc),
        patch("core.main.shutdown_services", new_callable=AsyncMock),
        patch("core.main.start_scheduler"),
        patch("core.main.stop_scheduler"),
    ):
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database"] == "ok"
            assert data["redis"] == "ok"

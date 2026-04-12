"""Tests for /api/dev/* endpoint authentication (#352)."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.main import app


client = TestClient(app, raise_server_exceptions=False)


def test_dev_simulate_blocked_in_production():
    """Dev simulate endpoint returns 403 when ENV=production."""
    with patch.dict(os.environ, {"ENV": "production"}):
        resp = client.post("/api/dev/simulate", json={"turns": 1})
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


def test_dev_emit_blocked_in_production():
    """Dev emit endpoint returns 403 when ENV=production."""
    with patch.dict(os.environ, {"ENV": "production"}):
        resp = client.post("/api/dev/emit", json={"event_type": "test", "data": {}})
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


def test_dev_simulate_allowed_in_development():
    """Dev simulate endpoint is accessible when ENV=development."""
    with patch.dict(os.environ, {"ENV": "development"}):
        # Will fail deeper (no services), but should not get 403
        resp = client.post("/api/dev/simulate", json={"turns": 1})
    assert resp.status_code != 403


def test_dev_emit_allowed_by_default():
    """Dev emit endpoint is accessible when ENV is not set (defaults to development)."""
    with patch.dict(os.environ, {}, clear=False):
        env_backup = os.environ.pop("ENV", None)
        try:
            resp = client.post("/api/dev/emit", json={"event_type": "test", "data": {}})
        finally:
            if env_backup is not None:
                os.environ["ENV"] = env_backup
    assert resp.status_code != 403

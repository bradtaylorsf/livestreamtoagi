"""Smoke tests for core.auth.dev_email_app — the self-contained QA entrypoint.

This app exists so QA can verify the EMAIL_PROVIDER=console capture loop from
issue #466 without a live database (core.main:app's lifespan refuses to start
without DATABASE_URL). If these tests break, the live verification flow in
plan-issue-466.json (`uvicorn core.auth.dev_email_app:app --port 8765`) breaks.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.auth.dev_email_app import app


def test_healthz_returns_ok() -> None:
    """Verifier polls /healthz to know when uvicorn is ready to serve."""
    with TestClient(app) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_magic_link_writes_jsonl_with_link(tmp_path) -> None:
    """End-to-end: the QA flow that the verifier executes."""
    log_path = tmp_path / "emails.test.jsonl"
    env = {
        "EMAIL_PROVIDER": "console",
        "EMAIL_FROM": "no-reply@dev",
        "PUBLIC_BASE_URL": "http://localhost:8000",
        "EMAIL_CONSOLE_LOG": str(log_path),
        "AUTH_JWT_SECRET": "d" * 32,
    }
    with patch.dict(os.environ, env), TestClient(app) as client:
        resp = client.post("/api/auth/magic-link", json={"email": "qa@example.com"})
    assert resp.status_code == 200
    record = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["to"] == "qa@example.com"
    assert record["links"], "expected at least one link"
    link = record["links"][0]
    assert "/api/auth/verify" in link
    assert "token=" in link

"""Tests for the simulation-complete email notification."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.models import Simulation, User
from core.notifications.simulation_complete import (
    NotificationSendResult,
    send_completion_email,
)
from core.public_routes import router as public_router


def _make_user(**overrides) -> User:
    defaults: dict = {
        "id": uuid.uuid4(),
        "email": "alice@example.com",
        "created_at": datetime.now(UTC),
        "last_login_at": datetime.now(UTC),
        "simulations_submitted": 1,
        "total_cost_spent": Decimal("0"),
        "notify_on_complete": True,
        "unsubscribe_token": "tok-abc",
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_sim(**overrides) -> Simulation:
    defaults: dict = {
        "id": uuid.uuid4(),
        "name": "factions-test",
        "description": "Will agents form factions?",
        "config": {},
        "status": "completed",
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
        "total_conversations": 3,
        "total_turns": 42,
        "total_tokens": 1000,
        "total_cost": Decimal("0.42"),
        "agents_participated": ["vera", "rex"],
        "submitted_by_user_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return Simulation(**defaults)


# ── send_completion_email ────────────────────────────────────


class TestSendCompletionEmail:
    @pytest.fixture(autouse=True)
    def _env(self):
        with patch.dict(
            os.environ,
            {
                "PUBLIC_BASE_URL": "https://app.test.example",
                "EMAIL_PROVIDER": "console",
            },
        ):
            yield

    @pytest.mark.asyncio
    async def test_sends_success_email(self) -> None:
        user = _make_user()
        sim = _make_sim(status="completed", name='"escape" sim')

        captured: dict = {}

        async def fake_send(**kwargs):
            captured.update(kwargs)

        repo = MagicMock()
        repo.ensure_unsubscribe_token = AsyncMock(return_value="tok-abc")

        with patch(
            "core.notifications.simulation_complete.send_email",
            side_effect=fake_send,
        ):
            result = await send_completion_email(sim, user, user_repo=repo)

        assert isinstance(result, NotificationSendResult)
        assert result.sent is True
        assert result.delivery_error is None
        assert captured["to"] == user.email
        assert "completed successfully" in captured["subject"]
        # workspace link present in both bodies
        assert (
            f"https://app.test.example/simulations/{sim.id}"
            in captured["body_text"]
        )
        assert (
            f"https://app.test.example/simulations/{sim.id}"
            in captured["body_html"]
        )
        # unsubscribe link present
        assert (
            "https://app.test.example/api/notifications/unsubscribe"
            "?token=tok-abc" in captured["body_text"]
        )
        # HTML escaping kicked in for the simulation name
        assert "&quot;escape&quot;" in captured["body_html"]

    @pytest.mark.asyncio
    async def test_sends_failure_email_with_error_summary(self) -> None:
        user = _make_user()
        sim = _make_sim(
            status="failed",
            error_log={"runtime_errors": [{"message": "Tool X exploded"}]},
        )

        captured: dict = {}

        async def fake_send(**kwargs):
            captured.update(kwargs)

        repo = MagicMock()
        repo.ensure_unsubscribe_token = AsyncMock(return_value="tok-abc")

        with patch(
            "core.notifications.simulation_complete.send_email",
            side_effect=fake_send,
        ):
            result = await send_completion_email(sim, user, user_repo=repo)

        assert result.sent is True
        assert "failed" in captured["subject"]
        assert "Tool X exploded" in captured["body_text"]
        assert "Tool X exploded" in captured["body_html"]

    @pytest.mark.asyncio
    async def test_includes_video_link_when_available(self) -> None:
        user = _make_user()
        sim = _make_sim(status="completed")

        captured: dict = {}

        async def fake_send(**kwargs):
            captured.update(kwargs)

        repo = MagicMock()
        repo.ensure_unsubscribe_token = AsyncMock(return_value="tok-abc")

        with patch(
            "core.notifications.simulation_complete.send_email",
            side_effect=fake_send,
        ):
            result = await send_completion_email(
                sim,
                user,
                user_repo=repo,
                video_url="https://cdn.test/video.mp4",
            )

        assert result.sent is True
        assert "https://cdn.test/video.mp4" in captured["body_text"]
        assert "https://cdn.test/video.mp4" in captured["body_html"]

    @pytest.mark.asyncio
    async def test_skips_when_user_opted_out(self) -> None:
        user = _make_user(notify_on_complete=False)
        sim = _make_sim()

        sender = AsyncMock()
        repo = MagicMock()
        repo.ensure_unsubscribe_token = AsyncMock()

        with patch(
            "core.notifications.simulation_complete.send_email",
            new=sender,
        ):
            result = await send_completion_email(sim, user, user_repo=repo)

        assert result.sent is False
        assert result.skipped_reason == "opted_out"
        sender.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfills_missing_unsubscribe_token(self) -> None:
        user = _make_user(unsubscribe_token=None)
        sim = _make_sim()

        captured: dict = {}

        async def fake_send(**kwargs):
            captured.update(kwargs)

        repo = MagicMock()
        repo.ensure_unsubscribe_token = AsyncMock(return_value="freshly-minted")

        with patch(
            "core.notifications.simulation_complete.send_email",
            side_effect=fake_send,
        ):
            result = await send_completion_email(sim, user, user_repo=repo)

        assert result.sent is True
        repo.ensure_unsubscribe_token.assert_awaited_once_with(user.id)
        assert "token=freshly-minted" in captured["body_text"]

    @pytest.mark.asyncio
    async def test_returns_error_on_provider_failure(self) -> None:
        from core.auth.email import EmailSendError

        user = _make_user()
        sim = _make_sim()

        async def fake_send(**kwargs):
            raise EmailSendError("Resend failed: 500 boom")

        repo = MagicMock()
        repo.ensure_unsubscribe_token = AsyncMock(return_value="tok-abc")

        with patch(
            "core.notifications.simulation_complete.send_email",
            side_effect=fake_send,
        ):
            result = await send_completion_email(sim, user, user_repo=repo)

        assert result.sent is False
        assert result.delivery_error and "boom" in result.delivery_error


# ── Unsubscribe endpoint ─────────────────────────────────────


@pytest.fixture
def unsub_app():
    mock_db = MagicMock()
    mock_db.fetchrow = AsyncMock(return_value=None)
    mock_db.execute = AsyncMock(return_value="UPDATE 1")

    mock_services = MagicMock()
    mock_services.db = mock_db

    app = FastAPI()
    app.include_router(public_router)
    app.state.services = mock_services

    with patch("core.public_routes._get_db", return_value=mock_db):
        with TestClient(app) as client:
            yield client, mock_db


class TestUnsubscribeEndpoint:
    def test_unknown_token_returns_404(self, unsub_app):
        client, mock_db = unsub_app
        mock_db.fetchrow = AsyncMock(return_value=None)

        resp = client.get("/api/notifications/unsubscribe?token=does-not-exist")

        assert resp.status_code == 404
        assert "no longer valid" in resp.text

    def test_valid_token_flips_notify_flag(self, unsub_app):
        client, mock_db = unsub_app

        user_id = uuid.uuid4()
        user_row = {
            "id": user_id,
            "email": "alice@example.com",
            "created_at": datetime.now(UTC),
            "last_login_at": datetime.now(UTC),
            "simulations_submitted": 0,
            "total_cost_spent": Decimal("0"),
            "notify_on_complete": True,
            "unsubscribe_token": "tok-xyz",
        }
        # First fetchrow → get_by_unsubscribe_token, second → set_notify_on_complete
        updated_row = {**user_row, "notify_on_complete": False}
        mock_db.fetchrow = AsyncMock(side_effect=[user_row, updated_row])

        resp = client.get("/api/notifications/unsubscribe?token=tok-xyz")

        assert resp.status_code == 200
        assert "unsubscribed" in resp.text.lower()
        # The UPDATE query was issued
        assert mock_db.fetchrow.await_count == 2
        update_sql = mock_db.fetchrow.await_args_list[1].args[0]
        assert "UPDATE users" in update_sql
        assert "notify_on_complete" in update_sql
        # And the flag was set to False
        assert mock_db.fetchrow.await_args_list[1].args[1] is False

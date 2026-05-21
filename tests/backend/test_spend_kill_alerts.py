"""Tests for operator spend and kill-switch notifications."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.admin.dependencies import get_redis
from core.admin.kill_switch_routes import router as kill_switch_router
from core.auth.email import EmailSendError
from core.event_bus import EventBus, EventType
from core.notifications.spend_kill_alerts import (
    SpendAlertNotifier,
    send_spend_alert,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                self.values.pop(key, None)
        return deleted


def _budget_event(**overrides: Any) -> dict[str, Any]:
    data = {
        "agent_id": "vera",
        "window_spend_usd": 0.81,
        "cap_usd": 1.0,
        "tripped": False,
        "window_started_at": "2026-05-21T10:00:00Z",
        "window_seconds": 3600,
    }
    data.update(overrides)
    return {"event_type": "budget_update", "timestamp": 1779390000.0, "data": data}


@pytest.fixture
def alert_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALERT_EMAIL", "ops@example.com")
    monkeypatch.setenv("SPEND_ALERT_THRESHOLD_PCT", "0.8")
    monkeypatch.setenv("EMAIL_PROVIDER", "console")


@pytest.mark.asyncio
async def test_budget_update_under_threshold_sends_no_email(
    alert_env: None,
) -> None:
    notifier = SpendAlertNotifier(redis_client=FakeRedis())
    sender = AsyncMock()

    with patch("core.notifications.spend_kill_alerts.send_email", new=sender):
        result = await notifier.on_budget_update(_budget_event(window_spend_usd=0.79))

    assert result is not None
    assert result.sent is False
    assert result.skipped_reason == "below_threshold"
    sender.assert_not_called()


@pytest.mark.asyncio
async def test_budget_update_at_threshold_sends_one_deduped_approach_email(
    alert_env: None,
) -> None:
    redis = FakeRedis()
    notifier = SpendAlertNotifier(redis_client=redis)
    sender = AsyncMock()

    with patch("core.notifications.spend_kill_alerts.send_email", new=sender):
        first = await notifier.on_budget_update(_budget_event(window_spend_usd=0.8))
        second = await notifier.on_budget_update(_budget_event(window_spend_usd=0.9))

    assert first is not None and first.sent is True
    assert second is not None and second.sent is False
    assert second.skipped_reason == "duplicate"
    sender.assert_awaited_once()
    assert redis.expirations["spend_alert_sent:vera:2026-05-21T10_00_00Z:approach"] == 3600


@pytest.mark.asyncio
async def test_tripped_budget_update_sends_trip_after_approach_alert(
    alert_env: None,
) -> None:
    notifier = SpendAlertNotifier(redis_client=FakeRedis())
    sender = AsyncMock()

    with patch("core.notifications.spend_kill_alerts.send_email", new=sender):
        approach = await notifier.on_budget_update(_budget_event(window_spend_usd=0.9))
        tripped = await notifier.on_budget_update(
            _budget_event(window_spend_usd=1.01, tripped=True)
        )

    assert approach is not None and approach.sent is True
    assert tripped is not None and tripped.sent is True
    assert sender.await_count == 2
    subjects = [call.kwargs["subject"] for call in sender.await_args_list]
    assert any("Spend alert" in subject for subject in subjects)
    assert any("Spend cap tripped" in subject for subject in subjects)


@pytest.mark.asyncio
async def test_budget_update_emitted_on_event_bus_triggers_alert(
    alert_env: None,
) -> None:
    bus = EventBus()
    notifier = SpendAlertNotifier(redis_client=FakeRedis())
    bus.on(EventType.BUDGET_UPDATE, notifier.on_budget_update)
    sender = AsyncMock()

    with patch("core.notifications.spend_kill_alerts.send_email", new=sender):
        await bus.emit(
            EventType.BUDGET_UPDATE,
            _budget_event(window_spend_usd=0.91)["data"],
        )

    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_alert_email_skips_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALERT_EMAIL", raising=False)
    notifier = SpendAlertNotifier(redis_client=FakeRedis())
    sender = AsyncMock()

    with patch("core.notifications.spend_kill_alerts.send_email", new=sender):
        result = await notifier.on_budget_update(_budget_event(window_spend_usd=0.9))

    assert result is not None
    assert result.sent is False
    assert result.skipped_reason == "no_recipient"
    sender.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_failure_returns_delivery_error(
    alert_env: None,
) -> None:
    async def fail_send(**kwargs: Any) -> None:
        raise EmailSendError("Resend failed: 500 boom")

    with patch("core.notifications.spend_kill_alerts.send_email", side_effect=fail_send):
        result = await send_spend_alert(
            agent_id="vera",
            spend_usd=0.9,
            cap_usd=1.0,
            level="approach",
            threshold_pct=0.8,
        )

    assert result.sent is False
    assert result.delivery_error and "boom" in result.delivery_error


def _kill_client(redis: FakeRedis) -> TestClient:
    app = FastAPI()
    app.include_router(kill_switch_router)
    app.dependency_overrides[get_redis] = lambda: redis
    return TestClient(app)


def test_kill_switch_post_sends_activation_alert(
    alert_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "kill-secret")
    redis = FakeRedis()
    captured: dict[str, Any] = {}

    async def fake_send(**kwargs: Any) -> None:
        captured.update(kwargs)

    with _kill_client(redis) as client:
        with patch("core.notifications.spend_kill_alerts.send_email", side_effect=fake_send):
            response = client.post(
                "/kill?ttl=123",
                headers={"X-Kill-Switch-Key": "kill-secret"},
            )

    assert response.status_code == 200
    assert redis.values["kill_switch"] == "active"
    assert redis.expirations["kill_switch"] == 123
    assert captured["to"] == "ops@example.com"
    assert "Kill switch activated" in captured["subject"]
    assert "Source: api" in captured["body_text"]
    assert "Actor: kill_switch_api_key" in captured["body_text"]
    assert "TTL seconds: 123" in captured["body_text"]


def test_kill_switch_alert_failure_does_not_prevent_activation(
    alert_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KILL_SWITCH_API_KEY", "kill-secret")
    redis = FakeRedis()

    async def fail_send(**kwargs: Any) -> None:
        raise EmailSendError("provider down")

    with _kill_client(redis) as client:
        with patch("core.notifications.spend_kill_alerts.send_email", side_effect=fail_send):
            response = client.post(
                "/kill?ttl=321",
                headers={"X-Kill-Switch-Key": "kill-secret"},
            )

    assert response.status_code == 200
    assert response.json() == {"status": "active", "ttl_seconds": 321}
    assert redis.values["kill_switch"] == "active"
    assert redis.expirations["kill_switch"] == 321

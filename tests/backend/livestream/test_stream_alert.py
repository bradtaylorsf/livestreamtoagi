from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.auth.email import EmailSendError
from core.livestream import STREAM_DOWN, HealthEvent
from core.notifications.stream_alert import send_stream_alert


@pytest.mark.asyncio
async def test_send_stream_alert_builds_subject_and_bodies(monkeypatch) -> None:
    event = HealthEvent(
        type=STREAM_DOWN,
        detected_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        details={"reason": "pid_not_running_no_restart_recorded"},
    )
    calls: list[dict[str, str | None]] = []

    async def sender(
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        calls.append(
            {
                "to": to,
                "subject": subject,
                "body_text": body_text,
                "body_html": body_html,
            }
        )

    monkeypatch.setattr(
        "core.notifications.stream_alert.socket.gethostname",
        lambda: "qa-host",
    )

    result = await send_stream_alert(
        event,
        recipient="ops@example.com",
        sender=sender,
    )

    assert result.sent
    assert len(calls) == 1
    assert calls[0]["to"] == "ops@example.com"
    assert calls[0]["subject"] == "[stream-alert] stream_down on qa-host"
    assert "Type: stream_down" in calls[0]["body_text"]
    assert "docs/livestream/monitoring.md" in calls[0]["body_text"]
    assert "pid_not_running_no_restart_recorded" in calls[0]["body_text"]
    assert calls[0]["body_html"] is not None
    assert "stream_down" in calls[0]["body_html"]


@pytest.mark.asyncio
async def test_send_stream_alert_skips_when_recipient_missing(monkeypatch) -> None:
    event = HealthEvent(
        type=STREAM_DOWN,
        detected_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        details={},
    )
    monkeypatch.delenv("STREAM_ALERT_EMAIL", raising=False)

    async def sender(**kwargs) -> None:  # noqa: ANN003
        raise AssertionError(f"sender should not be called: {kwargs}")

    result = await send_stream_alert(event, sender=sender)

    assert not result.sent
    assert result.skipped_reason == "no_recipient"


@pytest.mark.asyncio
async def test_send_stream_alert_returns_delivery_error() -> None:
    event = HealthEvent(
        type=STREAM_DOWN,
        detected_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        details={},
    )

    async def sender(**kwargs) -> None:  # noqa: ANN003
        del kwargs
        raise EmailSendError("provider unavailable")

    result = await send_stream_alert(
        event,
        recipient="ops@example.com",
        sender=sender,
    )

    assert not result.sent
    assert result.delivery_error == "provider unavailable"

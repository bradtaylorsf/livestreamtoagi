"""Email alerts for livestream health events."""

from __future__ import annotations

import html
import json
import logging
import os
import socket
from typing import Protocol

from core.auth.email import EmailSendError, send_email
from core.livestream import HealthEvent
from core.notifications.simulation_complete import NotificationSendResult

logger = logging.getLogger(__name__)

RUNBOOK_LINK = "docs/livestream/monitoring.md"


class EmailSender(Protocol):
    async def __call__(
        self,
        *,
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> None:
        """Send an email."""


def _details_json(event: HealthEvent) -> str:
    return json.dumps(event.details, indent=2, sort_keys=True, default=str)


def _plain_body(event: HealthEvent, hostname: str) -> str:
    return "\n".join(
        [
            "Livestream health alert",
            "",
            f"Host: {hostname}",
            f"Type: {event.type}",
            f"Detected at: {event.detected_at.isoformat()}",
            f"Runbook: {RUNBOOK_LINK}",
            "",
            "Details:",
            _details_json(event),
            "",
        ]
    )


def _html_body(event: HealthEvent, hostname: str) -> str:
    details = html.escape(_details_json(event))
    return (
        "<html><body>"
        "<h1>Livestream health alert</h1>"
        "<p>"
        f"<strong>Host:</strong> {html.escape(hostname)}<br>"
        f"<strong>Type:</strong> {html.escape(event.type)}<br>"
        f"<strong>Detected at:</strong> {html.escape(event.detected_at.isoformat())}<br>"
        f"<strong>Runbook:</strong> {html.escape(RUNBOOK_LINK)}"
        "</p>"
        f"<pre>{details}</pre>"
        "</body></html>"
    )


async def send_stream_alert(
    event: HealthEvent,
    *,
    recipient: str | None = None,
    sender: EmailSender = send_email,
) -> NotificationSendResult:
    """Send one livestream-health alert email.

    The function never raises for provider failures; callers get a structured
    result so the health monitor can keep polling during an outage.
    """
    to = (
        recipient if recipient is not None else os.environ.get("STREAM_ALERT_EMAIL", "")
    ).strip()
    if not to:
        logger.info("[notify] skip stream alert type=%s reason=no_recipient", event.type)
        return NotificationSendResult(sent=False, skipped_reason="no_recipient")

    hostname = socket.gethostname()
    subject = f"[stream-alert] {event.type} on {hostname}"
    body_text = _plain_body(event, hostname)
    body_html = _html_body(event, hostname)

    try:
        await sender(
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except (EmailSendError, NotImplementedError) as exc:
        logger.exception("[notify] stream alert failed type=%s recipient=%s", event.type, to)
        return NotificationSendResult(sent=False, delivery_error=str(exc))

    logger.info("[notify] sent stream alert type=%s recipient=%s", event.type, to)
    return NotificationSendResult(sent=True)

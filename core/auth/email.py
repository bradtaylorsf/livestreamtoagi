"""Pluggable email sender for transactional messages (magic links, etc.).

Provider is selected by the ``EMAIL_PROVIDER`` env var:

  * ``resend`` — POST to api.resend.com (requires ``EMAIL_API_KEY``).
  * ``ses`` — placeholder; raises NotImplementedError until a real
    boto3-backed sender is wired up.
  * ``console`` (default) — log the message and pretend it was sent.
    Useful for dev and tests so we don't need API keys to exercise the
    auth flow.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)


class EmailSendError(RuntimeError):
    """Raised when the configured provider fails to deliver a message."""


async def send_email(
    *,
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> None:
    """Send a transactional email via the configured provider."""
    provider = os.environ.get("EMAIL_PROVIDER", "console").lower()
    sender = os.environ.get("EMAIL_FROM", "no-reply@livestreamtoagi.dev")

    if provider == "resend":
        api_key = os.environ.get("EMAIL_API_KEY", "")
        if not api_key:
            raise EmailSendError("EMAIL_PROVIDER=resend requires EMAIL_API_KEY")
        payload: dict[str, object] = {
            "from": sender,
            "to": [to],
            "subject": subject,
            "text": body_text,
        }
        if body_html:
            payload["html"] = body_html
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        if resp.status_code >= 300:
            raise EmailSendError(f"Resend failed: {resp.status_code} {resp.text}")
        return

    if provider == "ses":
        raise NotImplementedError("EMAIL_PROVIDER=ses is not yet implemented")

    # Console fallback — log only; convenient for dev.
    logger.info(
        "[email:console] to=%s subject=%s body=%s",
        to,
        subject,
        body_text,
    )

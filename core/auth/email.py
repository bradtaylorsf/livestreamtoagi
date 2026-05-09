"""Pluggable email sender for transactional messages (magic links, etc.).

Provider is selected by the ``EMAIL_PROVIDER`` env var:

  * ``resend`` — POST to api.resend.com (requires ``EMAIL_API_KEY``).
  * ``ses`` — placeholder; raises NotImplementedError until a real
    boto3-backed sender is wired up.
  * ``console`` (default) — log the message and pretend it was sent.
    Useful for dev and tests so we don't need API keys to exercise the
    auth flow.

When ``EMAIL_PROVIDER=console``, each send is also appended as a JSON
line to ``${EMAIL_CONSOLE_LOG:-/tmp/livestream-agi-emails.jsonl}`` so QA
can ``tail -f`` the file and copy the magic link out — uvicorn's default
log config swallows application loggers, so the ``logger.info`` line
alone isn't reliably visible. If ``EMAIL_CONSOLE_REDIS_STREAM`` is set
to a non-empty value, the same record is also XADD'd to that Redis
stream for future dev-tooling UIs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CONSOLE_LOG_PATH = "/tmp/livestream-agi-emails.jsonl"
_CONSOLE_REDIS_MAXLEN = 1000
_LINK_RE = re.compile(r"https?://\S+")
_LINK_TRIM_CHARS = ".,;:!?)\"'>"


class EmailSendError(RuntimeError):
    """Raised when the configured provider fails to deliver a message."""


def _extract_links(body_text: str) -> list[str]:
    """Pull http(s) URLs out of a plaintext body, stripping trailing punctuation."""
    links: list[str] = []
    for raw in _LINK_RE.findall(body_text or ""):
        link = raw.rstrip(_LINK_TRIM_CHARS)
        if link:
            links.append(link)
    return links


def _write_console_log(record: dict[str, object]) -> None:
    """Append a JSON line to the console-email log file. Never raises."""
    path = Path(os.environ.get("EMAIL_CONSOLE_LOG", DEFAULT_CONSOLE_LOG_PATH))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("[email:console] failed to write %s: %s", path, exc)


async def _publish_console_redis(stream: str, record: dict[str, object]) -> None:
    """XADD the record to a Redis stream. Swallows all errors."""
    try:
        import redis.asyncio as aioredis  # local import: dev-only path
    except ImportError as exc:
        logger.warning("[email:console] redis.asyncio not importable: %s", exc)
        return

    url = os.environ.get("REDIS_URL", "redis://localhost:6381")
    fields = {
        "ts": str(record.get("ts", "")),
        "to": str(record.get("to", "")),
        "subject": str(record.get("subject", "")),
        "body": str(record.get("body", "")),
        "links": json.dumps(record.get("links", [])),
    }
    client = None
    try:
        client = aioredis.from_url(url, socket_connect_timeout=2)
        await client.xadd(stream, fields, maxlen=_CONSOLE_REDIS_MAXLEN, approximate=True)
    except Exception as exc:  # noqa: BLE001 — dev convenience, never break auth
        logger.warning("[email:console] redis publish failed (%s): %s", url, exc)
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


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

    record: dict[str, object] = {
        "ts": datetime.now(UTC).isoformat(),
        "to": to,
        "subject": subject,
        "body": body_text,
        "links": _extract_links(body_text),
    }
    _write_console_log(record)

    stream = os.environ.get("EMAIL_CONSOLE_REDIS_STREAM", "").strip()
    if stream:
        await _publish_console_redis(stream, record)

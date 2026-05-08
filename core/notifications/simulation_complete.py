"""Send a templated email when a public-submitted simulation finishes."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.auth.email import EmailSendError, send_email
from core.notifications.templates import (
    render_html,
    render_plaintext,
    render_subject,
)

if TYPE_CHECKING:
    from core.models import Simulation, User
    from core.repos.user_repo import UserRepo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationSendResult:
    sent: bool
    skipped_reason: str | None = None
    delivery_error: str | None = None


def _summarize_error(sim: Simulation) -> str | None:
    """Build a short error blurb from the simulation's error_log."""
    log = sim.error_log
    if not log:
        return None
    if isinstance(log, dict):
        if "summary" in log and isinstance(log["summary"], str):
            return log["summary"][:500]
        runtime = log.get("runtime_errors")
        if isinstance(runtime, list) and runtime:
            first = runtime[0]
            if isinstance(first, dict):
                msg = first.get("message") or first.get("error") or str(first)
                return str(msg)[:500]
            return str(first)[:500]
        return str(log)[:500]
    if isinstance(log, list) and log:
        first = log[0]
        if isinstance(first, dict):
            msg = first.get("message") or first.get("error") or str(first)
            return str(msg)[:500]
        return str(first)[:500]
    return None


async def send_completion_email(
    sim: Simulation,
    user: User,
    *,
    user_repo: UserRepo,
    video_url: str | None = None,
) -> NotificationSendResult:
    """Send a completion-or-failure email to ``user`` for ``sim``.

    Returns a result describing whether the email was sent, skipped (e.g.
    user opted out), or failed at the provider boundary. Never raises.
    """
    if not user.notify_on_complete:
        logger.info(
            "[notify] skip completion email user=%s sim=%s reason=opted_out",
            user.id,
            sim.id,
        )
        return NotificationSendResult(sent=False, skipped_reason="opted_out")

    if not user.email:
        return NotificationSendResult(sent=False, skipped_reason="no_email")

    token = user.unsubscribe_token
    if not token:
        token = await user_repo.ensure_unsubscribe_token(user.id)
    if not token:
        logger.warning(
            "[notify] could not mint unsubscribe token user=%s sim=%s",
            user.id,
            sim.id,
        )
        return NotificationSendResult(sent=False, skipped_reason="no_token")

    base_url = os.environ.get(
        "PUBLIC_BASE_URL", "http://localhost:8000"
    ).rstrip("/")
    workspace_url = f"{base_url}/simulations/{sim.id}"
    unsubscribe_url = (
        f"{base_url}/api/notifications/unsubscribe?token={token}"
    )
    error_summary = _summarize_error(sim) if sim.status == "failed" else None

    subject = render_subject(name=sim.name, status=sim.status)
    body_text = render_plaintext(
        name=sim.name,
        status=sim.status,
        workspace_url=workspace_url,
        video_url=video_url,
        error_summary=error_summary,
        unsubscribe_url=unsubscribe_url,
    )
    body_html = render_html(
        name=sim.name,
        status=sim.status,
        workspace_url=workspace_url,
        video_url=video_url,
        error_summary=error_summary,
        unsubscribe_url=unsubscribe_url,
    )

    try:
        await send_email(
            to=user.email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except (EmailSendError, NotImplementedError) as exc:
        logger.exception(
            "[notify] completion email failed user=%s sim=%s status=%s",
            user.id,
            sim.id,
            sim.status,
        )
        return NotificationSendResult(
            sent=False,
            delivery_error=str(exc),
        )

    logger.info(
        "[notify] sent completion email user=%s sim=%s status=%s video=%s",
        user.id,
        sim.id,
        sim.status,
        bool(video_url),
    )
    return NotificationSendResult(sent=True)

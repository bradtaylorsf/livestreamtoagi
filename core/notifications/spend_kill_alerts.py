"""Operator alerts for spend caps and kill-switch activation."""

from __future__ import annotations

import inspect
import logging
import os
import re
import time
from typing import Any, Literal

from core.auth.email import EmailSendError, send_email
from core.notifications.simulation_complete import NotificationSendResult
from core.notifications.templates import (
    render_kill_switch_html,
    render_kill_switch_plaintext,
    render_kill_switch_subject,
    render_spend_alert_html,
    render_spend_alert_plaintext,
    render_spend_alert_subject,
)

logger = logging.getLogger(__name__)

AlertLevel = Literal["approach", "tripped"]

DEFAULT_SPEND_ALERT_THRESHOLD_PCT = 0.8
DEFAULT_BUDGET_WINDOW_SECONDS = 3600
_KEY_PART_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _alert_recipient() -> str | None:
    recipient = os.environ.get("ALERT_EMAIL", "").strip()
    return recipient or None


def _threshold_from_env() -> float:
    raw = os.environ.get("SPEND_ALERT_THRESHOLD_PCT", "").strip()
    if not raw:
        return DEFAULT_SPEND_ALERT_THRESHOLD_PCT
    try:
        threshold = float(raw)
    except ValueError:
        logger.warning(
            "[notify] invalid SPEND_ALERT_THRESHOLD_PCT=%r; using %.2f",
            raw,
            DEFAULT_SPEND_ALERT_THRESHOLD_PCT,
        )
        return DEFAULT_SPEND_ALERT_THRESHOLD_PCT
    if threshold <= 0 or threshold > 1:
        logger.warning(
            "[notify] SPEND_ALERT_THRESHOLD_PCT must be between 0 and 1; using %.2f",
            DEFAULT_SPEND_ALERT_THRESHOLD_PCT,
        )
        return DEFAULT_SPEND_ALERT_THRESHOLD_PCT
    return threshold


def _safe_key_part(value: object) -> str:
    text = str(value or "unknown").strip() or "unknown"
    return _KEY_PART_RE.sub("_", text)[:160]


def _number(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning("[notify] invalid numeric budget field %s=%r", key, value)
            return None
    return None


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "tripped"}
    return bool(value)


def _window_seconds(data: dict[str, Any]) -> int:
    seconds = _number(data, "window_seconds", "window_length_seconds", "ttl_seconds")
    if seconds is None or seconds <= 0:
        return DEFAULT_BUDGET_WINDOW_SECONDS
    return max(1, int(seconds))


def _window_key(event: dict[str, Any], data: dict[str, Any], seconds: int) -> str:
    explicit = (
        data.get("window_key")
        or data.get("window_started_at")
        or data.get("window_start")
        or data.get("hour_window")
    )
    if explicit is not None:
        return _safe_key_part(explicit)
    timestamp = _number(event, "timestamp") or time.time()
    return str(int(timestamp // seconds * seconds))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _claim_dedupe_key(redis_client: Any, key: str, ttl_seconds: int) -> bool:
    if redis_client is None:
        return True

    setter = getattr(redis_client, "set", None)
    if setter is None:
        logger.warning("[notify] redis client has no set(); spend alert dedupe disabled")
        return True

    ttl = max(1, int(ttl_seconds))
    try:
        return bool(await _maybe_await(setter(key, "1", ex=ttl, nx=True)))
    except TypeError:
        # Older/simpler test doubles may not expose nx. Fall back to get+set so
        # unit tests still exercise the dedupe behavior; real Redis uses nx.
        getter = getattr(redis_client, "get", None)
        if getter is not None and await _maybe_await(getter(key)) is not None:
            return False
        return bool(await _maybe_await(setter(key, "1", ex=ttl)))


class SpendAlertNotifier:
    """Consumes budget events and emits deduped operator spend alerts."""

    def __init__(
        self,
        *,
        redis_client: Any | None,
        threshold_pct: float | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.threshold_pct = threshold_pct if threshold_pct is not None else _threshold_from_env()

    async def on_budget_update(
        self,
        event: dict[str, Any],
    ) -> NotificationSendResult | None:
        """EventBus callback for ``EventType.BUDGET_UPDATE`` envelopes."""
        data = event.get("data", event)
        if not isinstance(data, dict):
            logger.warning("[notify] budget update ignored: data is not a dict")
            return NotificationSendResult(sent=False, skipped_reason="invalid_payload")

        agent_id = str(data.get("agent_id") or data.get("agent") or "unknown")
        spend_usd = _number(data, "window_spend_usd", "hourly_spend_usd", "spend_usd")
        cap_usd = _number(data, "cap_usd", "hourly_cap_usd", "limit_usd")
        tripped = _truthy(data.get("tripped")) or _truthy(data.get("cap_tripped"))

        if spend_usd is None or cap_usd is None or cap_usd <= 0:
            logger.warning("[notify] budget update ignored: invalid spend/cap payload=%r", data)
            return NotificationSendResult(sent=False, skipped_reason="invalid_payload")

        pct = spend_usd / cap_usd
        if tripped:
            level: AlertLevel = "tripped"
        elif pct >= self.threshold_pct:
            level = "approach"
        else:
            return NotificationSendResult(sent=False, skipped_reason="below_threshold")

        if _alert_recipient() is None:
            return await send_spend_alert(
                agent_id=agent_id,
                spend_usd=spend_usd,
                cap_usd=cap_usd,
                level=level,
                threshold_pct=self.threshold_pct,
            )

        ttl_seconds = _window_seconds(data)
        key = (
            "spend_alert_sent:"
            f"{_safe_key_part(agent_id)}:"
            f"{_window_key(event, data, ttl_seconds)}:"
            f"{level}"
        )
        if not await _claim_dedupe_key(self.redis_client, key, ttl_seconds):
            logger.info("[notify] spend alert deduped key=%s", key)
            return NotificationSendResult(sent=False, skipped_reason="duplicate")

        return await send_spend_alert(
            agent_id=agent_id,
            spend_usd=spend_usd,
            cap_usd=cap_usd,
            level=level,
            threshold_pct=self.threshold_pct,
        )


async def send_spend_alert(
    *,
    agent_id: str,
    spend_usd: float,
    cap_usd: float,
    level: AlertLevel,
    threshold_pct: float,
) -> NotificationSendResult:
    """Send a spend cap alert to the configured operator inbox. Never raises."""
    recipient = _alert_recipient()
    if recipient is None:
        logger.info("[notify] skip spend alert agent=%s level=%s reason=no_recipient", agent_id, level)
        return NotificationSendResult(sent=False, skipped_reason="no_recipient")

    subject = render_spend_alert_subject(
        agent_id=agent_id,
        spend_usd=spend_usd,
        cap_usd=cap_usd,
        level=level,
        threshold_pct=threshold_pct,
    )
    body_text = render_spend_alert_plaintext(
        agent_id=agent_id,
        spend_usd=spend_usd,
        cap_usd=cap_usd,
        level=level,
        threshold_pct=threshold_pct,
    )
    body_html = render_spend_alert_html(
        agent_id=agent_id,
        spend_usd=spend_usd,
        cap_usd=cap_usd,
        level=level,
        threshold_pct=threshold_pct,
    )

    try:
        await send_email(
            to=recipient,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except (EmailSendError, NotImplementedError) as exc:
        logger.exception("[notify] spend alert failed agent=%s level=%s", agent_id, level)
        return NotificationSendResult(sent=False, delivery_error=str(exc))

    logger.info("[notify] sent spend alert agent=%s level=%s", agent_id, level)
    return NotificationSendResult(sent=True)


async def send_kill_switch_alert(
    *,
    source: str,
    ttl_seconds: int,
    actor: str,
) -> NotificationSendResult:
    """Send a kill-switch activation alert to the operator inbox. Never raises."""
    recipient = _alert_recipient()
    if recipient is None:
        logger.info("[notify] skip kill-switch alert source=%s reason=no_recipient", source)
        return NotificationSendResult(sent=False, skipped_reason="no_recipient")

    subject = render_kill_switch_subject(source=source, ttl_seconds=ttl_seconds, actor=actor)
    body_text = render_kill_switch_plaintext(
        source=source,
        ttl_seconds=ttl_seconds,
        actor=actor,
    )
    body_html = render_kill_switch_html(
        source=source,
        ttl_seconds=ttl_seconds,
        actor=actor,
    )

    try:
        await send_email(
            to=recipient,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
    except (EmailSendError, NotImplementedError) as exc:
        logger.exception("[notify] kill-switch alert failed source=%s", source)
        return NotificationSendResult(sent=False, delivery_error=str(exc))

    logger.info("[notify] sent kill-switch alert source=%s actor=%s", source, actor)
    return NotificationSendResult(sent=True)

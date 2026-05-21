"""Outbound user notifications (email, etc.)."""

from __future__ import annotations

from core.notifications.simulation_complete import (
    NotificationSendResult,
    send_completion_email,
)
from core.notifications.spend_kill_alerts import (
    SpendAlertNotifier,
    send_kill_switch_alert,
    send_spend_alert,
)
from core.notifications.stream_alert import send_stream_alert

__all__ = [
    "NotificationSendResult",
    "SpendAlertNotifier",
    "send_completion_email",
    "send_kill_switch_alert",
    "send_spend_alert",
    "send_stream_alert",
]

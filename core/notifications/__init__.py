"""Outbound user notifications (email, etc.)."""

from __future__ import annotations

from core.notifications.simulation_complete import (
    NotificationSendResult,
    send_completion_email,
)
from core.notifications.stream_alert import send_stream_alert

__all__ = ["NotificationSendResult", "send_completion_email", "send_stream_alert"]

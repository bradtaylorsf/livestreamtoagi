"""Outbound user notifications (email, etc.)."""

from __future__ import annotations

from core.notifications.simulation_complete import (
    NotificationSendResult,
    send_completion_email,
)

__all__ = ["NotificationSendResult", "send_completion_email"]

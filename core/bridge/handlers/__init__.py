"""Bridge service handlers."""

from __future__ import annotations

from core.bridge.handlers.memory import handle_memory_read, handle_memory_write

__all__ = ["handle_memory_read", "handle_memory_write"]

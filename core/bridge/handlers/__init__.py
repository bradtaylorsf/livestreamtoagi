"""Bridge service handlers."""

from __future__ import annotations

from core.bridge.handlers.code_execution import handle_code_execute
from core.bridge.handlers.memory import handle_memory_read, handle_memory_write

__all__ = ["handle_code_execute", "handle_memory_read", "handle_memory_write"]

"""Bridge service handlers."""

from __future__ import annotations

from core.bridge.handlers.code_execution import handle_code_execute
from core.bridge.handlers.director import handle_director_gate
from core.bridge.handlers.errand import handle_errand_complete
from core.bridge.handlers.management import handle_management_review
from core.bridge.handlers.memory import handle_memory_read, handle_memory_write

__all__ = [
    "handle_code_execute",
    "handle_director_gate",
    "handle_errand_complete",
    "handle_management_review",
    "handle_memory_read",
    "handle_memory_write",
]

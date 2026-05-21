"""Python<->Node bridge contract package (E4, issue #541).

The bridge lets the Node Minecraft bots call Python services (memory,
Management content filter, cost gate, ...) and lets Python push control
messages back. :mod:`core.bridge.contract` is the versioned message contract —
the single source of truth both halves validate against —
and :mod:`core.bridge.server` is the authenticated FastAPI WebSocket surface
(``bridge_router``) the Node side connects to.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from core.bridge.contract import (
    PROTOCOL_VERSION,
    SERVICE_REGISTRY,
    BridgeError,
    BridgeRequest,
    BridgeResponse,
    CostContext,
    UnsupportedServiceError,
    export_json_schema,
    is_supported_version,
    parse_version,
    validate_request,
    validate_response,
)

__all__ = [
    "INBOUND_VERBS",
    "PROTOCOL_VERSION",
    "SERVICE_REGISTRY",
    "BridgeError",
    "BridgeRequest",
    "BridgeResponse",
    "CostContext",
    "UnsupportedServiceError",
    "bridge_metrics_snapshot",
    "bridge_router",
    "dispatch_inbound",
    "handle_code_execute",
    "handle_director_gate",
    "handle_errand_complete",
    "handle_management_review",
    "handle_memory_read",
    "handle_memory_write",
    "log_bridge_event",
    "record_call",
    "reset_metrics",
    "export_json_schema",
    "is_supported_version",
    "parse_version",
    "validate_request",
    "validate_response",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "INBOUND_VERBS": ("core.bridge.inbound", "INBOUND_VERBS"),
    "bridge_metrics_snapshot": ("core.bridge.observability", "bridge_metrics_snapshot"),
    "bridge_router": ("core.bridge.server", "bridge_router"),
    "dispatch_inbound": ("core.bridge.inbound", "dispatch_inbound"),
    "handle_code_execute": ("core.bridge.handlers", "handle_code_execute"),
    "handle_director_gate": ("core.bridge.handlers", "handle_director_gate"),
    "handle_errand_complete": ("core.bridge.handlers", "handle_errand_complete"),
    "handle_management_review": ("core.bridge.handlers", "handle_management_review"),
    "handle_memory_read": ("core.bridge.handlers", "handle_memory_read"),
    "handle_memory_write": ("core.bridge.handlers", "handle_memory_write"),
    "log_bridge_event": ("core.bridge.observability", "log_bridge_event"),
    "record_call": ("core.bridge.observability", "record_call"),
    "reset_metrics": ("core.bridge.observability", "reset_metrics"),
}


def __getattr__(name: str) -> Any:
    """Lazy-load bridge runtime exports to keep contract imports lightweight."""

    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

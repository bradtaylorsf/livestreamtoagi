"""Python<->Node bridge contract package (E4, issue #541).

The bridge lets the Node Minecraft bots call Python services (memory,
Management content filter, cost gate, ...) and lets Python push control
messages back. :mod:`core.bridge.contract` is the versioned message contract —
the single source of truth both halves validate against —
and :mod:`core.bridge.server` is the authenticated FastAPI WebSocket surface
(``bridge_router``) the Node side connects to.
"""

from __future__ import annotations

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
from core.bridge.handlers import (
    handle_code_execute,
    handle_errand_complete,
    handle_memory_read,
    handle_memory_write,
)
from core.bridge.inbound import INBOUND_VERBS, dispatch_inbound
from core.bridge.observability import (
    bridge_metrics_snapshot,
    log_bridge_event,
    record_call,
    reset_metrics,
)
from core.bridge.server import bridge_router

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
    "handle_errand_complete",
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

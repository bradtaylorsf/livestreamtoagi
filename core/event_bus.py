"""WebSocket event bus for broadcasting structured events to connected clients."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """All supported event types."""

    AGENT_SPEAK = "agent_speak"
    AGENT_MOVE = "agent_move"
    AGENT_ACTION = "agent_action"
    ALPHA_DISPATCH = "alpha_dispatch"
    ALPHA_RETURN = "alpha_return"
    OVERSEER_WARNING = "overseer_warning"
    OVERSEER_INTERVENTION = "overseer_intervention"
    WORLD_EXPANSION = "world_expansion"
    POLL_CREATED = "poll_created"
    POLL_RESULT = "poll_result"
    BUDGET_UPDATE = "budget_update"
    VIEWER_COUNT = "viewer_count"
    TTS_PLAY = "tts_play"
    CONFIG_RELOADED = "config_reloaded"


# Custom JSON encoder for Decimal, datetime, UUID
class _EventEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        from datetime import datetime
        from decimal import Decimal

        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        return super().default(o)


class _ClientInfo:
    """Metadata for a connected WebSocket client."""

    __slots__ = ("ws", "client_id", "connected_at")

    def __init__(self, ws: WebSocket, client_id: str) -> None:
        self.ws = ws
        self.client_id = client_id
        self.connected_at = time.time()


EventCallback = Callable[..., Coroutine[Any, Any, None]]

HISTORY_BUFFER_SIZE = 50
MAX_MESSAGE_BYTES = 1_048_576  # 1 MB
MAX_CONNECTIONS = 100


class EventBus:
    """Manages WebSocket connections, event broadcasting, and internal callbacks."""

    def __init__(self, allowed_origins: list[str] | None = None) -> None:
        self._allowed_origins = allowed_origins
        self._clients: dict[str, _ClientInfo] = {}
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=HISTORY_BUFFER_SIZE)
        self._lock = asyncio.Lock()

    @property
    def connected_count(self) -> int:
        return len(self._clients)

    def on(self, event_type: str, callback: EventCallback) -> None:
        """Register an async callback for an event type."""
        self._validate_event_type(event_type)
        self._callbacks.setdefault(event_type, []).append(callback)

    async def emit(self, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Broadcast an event to all connected WebSocket clients and fire callbacks.

        Returns the full event envelope.
        """
        self._validate_event_type(event_type)

        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": time.time(),
            "data": data or {},
        }

        message = json.dumps(event, cls=_EventEncoder)

        encoded_size = len(message.encode())
        if encoded_size > MAX_MESSAGE_BYTES:
            logger.warning(
                "Event %s payload exceeds 1MB (%d bytes)", event_type, encoded_size
            )

        self._history.append(event)

        # Fire internal callbacks (don't let one failure stop others)
        callbacks = self._callbacks.get(event_type, [])
        for cb in callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("Error in event callback for %s", event_type)

        # Broadcast to WebSocket clients
        await self._broadcast(message)

        return event

    async def connect(self, ws: WebSocket) -> str:
        """Accept a WebSocket connection, send history, and start tracking."""
        # Enforce connection limit
        if self.connected_count >= MAX_CONNECTIONS:
            await ws.close(code=1008, reason="Too many connections")
            raise ConnectionError("Connection limit reached")

        # Validate origin if configured
        if self._allowed_origins is not None:
            origin = (ws.headers.get("origin") or "").rstrip("/")
            if origin not in self._allowed_origins:
                await ws.close(code=1008, reason="Origin not allowed")
                raise ConnectionError(f"Rejected origin: {origin}")

        await ws.accept()
        client_id = str(uuid.uuid4())
        client = _ClientInfo(ws, client_id)

        async with self._lock:
            self._clients[client_id] = client

        # Send buffered history
        if self._history:
            history_msg = json.dumps(
                {"type": "history", "events": list(self._history)}, cls=_EventEncoder
            )
            try:
                await ws.send_text(history_msg)
            except Exception:
                logger.warning("Failed to send history to client %s", client_id)
                async with self._lock:
                    self._clients.pop(client_id, None)
                return client_id

        logger.info("Client %s connected (total: %d)", client_id, self.connected_count)
        return client_id

    async def disconnect(self, client_id: str) -> None:
        """Remove a client from tracking."""
        async with self._lock:
            self._clients.pop(client_id, None)
        logger.info("Client %s disconnected (total: %d)", client_id, self.connected_count)

    async def shutdown(self) -> None:
        """Close all WebSocket connections gracefully."""
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()

        for client in clients:
            try:
                await client.ws.close()
            except Exception:
                pass

        logger.info("EventBus shut down, closed %d connections", len(clients))

    async def _broadcast(self, message: str) -> None:
        """Send a message to all connected clients, removing dead ones."""
        async with self._lock:
            clients = list(self._clients.items())

        async def _send(client_id: str, client: _ClientInfo) -> str | None:
            try:
                await client.ws.send_text(message)
                return None
            except Exception:
                return client_id

        if clients:
            results = await asyncio.gather(*[_send(cid, c) for cid, c in clients])
            dead_ids = [cid for cid in results if cid is not None]

            if dead_ids:
                async with self._lock:
                    for cid in dead_ids:
                        self._clients.pop(cid, None)
                logger.info("Removed %d dead client(s)", len(dead_ids))

    @staticmethod
    def _validate_event_type(event_type: str) -> None:
        """Raise ValueError if event_type is not in the EventType enum."""
        if event_type not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"Unknown event type: {event_type!r}. Valid types: {sorted(_VALID_EVENT_TYPES)}"
            )


_VALID_EVENT_TYPES: frozenset[str] = frozenset(e.value for e in EventType)

# Module-level singleton
event_bus = EventBus()

"""Tests for the WebSocket event bus."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.event_bus import HISTORY_BUFFER_SIZE, EventBus, EventType

# ── Helpers ──────────────────────────────────────────────────────


def _make_mock_ws(*, fail_send: bool = False) -> MagicMock:
    """Create a mock WebSocket with async send_text."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    if fail_send:
        ws.send_text = AsyncMock(side_effect=Exception("connection lost"))
    else:
        ws.send_text = AsyncMock()
    return ws


async def _connect_mock_client(bus: EventBus, *, fail_send: bool = False) -> tuple[str, MagicMock]:
    """Connect a mock WebSocket client and return (client_id, mock_ws)."""
    ws = _make_mock_ws(fail_send=fail_send)
    client_id = await bus.connect(ws)
    return client_id, ws


# ── Unit Tests ───────────────────────────────────────────────────


class TestEmitBroadcast:
    """emit() broadcasts to all connected clients."""

    async def test_emit_sends_to_all_clients(self) -> None:
        bus = EventBus()
        _, ws1 = await _connect_mock_client(bus)
        _, ws2 = await _connect_mock_client(bus)

        await bus.emit("agent_speak", {"agent_id": "rex", "message": "hi", "emotion": "neutral"})

        # Each ws gets history (empty) + the emitted event
        assert ws1.send_text.call_count == 1
        assert ws2.send_text.call_count == 1

        payload = json.loads(ws1.send_text.call_args[0][0])
        assert payload["event_type"] == "agent_speak"
        assert payload["data"]["agent_id"] == "rex"

    async def test_emit_with_no_clients_does_not_error(self) -> None:
        bus = EventBus()
        event = await bus.emit("viewer_count", {"count": 42})
        assert event["event_type"] == "viewer_count"


class TestOnCallback:
    """on() registers and fires async callbacks."""

    async def test_callback_fires_with_correct_payload(self) -> None:
        bus = EventBus()
        received: list[dict] = []

        async def handler(event: dict[str, Any]) -> None:
            received.append(event)

        bus.on("budget_update", handler)
        await bus.emit("budget_update", {"daily_spend": 1.5, "daily_limit": 10.0, "per_agent": {}})

        assert len(received) == 1
        assert received[0]["data"]["daily_spend"] == 1.5

    async def test_multiple_callbacks_all_fire(self) -> None:
        bus = EventBus()
        calls: list[str] = []

        async def cb1(event: dict) -> None:
            calls.append("cb1")

        async def cb2(event: dict) -> None:
            calls.append("cb2")

        bus.on("agent_move", cb1)
        bus.on("agent_move", cb2)
        await bus.emit("agent_move", {"agent_id": "aurora", "target": "park", "x": 10, "y": 20})

        assert calls == ["cb1", "cb2"]

    async def test_erroring_callback_does_not_crash_emit(self) -> None:
        bus = EventBus()

        async def bad_handler(event: dict) -> None:
            raise RuntimeError("boom")

        bus.on("agent_action", bad_handler)
        # Should not raise
        event = await bus.emit(
            "agent_action", {"agent_id": "pixel", "action": "dance", "details": {}}
        )
        assert event["event_type"] == "agent_action"


class TestEventEnvelope:
    """Events include timestamp and event_id."""

    async def test_event_has_timestamp(self) -> None:
        bus = EventBus()
        event = await bus.emit("viewer_count", {"count": 0})
        assert isinstance(event["timestamp"], float)
        assert event["timestamp"] > 0

    async def test_event_has_uuid_event_id(self) -> None:
        bus = EventBus()
        event = await bus.emit("viewer_count", {"count": 0})
        # Should be a valid UUID string
        parsed = uuid.UUID(event["event_id"])
        assert str(parsed) == event["event_id"]


class TestJsonSerialization:
    """JSON serialization works for all event types including special types."""

    @pytest.mark.parametrize(
        "event_type,data",
        [
            ("agent_speak", {"agent_id": "rex", "message": "Ship it.", "emotion": "neutral"}),
            ("agent_move", {"agent_id": "aurora", "target": "park", "x": 100, "y": 200}),
            (
                "agent_action",
                {"agent_id": "pixel", "action": "research", "details": {"query": "AI"}},
            ),
            ("alpha_dispatch", {"from": "vera", "task": "fetch docs", "status": "pending"}),
            ("alpha_return", {"result": "done", "status": "success"}),
            ("management_warning", {"type": "language", "message": "watch it", "severity": 2}),
            (
                "management_intervention",
                {"type": "block", "message": "blocked", "agent_id": "grok"},
            ),
            ("world_expansion", {"chunk_id": "c1", "name": "Town Square", "built_by": "aurora"}),
            ("poll_created", {"poll_id": "p1", "title": "What next?", "options": ["A", "B"]}),
            ("poll_result", {"poll_id": "p1", "winner": "A", "votes": {"A": 10, "B": 5}}),
            ("budget_update", {"daily_spend": 1.23, "daily_limit": 10.0, "per_agent": {}}),
            ("viewer_count", {"count": 150}),
            ("tts_play", {"agent_id": "vera", "audio_url": "/audio/1.mp3", "duration": 3.5}),
            ("config_reloaded", {"reloaded_agents": ["rex", "vera"]}),
        ],
    )
    async def test_event_type_serializes(self, event_type: str, data: dict) -> None:
        bus = EventBus()
        _, ws = await _connect_mock_client(bus)
        await bus.emit(event_type, data)

        sent = ws.send_text.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["event_type"] == event_type
        assert parsed["data"] == data

    async def test_decimal_serialization(self) -> None:
        bus = EventBus()
        _, ws = await _connect_mock_client(bus)
        await bus.emit(
            "budget_update",
            {
                "daily_spend": Decimal("3.14"),
                "daily_limit": Decimal("10.00"),
                "per_agent": {},
            },
        )

        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["data"]["daily_spend"] == 3.14

    async def test_datetime_serialization(self) -> None:
        bus = EventBus()
        _, ws = await _connect_mock_client(bus)
        dt = datetime(2026, 1, 15, 12, 0, 0)
        await bus.emit(
            "agent_action",
            {
                "agent_id": "rex",
                "action": "build",
                "details": {"started_at": dt},
            },
        )

        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["data"]["details"]["started_at"] == "2026-01-15T12:00:00"

    async def test_uuid_serialization(self) -> None:
        bus = EventBus()
        _, ws = await _connect_mock_client(bus)
        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        await bus.emit(
            "poll_created",
            {
                "poll_id": uid,
                "title": "Test",
                "options": ["A"],
            },
        )

        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["data"]["poll_id"] == "12345678-1234-5678-1234-567812345678"


class TestDisconnectedClient:
    """Disconnected/erroring client is removed without crashing emit."""

    async def test_dead_client_removed_on_emit(self) -> None:
        bus = EventBus()
        _, good_ws = await _connect_mock_client(bus)
        _, bad_ws = await _connect_mock_client(bus, fail_send=True)

        assert bus.connected_count == 2
        await bus.emit("viewer_count", {"count": 1})

        # Bad client should have been removed
        assert bus.connected_count == 1
        # Good client still got the message
        assert good_ws.send_text.call_count == 1


class TestConnectionTracking:
    """connected_count tracks connections accurately."""

    async def test_count_increases_on_connect(self) -> None:
        bus = EventBus()
        assert bus.connected_count == 0
        await _connect_mock_client(bus)
        assert bus.connected_count == 1
        await _connect_mock_client(bus)
        assert bus.connected_count == 2

    async def test_count_decreases_on_disconnect(self) -> None:
        bus = EventBus()
        cid1, _ = await _connect_mock_client(bus)
        cid2, _ = await _connect_mock_client(bus)
        assert bus.connected_count == 2

        await bus.disconnect(cid1)
        assert bus.connected_count == 1

        await bus.disconnect(cid2)
        assert bus.connected_count == 0

    async def test_double_disconnect_does_not_error(self) -> None:
        bus = EventBus()
        cid, _ = await _connect_mock_client(bus)
        await bus.disconnect(cid)
        await bus.disconnect(cid)  # Should not raise
        assert bus.connected_count == 0


class TestHistoryBuffer:
    """Event history buffer stores last 50 events."""

    async def test_history_stored(self) -> None:
        bus = EventBus()
        for i in range(5):
            await bus.emit("viewer_count", {"count": i})
        assert len(bus._history) == 5

    async def test_history_drops_oldest_on_overflow(self) -> None:
        bus = EventBus()
        for i in range(HISTORY_BUFFER_SIZE + 10):
            await bus.emit("viewer_count", {"count": i})

        assert len(bus._history) == HISTORY_BUFFER_SIZE
        # Oldest should be count=10 (first 10 were dropped)
        assert bus._history[0]["data"]["count"] == 10

    async def test_new_client_receives_history(self) -> None:
        bus = EventBus()
        await bus.emit("agent_speak", {"agent_id": "rex", "message": "first", "emotion": "neutral"})
        await bus.emit("viewer_count", {"count": 42})

        _, ws = await _connect_mock_client(bus)

        # First call to send_text should be the history message
        history_call = ws.send_text.call_args_list[0]
        history_msg = json.loads(history_call[0][0])
        assert history_msg["type"] == "history"
        assert len(history_msg["events"]) == 2
        assert history_msg["events"][0]["event_type"] == "agent_speak"
        assert history_msg["events"][1]["event_type"] == "viewer_count"


class TestEventTypeValidation:
    """Unknown event types raise ValueError."""

    async def test_emit_unknown_type_raises(self) -> None:
        bus = EventBus()
        with pytest.raises(ValueError, match="Unknown event type"):
            await bus.emit("not_a_real_event", {})

    def test_on_unknown_type_raises(self) -> None:
        bus = EventBus()

        async def handler(event: dict) -> None:
            pass

        with pytest.raises(ValueError, match="Unknown event type"):
            bus.on("fake_event", handler)


class TestShutdown:
    """Shutdown closes all connections."""

    async def test_shutdown_closes_all(self) -> None:
        bus = EventBus()
        _, ws1 = await _connect_mock_client(bus)
        _, ws2 = await _connect_mock_client(bus)

        await bus.shutdown()

        assert bus.connected_count == 0
        ws1.close.assert_awaited_once()
        ws2.close.assert_awaited_once()


class TestEventTypeEnum:
    """EventType enum covers all required types."""

    def test_all_event_types_present(self) -> None:
        expected = {
            "agent_speak",
            "agent_move",
            "agent_action",
            "alpha_dispatch",
            "alpha_return",
            "management_warning",
            "management_intervention",
            "management_shadow",
            "world_expansion",
            "poll_created",
            "poll_result",
            "budget_update",
            "viewer_count",
            "tts_play",
            "tool_executed",
            "config_reloaded",
            "artifact_created",
            "conversation_productivity",
            "agi_progress",
            "task_delegated",
            "task_completed",
            "agent_spawn",
            "agent_despawn",
            "simulation_error",
            "bridge_perception",
            "bridge_action_result",
            "bridge_scene_update",
            "bridge_scene_digest",
            "distress_reported",
        }
        actual = {e.value for e in EventType}
        assert actual == expected


# ── Integration Tests ────────────────────────────────────────────


def _make_test_app() -> tuple:
    """Create a minimal FastAPI app with WebSocket endpoint and its own EventBus."""
    from fastapi import WebSocketDisconnect
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    from starlette.websockets import WebSocket

    bus = EventBus()

    async def ws_endpoint(websocket: WebSocket) -> None:
        client_id = await bus.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await bus.disconnect(client_id)

    test_app = Starlette(routes=[WebSocketRoute("/ws", ws_endpoint)])
    return test_app, bus


@pytest.mark.integration
class TestWebSocketIntegration:
    """Integration tests using Starlette TestClient with real WebSocket connections.

    These are sync tests because TestClient runs its own event loop in a thread.
    We use the TestClient's portal to schedule async work on that loop.
    """

    def test_client_connects_and_receives_event(self) -> None:
        from starlette.testclient import TestClient

        app, bus = _make_test_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws_conn:
                # Use the TestClient's internal portal to emit on the server's loop
                client.portal.call(
                    bus.emit,
                    "agent_speak",
                    {"agent_id": "rex", "message": "test", "emotion": "neutral"},
                )

                data = ws_conn.receive_json()
                assert data["event_type"] == "agent_speak"
                assert data["data"]["agent_id"] == "rex"

    def test_reconnecting_client_gets_history(self) -> None:
        from starlette.testclient import TestClient

        app, bus = _make_test_app()

        with TestClient(app) as client:
            # Pre-populate history via the server's event loop
            client.portal.call(bus.emit, "viewer_count", {"count": 1})
            client.portal.call(bus.emit, "viewer_count", {"count": 2})

            # Now connect — should receive history
            with client.websocket_connect("/ws") as ws_conn:
                data = ws_conn.receive_json()
                assert data["type"] == "history"
                assert len(data["events"]) == 2
                assert data["events"][0]["data"]["count"] == 1
                assert data["events"][1]["data"]["count"] == 2

    def test_multiple_clients_receive_broadcast(self) -> None:
        from starlette.testclient import TestClient

        app, bus = _make_test_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws1:
                with client.websocket_connect("/ws") as ws2:
                    client.portal.call(bus.emit, "viewer_count", {"count": 77})

                    d1 = ws1.receive_json()
                    d2 = ws2.receive_json()
                    assert d1["event_type"] == "viewer_count"
                    assert d2["event_type"] == "viewer_count"
                    assert d1["data"]["count"] == 77

    def test_client_disconnect_handled_gracefully(self) -> None:
        from starlette.testclient import TestClient

        app, bus = _make_test_app()

        with TestClient(app) as client:
            with client.websocket_connect("/ws"):
                pass  # connection closes on context exit

            # After disconnect, emitting should still work
            client.portal.call(bus.emit, "viewer_count", {"count": 0})
            # No exception means success


# ── Resilience Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bad_callback_does_not_crash_other_callbacks():
    """An exception in one callback should not prevent others from running."""
    bus = EventBus()
    results = []

    async def good_callback(event: dict) -> None:
        results.append("good")

    async def bad_callback(event: dict) -> None:
        raise RuntimeError("boom")

    bus.on(EventType.AGENT_SPEAK, bad_callback)
    bus.on(EventType.AGENT_SPEAK, good_callback)

    await bus.emit(EventType.AGENT_SPEAK, {"agent_id": "vera", "text": "hi"})

    # good_callback should still have run despite bad_callback raising
    assert "good" in results


@pytest.mark.asyncio
async def test_history_buffer_overflow():
    """Emitting more than HISTORY_BUFFER_SIZE events should drop oldest."""
    bus = EventBus()

    for i in range(HISTORY_BUFFER_SIZE + 10):
        await bus.emit(EventType.AGENT_SPEAK, {"agent_id": "vera", "seq": i})

    # Access internal history buffer (deque with maxlen=HISTORY_BUFFER_SIZE)
    history = list(bus._history)
    assert len(history) == HISTORY_BUFFER_SIZE
    # Oldest events should have been dropped
    first_seq = history[0]["data"]["seq"]
    assert first_seq == 10, f"Expected oldest seq=10, got {first_seq}"


@pytest.mark.asyncio
async def test_emit_agent_move_with_no_clients():
    """Emitting with zero connected clients should silently succeed."""
    bus = EventBus()
    event = await bus.emit(EventType.AGENT_MOVE, {"agent_id": "rex", "x": 5, "y": 10})
    assert event["event_type"] == EventType.AGENT_MOVE


@pytest.mark.asyncio
async def test_failed_send_removes_client():
    """A client that fails on send_text should be removed from active clients."""
    bus = EventBus()
    ws = _make_mock_ws(fail_send=True)
    ws.headers = MagicMock()
    ws.headers.get = MagicMock(return_value=None)

    await bus.connect(ws)
    assert bus.connected_count == 1

    # Emit should trigger send which fails — client should be cleaned up
    await bus.emit(EventType.AGENT_SPEAK, {"agent_id": "vera", "text": "test"})

    # After failed send, client should be disconnected
    assert bus.connected_count == 0

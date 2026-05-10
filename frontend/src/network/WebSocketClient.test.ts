import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DEFAULT_WS_URL, resolveWebSocketUrl, WebSocketClient } from "./WebSocketClient";
import type { ServerEvent } from "../types/events";
import { EventType } from "../types/events";

// Mock WebSocket
class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  readyState: number = 0; // CONNECTING
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
    this.readyState = 3; // CLOSED
  }

  simulateOpen(): void {
    this.readyState = 1; // OPEN
    this.onopen?.();
  }

  simulateMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose(): void {
    this.readyState = 3;
    this.onclose?.();
  }

  simulateError(): void {
    this.onerror?.();
  }

  // Static constants matching real WebSocket
  static OPEN = 1;
  static CLOSED = 3;
}

// Apply mock before each test
beforeEach(() => {
  MockWebSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", MockWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("WebSocketClient", () => {
  it("defaults to the backend websocket on port 8010", () => {
    const client = new WebSocketClient();
    client.connect();

    expect(DEFAULT_WS_URL).toBe("ws://localhost:8010/ws");
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toBe("ws://localhost:8010/ws");
    client.disconnect();
  });

  it("resolves a missing env URL to the backend websocket default", () => {
    expect(resolveWebSocketUrl(undefined)).toBe("ws://localhost:8010/ws");
    expect(resolveWebSocketUrl("ws://test:8000/ws")).toBe("ws://test:8000/ws");
  });

  it("connects to the given URL", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    client.connect();

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toBe("ws://test:8000/ws");
    client.disconnect();
  });

  it("reports connected state when open", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    expect(client.connected).toBe(false);

    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    expect(client.connected).toBe(true);

    client.disconnect();
    expect(client.connected).toBe(false);
  });

  it("dispatches events to registered callbacks", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const received: ServerEvent[] = [];
    client.onEvent((e) => received.push(e));

    client.connect();
    MockWebSocket.instances[0].simulateOpen();

    const event: ServerEvent = {
      event_id: "abc-123",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello" },
    };
    MockWebSocket.instances[0].simulateMessage(event);

    expect(received).toHaveLength(1);
    expect(received[0].event_type).toBe(EventType.AGENT_SPEAK);
    client.disconnect();
  });

  it("handles history batch from backend", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const received: ServerEvent[] = [];
    client.onEvent((e) => received.push(e));

    client.connect();
    MockWebSocket.instances[0].simulateOpen();

    const historyBatch = {
      type: "history",
      events: [
        {
          event_id: "1",
          event_type: EventType.BUDGET_UPDATE,
          timestamp: 1000,
          data: { total_spent: 5.0 },
        },
        {
          event_id: "2",
          event_type: EventType.VIEWER_COUNT,
          timestamp: 1001,
          data: { count: 42 },
        },
      ],
    };
    MockWebSocket.instances[0].simulateMessage(historyBatch);

    expect(received).toHaveLength(2);
    client.disconnect();
  });

  it("deduplicates history on reconnect — skips events already seen", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const received: ServerEvent[] = [];
    client.onEvent((e) => received.push(e));

    // First connection: receive two live events
    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateMessage({
      event_id: "1",
      event_type: EventType.BUDGET_UPDATE,
      timestamp: 1000,
      data: { total_spent: 1.0 },
    });
    MockWebSocket.instances[0].simulateMessage({
      event_id: "2",
      event_type: EventType.VIEWER_COUNT,
      timestamp: 1001,
      data: { count: 10 },
    });
    expect(received).toHaveLength(2);

    // Connection drops and reconnects
    MockWebSocket.instances[0].simulateClose();
    vi.advanceTimersByTime(1000);
    MockWebSocket.instances[1].simulateOpen();

    // Backend replays its buffer: events 1 & 2 (already seen) + event 3 (new)
    MockWebSocket.instances[1].simulateMessage({
      type: "history",
      events: [
        { event_id: "1", event_type: EventType.BUDGET_UPDATE, timestamp: 1000, data: { total_spent: 1.0 } },
        { event_id: "2", event_type: EventType.VIEWER_COUNT,  timestamp: 1001, data: { count: 10 } },
        { event_id: "3", event_type: EventType.AGENT_SPEAK,   timestamp: 1002, data: { agent_id: "vera", text: "hi" } },
      ],
    });

    // Only event 3 should be dispatched — events 1 & 2 are filtered out
    expect(received).toHaveLength(3);
    expect(received[2].event_id).toBe("3");
    client.disconnect();
  });

  it("unsubscribes callback when dispose function is called", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const received: ServerEvent[] = [];
    const unsubscribe = client.onEvent((e) => received.push(e));

    client.connect();
    MockWebSocket.instances[0].simulateOpen();

    const event: ServerEvent = {
      event_id: "1",
      event_type: EventType.AGENT_MOVE,
      timestamp: Date.now(),
      data: {},
    };
    MockWebSocket.instances[0].simulateMessage(event);
    expect(received).toHaveLength(1);

    unsubscribe();
    MockWebSocket.instances[0].simulateMessage(event);
    expect(received).toHaveLength(1); // no new events
    client.disconnect();
  });

  it("disconnects cleanly", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    client.connect();
    const ws = MockWebSocket.instances[0];
    ws.simulateOpen();

    client.disconnect();
    expect(ws.closed).toBe(true);
  });
});

describe("WebSocketClient reconnection", () => {
  it("reconnects with exponential backoff after close", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    client.connect();
    expect(MockWebSocket.instances).toHaveLength(1);

    // Simulate connection loss
    MockWebSocket.instances[0].simulateClose();

    // After 1s (initial backoff), should reconnect
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2);

    // Second close — backoff doubles to 2s
    MockWebSocket.instances[1].simulateClose();
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2); // not yet
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(3);

    // Third close — backoff doubles to 4s
    MockWebSocket.instances[2].simulateClose();
    vi.advanceTimersByTime(3000);
    expect(MockWebSocket.instances).toHaveLength(3); // not yet
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(4);

    client.disconnect();
  });

  it("resets backoff on successful connection", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    client.connect();

    // Fail twice to increase backoff
    MockWebSocket.instances[0].simulateClose();
    vi.advanceTimersByTime(1000);
    MockWebSocket.instances[1].simulateClose();
    vi.advanceTimersByTime(2000);

    // Now succeed
    MockWebSocket.instances[2].simulateOpen();
    // Backoff should reset to 1s
    expect(client.currentBackoff).toBe(1000);

    client.disconnect();
  });

  it("caps backoff at 30 seconds", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    client.connect();

    // Fail many times: 1s, 2s, 4s, 8s, 16s, 32s -> capped at 30s
    for (let i = 0; i < 6; i++) {
      MockWebSocket.instances[i].simulateClose();
      vi.advanceTimersByTime(30000);
    }

    // After 6 failures the backoff should be capped at 30s
    expect(client.currentBackoff).toBe(30000);
    client.disconnect();
  });

  it("does not reconnect after explicit disconnect", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    client.connect();
    client.disconnect();

    // Even after waiting, no new connection
    vi.advanceTimersByTime(60000);
    expect(MockWebSocket.instances).toHaveLength(1);
  });
});

describe("WebSocketClient lifecycle callbacks", () => {
  it("fires onConnect when connection opens", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const onConnect = vi.fn();
    client.onConnect = onConnect;

    client.connect();
    expect(onConnect).not.toHaveBeenCalled();

    MockWebSocket.instances[0].simulateOpen();
    expect(onConnect).toHaveBeenCalledTimes(1);
    client.disconnect();
  });

  it("fires onDisconnect when connection closes", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const onDisconnect = vi.fn();
    client.onDisconnect = onDisconnect;

    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    expect(onDisconnect).not.toHaveBeenCalled();

    MockWebSocket.instances[0].simulateClose();
    expect(onDisconnect).toHaveBeenCalledTimes(1);
    client.disconnect();
  });

  it("fires onDisconnect before scheduling reconnect", () => {
    const client = new WebSocketClient("ws://test:8000/ws");
    const callOrder: string[] = [];
    client.onDisconnect = () => callOrder.push("disconnect");

    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    MockWebSocket.instances[0].simulateClose();

    // onDisconnect fires, then reconnect is scheduled (not immediate)
    expect(callOrder).toEqual(["disconnect"]);
    expect(MockWebSocket.instances).toHaveLength(1); // reconnect not yet

    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances).toHaveLength(2); // now reconnected
    client.disconnect();
  });
});

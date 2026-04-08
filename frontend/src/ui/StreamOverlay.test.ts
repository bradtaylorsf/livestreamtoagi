// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { StreamOverlay, _resetOverlayStyles } from "./StreamOverlay";
import { EventType } from "../types/events";

function createMockWsClient() {
  const callbacks: Array<(event: any) => void> = [];
  return {
    onEvent: vi.fn((cb: (event: any) => void) => {
      callbacks.push(cb);
      return () => {
        const idx = callbacks.indexOf(cb);
        if (idx >= 0) callbacks.splice(idx, 1);
      };
    }),
    emit: (event: any) => {
      for (const cb of callbacks) cb(event);
    },
  };
}

describe("StreamOverlay", () => {
  let wsClient: ReturnType<typeof createMockWsClient>;
  let overlay: StreamOverlay;

  beforeEach(() => {
    _resetOverlayStyles();
    document.body.innerHTML = '<div id="game"></div>';
    wsClient = createMockWsClient();
    overlay = new StreamOverlay(wsClient as any);
  });

  afterEach(() => {
    overlay.destroy();
    document.body.innerHTML = "";
  });

  it("creates container in #game", () => {
    const container = document.getElementById("stream-overlay");
    expect(container).not.toBeNull();
    expect(container!.parentElement!.id).toBe("game");
  });

  it("has top bar and sidebar", () => {
    const container = overlay.getContainer();
    expect(container.querySelector(".overlay-top-bar")).not.toBeNull();
    expect(container.querySelector(".overlay-right-sidebar")).not.toBeNull();
  });

  it("subscribes to WebSocket events", () => {
    expect(wsClient.onEvent).toHaveBeenCalledTimes(1);
  });

  it("routes BUDGET_UPDATE to BudgetTicker", () => {
    wsClient.emit({
      event_id: "1",
      event_type: EventType.BUDGET_UPDATE,
      timestamp: Date.now(),
      data: { total_spent: 75.5, daily_limit: 150 },
    });
    expect(overlay.getBudgetTicker().getElement().textContent).toContain("$75.50");
  });

  it("routes VIEWER_COUNT to ViewerCount", () => {
    wsClient.emit({
      event_id: "2",
      event_type: EventType.VIEWER_COUNT,
      timestamp: Date.now(),
      data: { count: 420 },
    });
    expect(overlay.getViewerCount().getElement().textContent).toContain("420");
  });

  it("routes AGENT_SPEAK to AgentStatusPanel as talking", () => {
    wsClient.emit({
      event_id: "3",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello" },
    });
    expect(overlay.getAgentStatusPanel().getStatus("vera")).toBe("talking");
  });

  it("routes AGENT_ACTION building to AgentStatusPanel", () => {
    wsClient.emit({
      event_id: "4",
      event_type: EventType.AGENT_ACTION,
      timestamp: Date.now(),
      data: { agent_id: "rex", action: "building" },
    });
    expect(overlay.getAgentStatusPanel().getStatus("rex")).toBe("building");
  });

  it("routes AGENT_ACTION non-building to idle", () => {
    wsClient.emit({
      event_id: "5",
      event_type: EventType.AGENT_ACTION,
      timestamp: Date.now(),
      data: { agent_id: "rex", action: "thinking" },
    });
    expect(overlay.getAgentStatusPanel().getStatus("rex")).toBe("idle");
  });

  it("updates topic from AGENT_SPEAK with topic field", () => {
    wsClient.emit({
      event_id: "6",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello", topic: "Budget planning" },
    });
    expect(overlay.getTopicDisplay().getElement().textContent).toContain("Budget planning");
  });

  it("works without WebSocket client", () => {
    const noWs = new StreamOverlay(null);
    expect(noWs.getContainer()).toBeInstanceOf(HTMLDivElement);
    noWs.destroy();
  });

  it("cleans up on destroy", () => {
    overlay.destroy();
    expect(document.getElementById("stream-overlay")).toBeNull();
  });
});

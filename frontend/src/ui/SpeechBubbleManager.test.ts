// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SpeechBubbleManager, _resetStyles } from "./SpeechBubbleManager";
import { EventType } from "../types/events";

function createMockScene() {
  return {
    cameras: {
      main: {
        width: 1280,
        height: 720,
        worldView: { x: 0, y: 0, width: 1280, height: 720 },
      },
    },
  };
}

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

function createMockAgentSpriteManager() {
  const sprites: Record<string, any> = {
    vera: { getPosition: () => ({ x: 112, y: 192 }) },
    rex: { getPosition: () => ({ x: 112, y: 512 }) },
    alpha: { getPosition: () => ({ x: 144, y: 224 }) },
  };
  return {
    getSprite: vi.fn((id: string) => sprites[id]),
  };
}

describe("SpeechBubbleManager", () => {
  let scene: ReturnType<typeof createMockScene>;
  let wsClient: ReturnType<typeof createMockWsClient>;
  let agentSpriteManager: ReturnType<typeof createMockAgentSpriteManager>;
  let manager: SpeechBubbleManager;

  beforeEach(() => {
    vi.useFakeTimers();
    _resetStyles();
    document.body.innerHTML = '<div id="game"></div>';
    scene = createMockScene();
    wsClient = createMockWsClient();
    agentSpriteManager = createMockAgentSpriteManager();
    manager = new SpeechBubbleManager(
      scene as any,
      wsClient as any,
      agentSpriteManager as any,
    );
  });

  afterEach(() => {
    manager.destroy();
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("creates container element in #game", () => {
    const container = document.getElementById("speech-bubbles");
    expect(container).not.toBeNull();
    expect(container!.parentElement!.id).toBe("game");
  });

  it("subscribes to WebSocket events", () => {
    expect(wsClient.onEvent).toHaveBeenCalledTimes(1);
  });

  it("creates bubble on showBubble()", () => {
    manager.showBubble("vera", "Hello!");
    expect(manager.getActiveBubbleCount()).toBe(1);
    expect(manager.getBubble("vera")).toBeDefined();
  });

  it("skips management agent", () => {
    manager.showBubble("management", "Filtered content.");
    expect(manager.getActiveBubbleCount()).toBe(0);
    expect(manager.getBubble("management")).toBeUndefined();
  });

  it("replaces existing bubble for same agent", () => {
    manager.showBubble("vera", "First message");
    const firstBubble = manager.getBubble("vera");
    manager.showBubble("vera", "Second message");
    const secondBubble = manager.getBubble("vera");
    expect(secondBubble).not.toBe(firstBubble);
    expect(manager.getActiveBubbleCount()).toBe(1);
  });

  it("tracks multiple agents simultaneously", () => {
    manager.showBubble("vera", "Hello");
    manager.showBubble("rex", "Hi there");
    expect(manager.getActiveBubbleCount()).toBe(2);
  });

  it("handles agent_speak WebSocket event", () => {
    wsClient.emit({
      event_id: "1",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello from WS" },
    });
    expect(manager.getActiveBubbleCount()).toBe(1);
    expect(manager.getBubble("vera")).toBeDefined();
  });

  it("uses tone from event data", () => {
    wsClient.emit({
      event_id: "2",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Watch out!", tone: "urgent" },
    });
    const bubble = manager.getBubble("vera");
    expect(bubble!.getElement().classList.contains("bubble-urgent")).toBe(true);
  });

  it("defaults to casual tone", () => {
    manager.showBubble("vera", "Hello");
    const bubble = manager.getBubble("vera");
    expect(bubble!.getElement().classList.contains("bubble-casual")).toBe(true);
  });

  it("ignores non-speak events", () => {
    wsClient.emit({
      event_id: "3",
      event_type: EventType.AGENT_MOVE,
      timestamp: Date.now(),
      data: { agent_id: "vera", to: { x: 300, y: 400 } },
    });
    expect(manager.getActiveBubbleCount()).toBe(0);
  });

  describe("update()", () => {
    it("updates bubble position from sprite position", () => {
      manager.showBubble("vera", "Hello");
      manager.update();
      const bubble = manager.getBubble("vera");
      // With no camera offset, screen coords should match world coords (+ offset)
      expect(bubble!.getElement().style.left).toBe("112px");
      // y = 192 + (-40) offset = 152
      expect(bubble!.getElement().style.top).toBe("152px");
    });

    it("removes dismissed bubbles during update", () => {
      manager.showBubble("vera", "Hello", "casual", 1000);
      vi.advanceTimersByTime(1000); // dismiss triggers
      manager.update();
      expect(manager.getActiveBubbleCount()).toBe(0);
    });
  });

  it("creates alpha bubble with emoji treatment", () => {
    manager.showBubble("alpha", "Go fetch the package");
    const bubble = manager.getBubble("alpha");
    expect(bubble).toBeDefined();
    expect(bubble!.getElement().classList.contains("bubble-alpha")).toBe(true);
  });

  it("works without WebSocket client", () => {
    const mgr = new SpeechBubbleManager(
      scene as any,
      null,
      agentSpriteManager as any,
    );
    mgr.showBubble("vera", "Hello");
    expect(mgr.getActiveBubbleCount()).toBe(1);
    mgr.destroy();
  });

  it("cleans up on destroy", () => {
    manager.showBubble("vera", "Hello");
    manager.showBubble("rex", "Hi");
    manager.destroy();
    expect(manager.getActiveBubbleCount()).toBe(0);
    expect(document.getElementById("speech-bubbles")).toBeNull();
  });
});

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { OverlayManager, _resetOverlayManagerStyles } from "./OverlayManager";
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

describe("OverlayManager", () => {
  let wsClient: ReturnType<typeof createMockWsClient>;
  let overlay: OverlayManager;
  let gameDiv: HTMLDivElement;

  beforeEach(() => {
    _resetOverlayManagerStyles();
    gameDiv = document.createElement("div");
    gameDiv.id = "game";
    document.body.appendChild(gameDiv);

    wsClient = createMockWsClient();
    overlay = new OverlayManager(wsClient as any);
  });

  afterEach(() => {
    overlay.destroy();
    gameDiv.remove();
    // Clean up injected styles
    document.getElementById("overlay-manager-styles")?.remove();
  });

  it("creates container element", () => {
    const container = overlay.getContainer();
    expect(container.id).toBe("overlay-manager");
  });

  it("appends container to game div", () => {
    expect(gameDiv.querySelector("#overlay-manager")).toBeTruthy();
  });

  it("subscribes to WebSocket events", () => {
    expect(wsClient.onEvent).toHaveBeenCalledTimes(1);
  });

  describe("POLL_CREATED", () => {
    it("shows poll card with question and options", () => {
      wsClient.emit({
        event_id: "1",
        event_type: EventType.POLL_CREATED,
        timestamp: Date.now(),
        data: {
          poll_id: "p1",
          question: "What should we build?",
          options: ["Game", "Tool", "Website"],
        },
      });

      const container = overlay.getContainer();
      const pollQuestion = container.querySelector(".overlay-poll-question");
      expect(pollQuestion?.textContent).toBe("What should we build?");

      const options = container.querySelectorAll(".overlay-poll-option");
      expect(options).toHaveLength(3);
      expect(options[0].textContent).toBe("Game");
      expect(options[1].textContent).toBe("Tool");
      expect(options[2].textContent).toBe("Website");
    });

    it("replaces existing poll on new POLL_CREATED", () => {
      wsClient.emit({
        event_id: "1",
        event_type: EventType.POLL_CREATED,
        timestamp: Date.now(),
        data: { poll_id: "p1", question: "First?", options: ["A"] },
      });

      wsClient.emit({
        event_id: "2",
        event_type: EventType.POLL_CREATED,
        timestamp: Date.now(),
        data: { poll_id: "p2", question: "Second?", options: ["B"] },
      });

      const polls = overlay.getContainer().querySelectorAll(".overlay-poll");
      expect(polls).toHaveLength(1);
      expect(polls[0].querySelector(".overlay-poll-question")?.textContent).toBe("Second?");
    });
  });

  describe("POLL_RESULT", () => {
    it("shows results with vote bars and winner", () => {
      wsClient.emit({
        event_id: "2",
        event_type: EventType.POLL_RESULT,
        timestamp: Date.now(),
        data: {
          poll_id: "p1",
          results: { Game: 10, Tool: 5, Website: 3 },
          winner: "Game",
        },
      });

      const container = overlay.getContainer();
      const header = container.querySelector(".overlay-poll-question");
      expect(header?.textContent).toBe("Poll Results");

      const winnerRow = container.querySelector(".overlay-poll-winner");
      expect(winnerRow).toBeTruthy();
    });
  });

  describe("ARTIFACT_CREATED", () => {
    it("shows toast notification with artifact name", () => {
      wsClient.emit({
        event_id: "3",
        event_type: EventType.ARTIFACT_CREATED,
        timestamp: Date.now(),
        data: {
          agent_id: "rex",
          artifact_type: "code",
          name: "calculator.py",
        },
      });

      const toasts = overlay.getContainer().querySelectorAll(".overlay-toast");
      expect(toasts).toHaveLength(1);
      expect(toasts[0].textContent).toContain("calculator.py");
      expect(toasts[0].textContent).toContain("rex");
    });

    it("stacks multiple toasts", () => {
      wsClient.emit({
        event_id: "3",
        event_type: EventType.ARTIFACT_CREATED,
        timestamp: Date.now(),
        data: { agent_id: "rex", artifact_type: "code", name: "a.py" },
      });
      wsClient.emit({
        event_id: "4",
        event_type: EventType.ARTIFACT_CREATED,
        timestamp: Date.now(),
        data: { agent_id: "aurora", artifact_type: "design", name: "mockup.png" },
      });

      const toasts = overlay.getContainer().querySelectorAll(".overlay-toast");
      expect(toasts).toHaveLength(2);
    });
  });

  it("cleans up on destroy", () => {
    overlay.destroy();
    expect(gameDiv.querySelector("#overlay-manager")).toBeNull();
  });

  it("works without WebSocket client", () => {
    const noWsOverlay = new OverlayManager(null);
    expect(noWsOverlay.getContainer()).toBeDefined();
    noWsOverlay.destroy();
  });
});

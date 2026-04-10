// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ManagementEffects } from "./ManagementEffects";
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

describe("ManagementEffects", () => {
  let wsClient: ReturnType<typeof createMockWsClient>;
  let effects: ManagementEffects;
  let gameDiv: HTMLDivElement;

  beforeEach(() => {
    // Create a #game container for the effects to attach to
    gameDiv = document.createElement("div");
    gameDiv.id = "game";
    document.body.appendChild(gameDiv);

    wsClient = createMockWsClient();
    effects = new ManagementEffects(wsClient as any);
  });

  afterEach(() => {
    effects.destroy();
    gameDiv.remove();
    // Clean up injected styles
    document.getElementById("management-effects-styles")?.remove();
  });

  it("registers WebSocket event handler", () => {
    expect(wsClient.onEvent).toHaveBeenCalledTimes(1);
  });

  it("attaches container to #game element", () => {
    const container = gameDiv.querySelector(".management-container");
    expect(container).not.toBeNull();
  });

  // ── Level 1: Notice (screen flash) ──────────────────────────

  describe("Level 1 (notice)", () => {
    it("creates a flash overlay", () => {
      effects.triggerEffect(1);
      const overlay = gameDiv.querySelector(".management-flash");
      expect(overlay).not.toBeNull();
    });

    it("sets active level to 1", () => {
      effects.triggerEffect(1);
      expect(effects.getActiveLevel()).toBe(1);
    });

    it("auto-dismisses after 500ms", () => {
      vi.useFakeTimers();
      effects.triggerEffect(1);
      expect(effects.getActiveLevel()).toBe(1);
      vi.advanceTimersByTime(500);
      expect(effects.getActiveLevel()).toBeNull();
      vi.useRealTimers();
    });
  });

  // ── Level 2: Warning (dim + text + eye) ─────────────────────

  describe("Level 2 (warning)", () => {
    it("creates a dim overlay with warning text", () => {
      effects.triggerEffect(2);
      const overlay = gameDiv.querySelector(".management-dim");
      expect(overlay).not.toBeNull();
      const text = overlay!.querySelector(".management-text");
      expect(text).not.toBeNull();
      expect(text!.textContent).toBe("MANAGEMENT HAS NOTED THIS INTERACTION.");
    });

    it("shows eye icon", () => {
      effects.triggerEffect(2);
      const eye = gameDiv.querySelector(".management-eye");
      expect(eye).not.toBeNull();
    });

    it("applies glitch effect to text", () => {
      effects.triggerEffect(2);
      const text = gameDiv.querySelector(".management-text");
      expect(text!.classList.contains("management-glitch")).toBe(true);
    });

    it("auto-dismisses after 3000ms", () => {
      vi.useFakeTimers();
      effects.triggerEffect(2);
      expect(effects.getActiveLevel()).toBe(2);
      vi.advanceTimersByTime(3000);
      expect(effects.getActiveLevel()).toBeNull();
      vi.useRealTimers();
    });
  });

  // ── Level 3: Intervention (content blocked + audio) ─────────

  describe("Level 3 (intervention)", () => {
    it("creates a block overlay with content review text", () => {
      effects.triggerEffect(3);
      const overlay = gameDiv.querySelector(".management-block");
      expect(overlay).not.toBeNull();
      const text = overlay!.querySelector(".management-text");
      expect(text!.textContent).toBe("CONTENT REVIEW IN PROGRESS");
    });

    it("shows eye icon", () => {
      effects.triggerEffect(3);
      const eye = gameDiv.querySelector(".management-eye");
      expect(eye).not.toBeNull();
    });

    it("auto-dismisses after 5000ms", () => {
      vi.useFakeTimers();
      effects.triggerEffect(3);
      vi.advanceTimersByTime(5000);
      expect(effects.getActiveLevel()).toBeNull();
      vi.useRealTimers();
    });
  });

  // ── Level 4: Broadcast interruption ─────────────────────────

  describe("Level 4 (broadcast interruption)", () => {
    it("creates a fullscreen overlay", () => {
      effects.triggerEffect(4);
      const overlay = gameDiv.querySelector(".management-fullscreen");
      expect(overlay).not.toBeNull();
    });

    it("displays Management message when provided", () => {
      effects.triggerEffect(4, { message: "Test broadcast message" });
      const text = gameDiv.querySelector(".management-text");
      expect(text!.textContent).toBe("Test broadcast message");
    });

    it("uses default message when none provided", () => {
      effects.triggerEffect(4);
      const text = gameDiv.querySelector(".management-text");
      expect(text!.textContent).toBe("MANAGEMENT IS ADDRESSING THE AUDIENCE.");
    });

    it("shows large eye icon", () => {
      effects.triggerEffect(4);
      const eye = gameDiv.querySelector(".management-eye-large");
      expect(eye).not.toBeNull();
    });

    it("blocks pointer events", () => {
      effects.triggerEffect(4);
      const overlay = gameDiv.querySelector(".management-fullscreen") as HTMLDivElement;
      expect(overlay.style.pointerEvents).toBe("auto");
    });

    it("does NOT auto-dismiss (stays until cleared)", () => {
      vi.useFakeTimers();
      effects.triggerEffect(4);
      vi.advanceTimersByTime(60000);
      expect(effects.getActiveLevel()).toBe(4);
      vi.useRealTimers();
    });
  });

  // ── Level 5: Emergency (maintenance screen) ─────────────────

  describe("Level 5 (emergency)", () => {
    it("creates an emergency overlay", () => {
      effects.triggerEffect(5);
      const overlay = gameDiv.querySelector(".management-emergency");
      expect(overlay).not.toBeNull();
    });

    it("displays maintenance text", () => {
      effects.triggerEffect(5);
      const text = gameDiv.querySelector(".management-text");
      expect(text!.textContent).toBe("BROADCAST SUSPENDED. PLEASE STAND BY.");
    });

    it("blocks pointer events (blocks interaction)", () => {
      effects.triggerEffect(5);
      const overlay = gameDiv.querySelector(".management-emergency") as HTMLDivElement;
      expect(overlay.style.pointerEvents).toBe("auto");
    });

    it("does NOT auto-dismiss", () => {
      vi.useFakeTimers();
      effects.triggerEffect(5);
      vi.advanceTimersByTime(60000);
      expect(effects.getActiveLevel()).toBe(5);
      vi.useRealTimers();
    });
  });

  // ── clearEffect ─────────────────────────────────────────────

  describe("clearEffect", () => {
    it("removes overlay DOM nodes", () => {
      effects.triggerEffect(3);
      expect(gameDiv.querySelector(".management-overlay")).not.toBeNull();
      effects.clearEffect();
      expect(gameDiv.querySelector(".management-overlay")).toBeNull();
    });

    it("removes eye icon", () => {
      effects.triggerEffect(2);
      expect(gameDiv.querySelector(".management-eye")).not.toBeNull();
      effects.clearEffect();
      expect(gameDiv.querySelector(".management-eye")).toBeNull();
    });

    it("resets active level to null", () => {
      effects.triggerEffect(3);
      effects.clearEffect();
      expect(effects.getActiveLevel()).toBeNull();
    });
  });

  // ── WebSocket event integration ─────────────────────────────

  describe("WebSocket event handling", () => {
    it("triggers effect on management_warning event", () => {
      wsClient.emit({
        event_id: "1",
        event_type: EventType.MANAGEMENT_WARNING,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "tone", severity: 2 },
      });
      expect(effects.getActiveLevel()).toBe(2);
    });

    it("defaults to level 1 for warning without severity", () => {
      wsClient.emit({
        event_id: "2",
        event_type: EventType.MANAGEMENT_WARNING,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "tone" },
      });
      expect(effects.getActiveLevel()).toBe(1);
    });

    it("triggers effect on management_intervention event", () => {
      wsClient.emit({
        event_id: "3",
        event_type: EventType.MANAGEMENT_INTERVENTION,
        timestamp: Date.now(),
        data: {
          agent_id: "vera",
          action: "filter",
          original_text: "bad",
          filtered_text: "good",
          severity: 4,
          message: "Attention viewers.",
        },
      });
      expect(effects.getActiveLevel()).toBe(4);
    });

    it("defaults to level 3 for intervention without severity", () => {
      wsClient.emit({
        event_id: "4",
        event_type: EventType.MANAGEMENT_INTERVENTION,
        timestamp: Date.now(),
        data: { agent_id: "vera", action: "filter", original_text: "a", filtered_text: "b" },
      });
      expect(effects.getActiveLevel()).toBe(3);
    });
  });

  // ── Effect replacement ──────────────────────────────────────

  it("clears previous effect when triggering a new one", () => {
    effects.triggerEffect(2);
    expect(gameDiv.querySelectorAll(".management-overlay").length).toBe(1);
    effects.triggerEffect(3);
    expect(gameDiv.querySelectorAll(".management-overlay").length).toBe(1);
    expect(effects.getActiveLevel()).toBe(3);
  });

  // ── destroy ─────────────────────────────────────────────────

  it("cleans up all DOM elements on destroy", () => {
    effects.triggerEffect(3);
    effects.destroy();
    expect(gameDiv.querySelector(".management-container")).toBeNull();
  });
});

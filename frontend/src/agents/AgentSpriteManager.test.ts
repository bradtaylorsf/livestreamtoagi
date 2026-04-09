import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentSpriteManager } from "./AgentSpriteManager";
import { EventType } from "../types/events";

function createMockScene() {
  return {
    add: {
      sprite: vi.fn((_x: number, _y: number, _key: string) => ({
        x: _x,
        y: _y,
        height: 32,
        setOrigin: vi.fn(),
        setDepth: vi.fn(),
        setFrame: vi.fn(),
        play: vi.fn(),
        setScale: vi.fn(),
        anims: { exists: vi.fn(() => false) },
        destroy: vi.fn(),
      })),
      text: vi.fn(
        (_x: number, _y: number, _text: string, _style?: object) => ({
          x: _x,
          y: _y,
          width: 40,
          visible: false,
          setOrigin: vi.fn(),
          setDepth: vi.fn(),
          setVisible: vi.fn(function (this: any, v: boolean) {
            this.visible = v;
            return this;
          }),
          setText: vi.fn(),
          setAlpha: vi.fn(),
          destroy: vi.fn(),
        }),
      ),
      graphics: vi.fn(() => ({
        setDepth: vi.fn(),
        setAlpha: vi.fn(),
        clear: vi.fn(),
        fillStyle: vi.fn(),
        fillCircle: vi.fn(),
        destroy: vi.fn(),
      })),
    },
    tweens: {
      add: vi.fn(() => ({
        stop: vi.fn(),
      })),
    },
    time: {
      delayedCall: vi.fn(),
      addEvent: vi.fn(() => ({
        destroy: vi.fn(),
      })),
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

describe("AgentSpriteManager", () => {
  let scene: ReturnType<typeof createMockScene>;
  let wsClient: ReturnType<typeof createMockWsClient>;
  let manager: AgentSpriteManager;

  beforeEach(() => {
    scene = createMockScene();
    wsClient = createMockWsClient();
    manager = new AgentSpriteManager(scene as any, wsClient as any, null);
  });

  it("creates sprites for all 8 entities (excludes management)", () => {
    expect(manager.getSpriteCount()).toBe(8);
  });

  it("creates sprites for each main agent", () => {
    for (const id of [
      "vera",
      "rex",
      "aurora",
      "pixel",
      "fork",
      "sentinel",
      "grok",
    ]) {
      expect(manager.getSprite(id)).toBeDefined();
    }
  });

  it("creates sprite for alpha", () => {
    expect(manager.getSprite("alpha")).toBeDefined();
  });

  it("does not create sprite for management", () => {
    expect(manager.getSprite("management")).toBeUndefined();
  });

  it("registers WebSocket event handler", () => {
    expect(wsClient.onEvent).toHaveBeenCalledTimes(1);
  });

  it("handles agent_move event", () => {
    const vera = manager.getSprite("vera")!;
    const moveToSpy = vi.spyOn(vera, "moveTo");

    wsClient.emit({
      event_id: "1",
      event_type: EventType.AGENT_MOVE,
      timestamp: Date.now(),
      data: { agent_id: "vera", to: { x: 300, y: 400 } },
    });

    expect(moveToSpy).toHaveBeenCalledWith(300, 400, undefined);
  });

  it("handles agent_speak event", () => {
    const vera = manager.getSprite("vera")!;
    const playAnimSpy = vi.spyOn(vera, "playAnimation");
    const setStatusSpy = vi.spyOn(vera, "setStatus");
    const setBadgeSpy = vi.spyOn(vera, "setBadgeState");

    wsClient.emit({
      event_id: "2",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello" },
    });

    expect(playAnimSpy).toHaveBeenCalledWith("talking");
    expect(setStatusSpy).toHaveBeenCalledWith("speaking");
    expect(setBadgeSpy).toHaveBeenCalledWith("conversation");
  });

  it("clears permission pending on speak", () => {
    const vera = manager.getSprite("vera")!;
    const setPermSpy = vi.spyOn(vera, "setPermissionPending");

    wsClient.emit({
      event_id: "2",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello" },
    });

    expect(setPermSpy).toHaveBeenCalledWith(false);
  });

  it("handles agent_action event for building", () => {
    const rex = manager.getSprite("rex")!;
    const playAnimSpy = vi.spyOn(rex, "playAnimation");
    const setStatusSpy = vi.spyOn(rex, "setStatus");
    const setBadgeSpy = vi.spyOn(rex, "setBadgeState");

    wsClient.emit({
      event_id: "3",
      event_type: EventType.AGENT_ACTION,
      timestamp: Date.now(),
      data: { agent_id: "rex", action: "building" },
    });

    expect(playAnimSpy).toHaveBeenCalledWith("building");
    expect(setStatusSpy).toHaveBeenCalledWith("building");
    expect(setBadgeSpy).toHaveBeenCalledWith("active");
  });

  it("handles agent_action event for thinking", () => {
    const aurora = manager.getSprite("aurora")!;
    const playAnimSpy = vi.spyOn(aurora, "playAnimation");
    const setBadgeSpy = vi.spyOn(aurora, "setBadgeState");

    wsClient.emit({
      event_id: "4",
      event_type: EventType.AGENT_ACTION,
      timestamp: Date.now(),
      data: { agent_id: "aurora", action: "thinking" },
    });

    expect(playAnimSpy).toHaveBeenCalledWith("thinking");
    expect(setBadgeSpy).toHaveBeenCalledWith("active");
  });

  it("ignores events for unknown agent IDs", () => {
    // Should not throw
    wsClient.emit({
      event_id: "5",
      event_type: EventType.AGENT_MOVE,
      timestamp: Date.now(),
      data: { agent_id: "nonexistent", to: { x: 0, y: 0 } },
    });
  });

  it("getAllSprites returns all sprites", () => {
    const all = manager.getAllSprites();
    expect(all).toHaveLength(8);
  });

  it("cleans up on destroy", () => {
    manager.destroy();
    expect(manager.getSpriteCount()).toBe(0);
  });

  it("works without WebSocket client", () => {
    const mgr = new AgentSpriteManager(scene as any, null, null);
    expect(mgr.getSpriteCount()).toBe(8);
    mgr.destroy();
  });

  // ── TOOL_EXECUTED handler tests ────────────────────────────────

  describe("TOOL_EXECUTED", () => {
    it("sets activity label and active badge on tool execution", () => {
      const vera = manager.getSprite("vera")!;
      const setActivitySpy = vi.spyOn(vera, "setActivity");
      const setBadgeSpy = vi.spyOn(vera, "setBadgeState");

      wsClient.emit({
        event_id: "10",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "file_read", success: undefined },
      });

      expect(setActivitySpy).toHaveBeenCalledWith("file_read");
      expect(setBadgeSpy).toHaveBeenCalledWith("active");
    });

    it("shows progress dots when tool is in-progress (success undefined)", () => {
      const vera = manager.getSprite("vera")!;
      const setProgressSpy = vi.spyOn(vera, "setProgress");

      wsClient.emit({
        event_id: "11",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "web_search" },
      });

      expect(setProgressSpy).toHaveBeenCalledWith(true);
    });

    it("clears progress and schedules cleanup on success", () => {
      const vera = manager.getSprite("vera")!;
      const setProgressSpy = vi.spyOn(vera, "setProgress");

      wsClient.emit({
        event_id: "12",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "file_read", success: true },
      });

      expect(setProgressSpy).toHaveBeenCalledWith(false);
      expect(scene.time.delayedCall).toHaveBeenCalledWith(2000, expect.any(Function));
    });

    it("sets error badge on tool failure", () => {
      const rex = manager.getSprite("rex")!;
      const setBadgeSpy = vi.spyOn(rex, "setBadgeState");

      wsClient.emit({
        event_id: "13",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "rex", tool_name: "run_tests", success: false },
      });

      expect(setBadgeSpy).toHaveBeenCalledWith("error");
    });

    it("ignores tool events for unknown agents", () => {
      wsClient.emit({
        event_id: "14",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "unknown", tool_name: "test" },
      });
      // Should not throw
    });
  });

  // ── MANAGEMENT_SHADOW handler tests ────────────────────────────

  describe("MANAGEMENT_SHADOW", () => {
    it("sets permission pending and waiting badge", () => {
      const vera = manager.getSprite("vera")!;
      const setPermSpy = vi.spyOn(vera, "setPermissionPending");
      const setBadgeSpy = vi.spyOn(vera, "setBadgeState");

      wsClient.emit({
        event_id: "20",
        event_type: EventType.MANAGEMENT_SHADOW,
        timestamp: Date.now(),
        data: { agent_id: "vera", flagged_content: "test" },
      });

      expect(setPermSpy).toHaveBeenCalledWith(true);
      expect(setBadgeSpy).toHaveBeenCalledWith("waiting");
    });

    it("schedules auto-clear after 3 seconds", () => {
      wsClient.emit({
        event_id: "21",
        event_type: EventType.MANAGEMENT_SHADOW,
        timestamp: Date.now(),
        data: { agent_id: "vera", flagged_content: "test" },
      });

      expect(scene.time.delayedCall).toHaveBeenCalledWith(3000, expect.any(Function));
    });

    it("ignores shadow events for unknown agents", () => {
      wsClient.emit({
        event_id: "22",
        event_type: EventType.MANAGEMENT_SHADOW,
        timestamp: Date.now(),
        data: { agent_id: "unknown", flagged_content: "test" },
      });
      // Should not throw
    });
  });
});

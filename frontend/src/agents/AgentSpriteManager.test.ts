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
        setVisible: vi.fn(),
        setAlpha: vi.fn(),
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
          setScrollFactor: vi.fn(),
          setVisible: vi.fn(function (this: any, v: boolean) {
            this.visible = v;
            return this;
          }),
          setText: vi.fn(),
          setAlpha: vi.fn(),
          destroy: vi.fn(),
        }),
      ),
      rectangle: vi.fn((_x: number, _y: number, _w: number, _h: number, _color: number) => ({
        setDepth: vi.fn(),
        setAlpha: vi.fn(),
        destroy: vi.fn(),
      })),
      graphics: vi.fn(() => ({
        x: 0,
        y: 0,
        setDepth: vi.fn().mockReturnThis(),
        setAlpha: vi.fn().mockReturnThis(),
        setPosition: vi.fn(function (this: any, x: number, y: number) {
          this.x = x;
          this.y = y;
        }),
        setVisible: vi.fn(),
        clear: vi.fn().mockReturnThis(),
        fillStyle: vi.fn().mockReturnThis(),
        fillCircle: vi.fn().mockReturnThis(),
        lineStyle: vi.fn().mockReturnThis(),
        beginPath: vi.fn().mockReturnThis(),
        moveTo: vi.fn().mockReturnThis(),
        lineTo: vi.fn().mockReturnThis(),
        strokePath: vi.fn().mockReturnThis(),
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
    cameras: {
      main: {
        flash: vi.fn(),
        centerX: 400,
        centerY: 300,
      },
    },
    anims: {
      exists: vi.fn(() => false),
    },
    textures: {
      exists: vi.fn(() => true),
    },
    events: {
      on: vi.fn(),
      off: vi.fn(),
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

    it("clears progress and schedules cleanup on success with 300ms delay", () => {
      const vera = manager.getSprite("vera")!;
      const setProgressSpy = vi.spyOn(vera, "setProgress");

      wsClient.emit({
        event_id: "12",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "file_read", success: true },
      });

      expect(setProgressSpy).toHaveBeenCalledWith(false);
      expect(scene.time.delayedCall).toHaveBeenCalledWith(300, expect.any(Function));
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

    it("plays thinking animation for reading tools (in-progress)", () => {
      const vera = manager.getSprite("vera")!;
      const playAnimSpy = vi.spyOn(vera, "playAnimation");

      wsClient.emit({
        event_id: "15",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "code_read" },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("thinking");
    });

    it("plays building animation for writing tools (in-progress)", () => {
      const rex = manager.getSprite("rex")!;
      const playAnimSpy = vi.spyOn(rex, "playAnimation");

      wsClient.emit({
        event_id: "16",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "rex", tool_name: "code_write" },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("building");
    });

    it("plays thinking animation for unknown tools (default)", () => {
      const vera = manager.getSprite("vera")!;
      const playAnimSpy = vi.spyOn(vera, "playAnimation");

      wsClient.emit({
        event_id: "17",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "some_unknown_tool" },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("thinking");
    });

    it("cancels pending idle timer when new tool starts", () => {
      const destroySpy = vi.fn();
      scene.time.delayedCall = vi.fn(() => ({ destroy: destroySpy }));

      // First tool completes — starts idle timer
      wsClient.emit({
        event_id: "18",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "code_read", success: true },
      });

      // New tool starts before idle timer fires
      wsClient.emit({
        event_id: "19",
        event_type: EventType.TOOL_EXECUTED,
        timestamp: Date.now(),
        data: { agent_id: "vera", tool_name: "code_write" },
      });

      // The first timer should have been cancelled
      expect(destroySpy).toHaveBeenCalled();
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

  // ── MANAGEMENT_INTERVENTION handler tests ─────────────────────

  describe("MANAGEMENT_INTERVENTION", () => {
    it("flashes camera red on intervention", () => {
      wsClient.emit({
        event_id: "30",
        event_type: EventType.MANAGEMENT_INTERVENTION,
        timestamp: Date.now(),
        data: { agent_id: "vera", action: "filter", original_text: "bad", filtered_text: "good" },
      });

      expect(scene.cameras.main.flash).toHaveBeenCalledWith(500, 255, 50, 50);
    });

    it("creates warning text overlay", () => {
      wsClient.emit({
        event_id: "31",
        event_type: EventType.MANAGEMENT_INTERVENTION,
        timestamp: Date.now(),
        data: { agent_id: "vera", action: "filter", original_text: "bad", filtered_text: "good" },
      });

      // Should create a text object for "MANAGEMENT INTERVENTION"
      const textCalls = scene.add.text.mock.calls;
      const warningCall = textCalls.find(
        (call: any[]) => call[2] === "MANAGEMENT INTERVENTION",
      );
      expect(warningCall).toBeDefined();
    });

    it("shakes the targeted agent sprite", () => {
      wsClient.emit({
        event_id: "32",
        event_type: EventType.MANAGEMENT_INTERVENTION,
        timestamp: Date.now(),
        data: { agent_id: "vera", action: "filter", original_text: "bad", filtered_text: "good" },
      });

      const vera = manager.getSprite("vera")!;
      expect(vera.getBadgeState()).toBe("error");
    });

    it("handles intervention for unknown agent without crash", () => {
      wsClient.emit({
        event_id: "33",
        event_type: EventType.MANAGEMENT_INTERVENTION,
        timestamp: Date.now(),
        data: { agent_id: "nonexistent", action: "filter", original_text: "a", filtered_text: "b" },
      });

      // Should still flash camera even without sprite
      expect(scene.cameras.main.flash).toHaveBeenCalled();
    });
  });

  // ── MANAGEMENT_WARNING handler tests ──────────────────────────

  describe("MANAGEMENT_WARNING", () => {
    it("sets activity and waiting badge on warning", () => {
      const vera = manager.getSprite("vera")!;
      const setActivitySpy = vi.spyOn(vera, "setActivity");
      const setBadgeSpy = vi.spyOn(vera, "setBadgeState");

      wsClient.emit({
        event_id: "40",
        event_type: EventType.MANAGEMENT_WARNING,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "tone" },
      });

      expect(setActivitySpy).toHaveBeenCalledWith("warning");
      expect(setBadgeSpy).toHaveBeenCalledWith("waiting");
    });

    it("schedules auto-clear after 3 seconds", () => {
      wsClient.emit({
        event_id: "41",
        event_type: EventType.MANAGEMENT_WARNING,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "tone" },
      });

      expect(scene.time.delayedCall).toHaveBeenCalledWith(3000, expect.any(Function));
    });
  });

  // ── ALPHA_DISPATCH handler tests ──────────────────────────────

  describe("ALPHA_DISPATCH", () => {
    it("plays running animation on alpha", () => {
      const alpha = manager.getSprite("alpha")!;
      const playAnimSpy = vi.spyOn(alpha, "playAnimation");

      wsClient.emit({
        event_id: "50",
        event_type: EventType.ALPHA_DISPATCH,
        timestamp: Date.now(),
        data: { task: "fetch data", dispatched_by: "vera" },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("running");
    });

    it("sets active badge on dispatch", () => {
      const alpha = manager.getSprite("alpha")!;
      const setBadgeSpy = vi.spyOn(alpha, "setBadgeState");

      wsClient.emit({
        event_id: "51",
        event_type: EventType.ALPHA_DISPATCH,
        timestamp: Date.now(),
        data: { task: "fetch data", dispatched_by: "vera" },
      });

      expect(setBadgeSpy).toHaveBeenCalledWith("active");
    });

    it("tweens alpha off-screen when no worldManager", () => {
      wsClient.emit({
        event_id: "52",
        event_type: EventType.ALPHA_DISPATCH,
        timestamp: Date.now(),
        data: { task: "fetch data", dispatched_by: "vera" },
      });

      expect(scene.tweens.add).toHaveBeenCalledWith(
        expect.objectContaining({
          x: -50,
          duration: 1000,
        }),
      );
    });

    it("uses pathfinding when worldManager is available", () => {
      const mockWorldManager = {
        expandWorld: vi.fn(),
        findPath: vi.fn(() => null),
        getTileSize: vi.fn(() => 32),
      };
      const mgr = new AgentSpriteManager(
        scene as any,
        wsClient as any,
        mockWorldManager as any,
      );

      wsClient.emit({
        event_id: "53",
        event_type: EventType.ALPHA_DISPATCH,
        timestamp: Date.now(),
        data: { task: "fetch data", from: "vera", task_id: "t1" },
      });

      const alpha = mgr.getSprite("alpha")!;
      expect(alpha.getBadgeState()).toBe("active");
      mgr.destroy();
    });
  });

  // ── ALPHA_RETURN handler tests ────────────────────────────────

  describe("ALPHA_RETURN", () => {
    it("makes alpha visible on return", () => {
      const alpha = manager.getSprite("alpha")!;

      wsClient.emit({
        event_id: "60",
        event_type: EventType.ALPHA_RETURN,
        timestamp: Date.now(),
        data: { task: "fetch data", result: "success", success: true },
      });

      expect(alpha.sprite.setVisible).toHaveBeenCalledWith(true);
    });

    it("plays carrying animation on successful return", () => {
      const alpha = manager.getSprite("alpha")!;
      const playAnimSpy = vi.spyOn(alpha, "playAnimation");

      wsClient.emit({
        event_id: "61",
        event_type: EventType.ALPHA_RETURN,
        timestamp: Date.now(),
        data: { task: "fetch data", result: "done", success: true },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("carrying");
    });

    it("plays confused animation on failed return", () => {
      const alpha = manager.getSprite("alpha")!;
      const playAnimSpy = vi.spyOn(alpha, "playAnimation");

      wsClient.emit({
        event_id: "62",
        event_type: EventType.ALPHA_RETURN,
        timestamp: Date.now(),
        data: { task: "fetch data", result: "error", success: false },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("confused");
    });
  });

  // ── TASK_DELEGATED handler tests ─────────────────────────────

  describe("TASK_DELEGATED", () => {
    it("routes alpha delegation through alpha dispatch handler", () => {
      const alpha = manager.getSprite("alpha")!;
      const playAnimSpy = vi.spyOn(alpha, "playAnimation");

      wsClient.emit({
        event_id: "200",
        event_type: EventType.TASK_DELEGATED,
        timestamp: Date.now(),
        data: {
          from_agent: "vera",
          to_agent: "alpha",
          task_description: "fetch data",
          task_id: "task_1",
        },
      });

      expect(playAnimSpy).toHaveBeenCalledWith("running");
    });

    it("creates ghost sprite for non-alpha delegation", () => {
      wsClient.emit({
        event_id: "201",
        event_type: EventType.TASK_DELEGATED,
        timestamp: Date.now(),
        data: {
          from_agent: "vera",
          to_agent: "rex",
          task_description: "review code",
          task_id: "task_2",
        },
      });

      // Ghost sprite should be created via scene.add.sprite
      expect(scene.add.sprite).toHaveBeenCalled();
    });

    it("does not crash for unknown delegator", () => {
      wsClient.emit({
        event_id: "202",
        event_type: EventType.TASK_DELEGATED,
        timestamp: Date.now(),
        data: {
          from_agent: "unknown",
          to_agent: "rex",
          task_description: "something",
          task_id: "task_3",
        },
      });
      // Should not throw
    });
  });

  // ── TASK_COMPLETED handler tests ──────────────────────────────

  describe("TASK_COMPLETED", () => {
    it("routes alpha task completion through alpha return handler", () => {
      const alpha = manager.getSprite("alpha")!;

      wsClient.emit({
        event_id: "210",
        event_type: EventType.TASK_COMPLETED,
        timestamp: Date.now(),
        data: {
          task_id: "task_1",
          to_agent: "alpha",
          success: true,
          result: "done",
        },
      });

      expect(alpha.sprite.setVisible).toHaveBeenCalledWith(true);
    });

    it("does not crash for unknown task_id completion", () => {
      wsClient.emit({
        event_id: "211",
        event_type: EventType.TASK_COMPLETED,
        timestamp: Date.now(),
        data: {
          task_id: "nonexistent",
          to_agent: "rex",
          success: true,
        },
      });
      // Should not throw
    });
  });

  // ── WORLD_EXPANSION handler tests ─────────────────────────────

  describe("WORLD_EXPANSION", () => {
    it("calls worldManager.expandWorld when worldManager exists", () => {
      const mockWorldManager = { expandWorld: vi.fn() };
      const mgr = new AgentSpriteManager(
        scene as any,
        wsClient as any,
        mockWorldManager as any,
      );

      wsClient.emit({
        event_id: "70",
        event_type: EventType.WORLD_EXPANSION,
        timestamp: Date.now(),
        data: { zone: "garden", description: "A beautiful garden" },
      });

      expect(mockWorldManager.expandWorld).toHaveBeenCalledWith("garden", "A beautiful garden");
      mgr.destroy();
    });

    it("does not crash when worldManager is null", () => {
      wsClient.emit({
        event_id: "71",
        event_type: EventType.WORLD_EXPANSION,
        timestamp: Date.now(),
        data: { zone: "garden", description: "A garden" },
      });
      // Should not throw
    });
  });

  // ── CONFIG_RELOADED handler tests ─────────────────────────────

  describe("CONFIG_RELOADED", () => {
    it("logs config reload without crash", () => {
      const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});

      wsClient.emit({
        event_id: "80",
        event_type: EventType.CONFIG_RELOADED,
        timestamp: Date.now(),
        data: { config_type: "agents", changes: ["vera.chattiness"] },
      });

      expect(consoleSpy).toHaveBeenCalledWith(
        "Config reloaded:",
        "agents",
        ["vera.chattiness"],
      );
      consoleSpy.mockRestore();
    });
  });

  // ── AGENT_SPAWN handler tests ────────────────────────────────

  describe("AGENT_SPAWN", () => {
    it("plays spawn effect on existing agent (reconnect)", () => {
      const vera = manager.getSprite("vera")!;

      wsClient.emit({
        event_id: "90",
        event_type: EventType.AGENT_SPAWN,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "reconnect" },
      });

      // Spawn effect sets alpha to 0 and tweens back
      expect(vera.sprite.setAlpha).toHaveBeenCalledWith(0);
    });

    it("does not crash for unknown agent spawn", () => {
      wsClient.emit({
        event_id: "91",
        event_type: EventType.AGENT_SPAWN,
        timestamp: Date.now(),
        data: { agent_id: "nonexistent", reason: "start" },
      });
      // Should not throw
    });

    it("ignores management agent spawn", () => {
      wsClient.emit({
        event_id: "92",
        event_type: EventType.AGENT_SPAWN,
        timestamp: Date.now(),
        data: { agent_id: "management", reason: "start" },
      });
      expect(manager.getSprite("management")).toBeUndefined();
    });
  });

  // ── AGENT_DESPAWN handler tests ──────────────────────────────

  describe("AGENT_DESPAWN", () => {
    it("sets spawning flag on despawn", () => {
      const vera = manager.getSprite("vera")!;

      wsClient.emit({
        event_id: "100",
        event_type: EventType.AGENT_DESPAWN,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "shutdown" },
      });

      // Despawn effect sets spawning flag immediately
      expect(vera.spawning).toBe(true);
    });

    it("creates tween for sprite fade-out", () => {
      wsClient.emit({
        event_id: "101",
        event_type: EventType.AGENT_DESPAWN,
        timestamp: Date.now(),
        data: { agent_id: "vera", reason: "error" },
      });

      // Should have created tweens (particles + sprite fade)
      expect(scene.tweens.add).toHaveBeenCalled();
    });

    it("does not crash for unknown agent despawn", () => {
      wsClient.emit({
        event_id: "102",
        event_type: EventType.AGENT_DESPAWN,
        timestamp: Date.now(),
        data: { agent_id: "nonexistent", reason: "shutdown" },
      });
      // Should not throw
    });
  });
});

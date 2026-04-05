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
        setFrame: vi.fn(),
        play: vi.fn(),
        anims: { exists: vi.fn(() => false) },
        destroy: vi.fn(),
      })),
      text: vi.fn(
        (_x: number, _y: number, _text: string, _style?: object) => ({
          x: _x,
          y: _y,
          setOrigin: vi.fn(),
          setVisible: vi.fn(),
          setText: vi.fn(),
          destroy: vi.fn(),
        }),
      ),
    },
    tweens: {
      add: vi.fn(() => ({
        stop: vi.fn(),
      })),
    },
    time: {
      delayedCall: vi.fn(),
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

  it("creates sprites for all 8 entities (excludes overseer)", () => {
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

  it("does not create sprite for overseer", () => {
    expect(manager.getSprite("overseer")).toBeUndefined();
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

    expect(moveToSpy).toHaveBeenCalledWith(300, 400);
  });

  it("handles agent_speak event", () => {
    const vera = manager.getSprite("vera")!;
    const playAnimSpy = vi.spyOn(vera, "playAnimation");
    const setStatusSpy = vi.spyOn(vera, "setStatus");

    wsClient.emit({
      event_id: "2",
      event_type: EventType.AGENT_SPEAK,
      timestamp: Date.now(),
      data: { agent_id: "vera", text: "Hello" },
    });

    expect(playAnimSpy).toHaveBeenCalledWith("talking");
    expect(setStatusSpy).toHaveBeenCalledWith("speaking");
  });

  it("handles agent_action event for building", () => {
    const rex = manager.getSprite("rex")!;
    const playAnimSpy = vi.spyOn(rex, "playAnimation");
    const setStatusSpy = vi.spyOn(rex, "setStatus");

    wsClient.emit({
      event_id: "3",
      event_type: EventType.AGENT_ACTION,
      timestamp: Date.now(),
      data: { agent_id: "rex", action: "building" },
    });

    expect(playAnimSpy).toHaveBeenCalledWith("building");
    expect(setStatusSpy).toHaveBeenCalledWith("building");
  });

  it("handles agent_action event for thinking", () => {
    const aurora = manager.getSprite("aurora")!;
    const playAnimSpy = vi.spyOn(aurora, "playAnimation");

    wsClient.emit({
      event_id: "4",
      event_type: EventType.AGENT_ACTION,
      timestamp: Date.now(),
      data: { agent_id: "aurora", action: "thinking" },
    });

    expect(playAnimSpy).toHaveBeenCalledWith("thinking");
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
});

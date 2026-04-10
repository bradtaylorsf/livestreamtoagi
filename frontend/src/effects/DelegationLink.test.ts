import { describe, it, expect, vi, beforeEach } from "vitest";
import { DelegationLink } from "./DelegationLink";

function createMockScene() {
  const updateCallbacks: Array<() => void> = [];
  return {
    add: {
      graphics: vi.fn(() => ({
        setDepth: vi.fn(),
        clear: vi.fn(),
        lineStyle: vi.fn(),
        beginPath: vi.fn(),
        moveTo: vi.fn(),
        lineTo: vi.fn(),
        strokePath: vi.fn(),
        destroy: vi.fn(),
      })),
    },
    events: {
      on: vi.fn((_event: string, cb: () => void) => {
        updateCallbacks.push(cb);
      }),
      off: vi.fn(),
    },
    _triggerUpdate: () => {
      for (const cb of updateCallbacks) cb();
    },
  };
}

function createMockSprite(x: number, y: number) {
  return { x, y, height: 32 };
}

describe("DelegationLink", () => {
  let scene: ReturnType<typeof createMockScene>;

  beforeEach(() => {
    scene = createMockScene();
  });

  it("creates a graphics object on construction", () => {
    const from = createMockSprite(100, 200);
    const to = createMockSprite(300, 200);
    const _link = new DelegationLink(scene as any, from as any, to as any, "vera");
    expect(scene.add.graphics).toHaveBeenCalled();
  });

  it("registers an update handler", () => {
    const from = createMockSprite(100, 200);
    const to = createMockSprite(300, 200);
    const _link = new DelegationLink(scene as any, from as any, to as any, "vera");
    expect(scene.events.on).toHaveBeenCalledWith("update", expect.any(Function));
  });

  it("unregisters update handler on destroy", () => {
    const from = createMockSprite(100, 200);
    const to = createMockSprite(300, 200);
    const link = new DelegationLink(scene as any, from as any, to as any, "vera");
    link.destroy();
    expect(scene.events.off).toHaveBeenCalledWith("update", expect.any(Function));
  });

  it("does not draw after destroy", () => {
    const from = createMockSprite(100, 200);
    const to = createMockSprite(300, 200);
    const link = new DelegationLink(scene as any, from as any, to as any, "vera");
    link.destroy();
    // Trigger update after destroy — should not throw
    scene._triggerUpdate();
  });

  it("can be destroyed multiple times without error", () => {
    const from = createMockSprite(100, 200);
    const to = createMockSprite(300, 200);
    const link = new DelegationLink(scene as any, from as any, to as any, "vera");
    link.destroy();
    link.destroy(); // second destroy should be safe
  });
});

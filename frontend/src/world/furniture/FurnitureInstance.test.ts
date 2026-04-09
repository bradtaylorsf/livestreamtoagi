import { describe, it, expect, vi } from "vitest";
import { FurnitureInstance } from "./FurnitureInstance";
import type { FurnitureManifest } from "./FurnitureManifest";

function createMockScene() {
  return {
    add: {
      image: vi.fn((_x: number, _y: number, _key: string) => ({
        x: _x,
        y: _y,
        depth: 0,
        setOrigin: vi.fn(),
        setDepth: vi.fn(function (this: any, d: number) {
          this.depth = d;
        }),
        setTexture: vi.fn(),
        destroy: vi.fn(),
      })),
    },
  };
}

const STATEFUL_MANIFEST: FurnitureManifest = {
  id: "MONITOR",
  name: "Monitor",
  category: "electronics",
  footprint: [1, 1],
  isDesk: false,
  states: { off: "monitor_off", on: "monitor_on" },
  canPlaceOnSurfaces: true,
  zSortOffset: 0.001,
};

const PLAIN_MANIFEST: FurnitureManifest = {
  id: "DESK",
  name: "Standard Desk",
  category: "desks",
  footprint: [3, 2],
  isDesk: true,
  canPlaceOnSurfaces: false,
  zSortOffset: 0,
};

describe("FurnitureInstance", () => {
  it("creates sprite at specified position", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, PLAIN_MANIFEST, 100, 200);
    expect(scene.add.image).toHaveBeenCalledWith(100, 200, "desk");
    expect(instance.x).toBe(100);
    expect(instance.y).toBe(200);
  });

  it("uses 'off' state texture as default for stateful furniture", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, STATEFUL_MANIFEST, 50, 50);
    expect(scene.add.image).toHaveBeenCalledWith(50, 50, "monitor_off");
    expect(instance.getState()).toBe("off");
  });

  it("setState swaps texture to the state's texture key", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, STATEFUL_MANIFEST, 50, 50);
    instance.setState("on");
    expect(instance.sprite.setTexture).toHaveBeenCalledWith("monitor_on");
    expect(instance.getState()).toBe("on");
  });

  it("setState back to off", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, STATEFUL_MANIFEST, 50, 50);
    instance.setState("on");
    instance.setState("off");
    expect(instance.sprite.setTexture).toHaveBeenCalledWith("monitor_off");
    expect(instance.getState()).toBe("off");
  });

  it("setState ignores unknown states", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, STATEFUL_MANIFEST, 50, 50);
    instance.setState("exploding");
    // Should still be "off"
    expect(instance.getState()).toBe("off");
  });

  it("setState is a no-op for non-stateful furniture", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, PLAIN_MANIFEST, 100, 200);
    instance.setState("on");
    expect(instance.sprite.setTexture).not.toHaveBeenCalled();
  });

  it("depth calculation includes Y position and zSortOffset", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, STATEFUL_MANIFEST, 50, 300);
    // depth = 1 + 300/10000 + 0.001 = 1.031
    expect(instance.sprite.setDepth).toHaveBeenCalledWith(expect.closeTo(1.031, 3));
  });

  it("accepts initial state parameter", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, STATEFUL_MANIFEST, 50, 50, "on");
    expect(scene.add.image).toHaveBeenCalledWith(50, 50, "monitor_on");
    expect(instance.getState()).toBe("on");
  });

  it("destroy removes sprite", () => {
    const scene = createMockScene();
    const instance = new FurnitureInstance(scene as any, PLAIN_MANIFEST, 100, 200);
    instance.destroy();
    expect(instance.sprite.destroy).toHaveBeenCalled();
  });
});

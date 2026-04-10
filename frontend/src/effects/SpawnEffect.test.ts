import { describe, it, expect, vi, beforeEach } from "vitest";
import { SpawnEffect } from "./SpawnEffect";

function createMockScene() {
  return {
    add: {
      rectangle: vi.fn((_x: number, _y: number, _w: number, _h: number, _color: number) => ({
        setDepth: vi.fn(),
        setAlpha: vi.fn(),
        destroy: vi.fn(),
      })),
    },
    tweens: {
      add: vi.fn((config: any) => {
        // Immediately call onComplete if provided
        if (config.onComplete) {
          config.onComplete();
        }
        return { stop: vi.fn() };
      }),
    },
    textures: {
      exists: vi.fn(() => false),
      createCanvas: vi.fn(() => ({
        getContext: vi.fn(() => ({
          fillStyle: "",
          fillRect: vi.fn(),
        })),
        refresh: vi.fn(),
      })),
    },
  };
}

function createMockSprite() {
  return {
    agentId: "vera",
    spawning: false,
    sprite: {
      x: 100,
      y: 200,
      setAlpha: vi.fn(),
    },
    getPosition: vi.fn(() => ({ x: 100, y: 200 })),
  };
}

describe("SpawnEffect", () => {
  let scene: ReturnType<typeof createMockScene>;
  let effect: SpawnEffect;

  beforeEach(() => {
    scene = createMockScene();
    effect = new SpawnEffect(scene as any);
  });

  it("creates particle texture on construction", () => {
    expect(scene.textures.createCanvas).toHaveBeenCalledWith("__spawn_particle", 2, 2);
  });

  it("skips texture creation if already exists", () => {
    scene.textures.exists = vi.fn(() => true);
    scene.textures.createCanvas = vi.fn();
    new SpawnEffect(scene as any);
    expect(scene.textures.createCanvas).not.toHaveBeenCalled();
  });

  describe("playSpawn", () => {
    it("sets spawning flag to true during effect", () => {
      // Override tweens to not auto-complete
      scene.tweens.add = vi.fn(() => ({ stop: vi.fn() }));
      const sprite = createMockSprite();
      effect.playSpawn(sprite as any);
      expect(sprite.spawning).toBe(true);
    });

    it("sets sprite alpha to 0 initially", () => {
      scene.tweens.add = vi.fn(() => ({ stop: vi.fn() }));
      const sprite = createMockSprite();
      effect.playSpawn(sprite as any);
      expect(sprite.sprite.setAlpha).toHaveBeenCalledWith(0);
    });

    it("creates particle rectangles", () => {
      scene.tweens.add = vi.fn(() => ({ stop: vi.fn() }));
      const sprite = createMockSprite();
      effect.playSpawn(sprite as any);
      // 24 particles + 1 sprite tween = multiple calls
      expect(scene.add.rectangle).toHaveBeenCalled();
      expect(scene.add.rectangle.mock.calls.length).toBe(24);
    });

    it("calls onComplete callback when effect finishes", () => {
      const sprite = createMockSprite();
      const onComplete = vi.fn();
      effect.playSpawn(sprite as any, onComplete);
      expect(onComplete).toHaveBeenCalled();
    });

    it("resets spawning flag on completion", () => {
      const sprite = createMockSprite();
      effect.playSpawn(sprite as any);
      expect(sprite.spawning).toBe(false);
    });
  });

  describe("playDespawn", () => {
    it("sets spawning flag to true during effect", () => {
      scene.tweens.add = vi.fn(() => ({ stop: vi.fn() }));
      const sprite = createMockSprite();
      effect.playDespawn(sprite as any);
      expect(sprite.spawning).toBe(true);
    });

    it("creates particle rectangles", () => {
      scene.tweens.add = vi.fn(() => ({ stop: vi.fn() }));
      const sprite = createMockSprite();
      effect.playDespawn(sprite as any);
      expect(scene.add.rectangle.mock.calls.length).toBe(24);
    });

    it("calls onComplete callback when effect finishes", () => {
      const sprite = createMockSprite();
      const onComplete = vi.fn();
      effect.playDespawn(sprite as any, onComplete);
      expect(onComplete).toHaveBeenCalled();
    });

    it("resets spawning flag on completion", () => {
      const sprite = createMockSprite();
      effect.playDespawn(sprite as any);
      expect(sprite.spawning).toBe(false);
    });
  });
});

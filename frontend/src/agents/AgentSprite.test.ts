import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentSprite, type AgentSpriteConfig } from "./AgentSprite";

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
        (_x: number, _y: number, _text: string, _style: object) => ({
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

describe("AgentSprite", () => {
  let scene: ReturnType<typeof createMockScene>;
  let agentSprite: AgentSprite;

  const config: AgentSpriteConfig = {
    agentId: "vera",
    name: "Vera",
    spriteKey: "sprite_vera",
    frameSize: 32,
    x: 100,
    y: 200,
  };

  beforeEach(() => {
    scene = createMockScene();
    agentSprite = new AgentSprite(scene as any, config);
  });

  it("creates sprite at correct position", () => {
    expect(scene.add.sprite).toHaveBeenCalledWith(100, 200, "sprite_vera");
  });

  it("creates name label", () => {
    expect(scene.add.text).toHaveBeenCalledWith(
      100,
      204,
      "Vera",
      expect.any(Object),
    );
  });

  it("creates status label (initially hidden)", () => {
    // Third call to add.text is the status label
    const statusCall = scene.add.text.mock.calls[1];
    expect(statusCall).toBeDefined();
    // Status label should be hidden initially
    const statusObj = scene.add.text.mock.results[1].value;
    expect(statusObj.setVisible).toHaveBeenCalledWith(false);
  });

  it("plays animation", () => {
    agentSprite.playAnimation("talking");
    expect(agentSprite.getCurrentAnimation()).toBe("talking");
  });

  it("sets status with icon", () => {
    agentSprite.setStatus("thinking");
    expect(agentSprite.getStatus()).toBe("thinking");
  });

  it("clears status when set to idle", () => {
    agentSprite.setStatus("thinking");
    agentSprite.setStatus("idle");
    expect(agentSprite.getStatus()).toBe("idle");
  });

  it("creates movement tween", () => {
    agentSprite.moveTo(300, 400);
    // Should create tweens for sprite, name label, and status label
    expect(scene.tweens.add).toHaveBeenCalled();
  });

  it("determines walk direction animation from movement delta", () => {
    // Moving right
    agentSprite.moveTo(300, 200);
    expect(agentSprite.getCurrentAnimation()).toBe("walk_right");
  });

  it("determines walk_left for negative x movement", () => {
    agentSprite.moveTo(0, 200);
    expect(agentSprite.getCurrentAnimation()).toBe("walk_left");
  });

  it("determines walk_down for positive y movement", () => {
    agentSprite.moveTo(100, 400);
    expect(agentSprite.getCurrentAnimation()).toBe("walk_down");
  });

  it("returns current position", () => {
    const pos = agentSprite.getPosition();
    expect(pos.x).toBe(100);
    expect(pos.y).toBe(200);
  });

  it("cleans up on destroy", () => {
    agentSprite.destroy();
    expect(agentSprite.sprite.destroy).toHaveBeenCalled();
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentSprite, type AgentSpriteConfig, formatToolName } from "./AgentSprite";

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
        x: 0,
        y: 0,
        setDepth: vi.fn(),
        setAlpha: vi.fn(),
        setPosition: vi.fn(function (this: any, x: number, y: number) {
          this.x = x;
          this.y = y;
        }),
        setVisible: vi.fn(),
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
    anims: {
      exists: vi.fn(() => false),
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
    // Second call to add.text is the status label
    const statusObj = scene.add.text.mock.results[1].value;
    expect(statusObj.setVisible).toHaveBeenCalledWith(false);
  });

  it("creates activity label (initially hidden)", () => {
    // Third call to add.text is the activity label
    const activityObj = scene.add.text.mock.results[2].value;
    expect(activityObj.setVisible).toHaveBeenCalledWith(false);
  });

  it("creates status badge graphics", () => {
    expect(scene.add.graphics).toHaveBeenCalled();
    const badge = scene.add.graphics.mock.results[0].value;
    expect(badge.setDepth).toHaveBeenCalledWith(3);
    expect(badge.fillCircle).toHaveBeenCalled();
  });

  it("creates permission indicator (initially hidden)", () => {
    // Fourth call to add.text is the permission indicator
    const permObj = scene.add.text.mock.results[3].value;
    expect(permObj.setVisible).toHaveBeenCalledWith(false);
  });

  it("creates progress dots (initially hidden)", () => {
    // Fifth call to add.text is the progress dots
    const dotsObj = scene.add.text.mock.results[4].value;
    expect(dotsObj.setVisible).toHaveBeenCalledWith(false);
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

  it("creates movement tween via direct fallback", () => {
    agentSprite.moveTo(300, 400);
    // Should create tweens for sprite, name, status, activity, permission, progress
    expect(scene.tweens.add).toHaveBeenCalled();
  });

  it("marks agent as busy during movement", () => {
    agentSprite.moveTo(300, 400);
    expect(agentSprite.isBusy).toBe(true);
  });

  it("cancels path and resets state", () => {
    agentSprite.moveTo(300, 400);
    agentSprite.cancelPath();
    expect(agentSprite.isBusy).toBe(false);
    expect(agentSprite.getCurrentAnimation()).toBe("idle");
  });

  it("determines walk direction animation from movement delta", () => {
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

  // ── Activity indicator tests ─────────────────────────────────

  describe("setActivity", () => {
    it("shows activity label with formatted tool name", () => {
      const activityObj = scene.add.text.mock.results[2].value;
      agentSprite.setActivity("file_read");
      expect(activityObj.setText).toHaveBeenCalledWith("Reading file...");
      expect(activityObj.setVisible).toHaveBeenCalledWith(true);
      expect(activityObj.setAlpha).toHaveBeenCalledWith(1);
    });

    it("starts fade-out tween when set to null", () => {
      const activityObj = scene.add.text.mock.results[2].value;
      activityObj.visible = true;
      agentSprite.setActivity(null);
      // Should create a fade-out tween
      expect(scene.tweens.add).toHaveBeenCalledWith(
        expect.objectContaining({
          targets: activityObj,
          alpha: 0,
          duration: 1000,
        }),
      );
    });
  });

  describe("setBadgeState", () => {
    it("sets badge state and redraws", () => {
      const badge = scene.add.graphics.mock.results[0].value;
      agentSprite.setBadgeState("active");
      expect(agentSprite.getBadgeState()).toBe("active");
      expect(badge.clear).toHaveBeenCalled();
      expect(badge.fillStyle).toHaveBeenCalledWith(0x44cc44, 1);
      expect(badge.fillCircle).toHaveBeenCalled();
    });

    it("creates pulse tween for active state", () => {
      agentSprite.setBadgeState("active");
      const badge = scene.add.graphics.mock.results[0].value;
      expect(scene.tweens.add).toHaveBeenCalledWith(
        expect.objectContaining({
          targets: badge,
          alpha: 0.6,
          duration: 500,
          yoyo: true,
          repeat: -1,
        }),
      );
    });

    it("stops pulse tween when leaving active state", () => {
      agentSprite.setBadgeState("active");
      const tweensBefore = scene.tweens.add.mock.calls.length;
      agentSprite.setBadgeState("idle");
      expect(agentSprite.getBadgeState()).toBe("idle");
    });

    it("sets error color for error state", () => {
      const badge = scene.add.graphics.mock.results[0].value;
      agentSprite.setBadgeState("error");
      expect(badge.fillStyle).toHaveBeenCalledWith(0xff4444, 1);
    });

    it("sets yellow color for waiting state", () => {
      const badge = scene.add.graphics.mock.results[0].value;
      agentSprite.setBadgeState("waiting");
      expect(badge.fillStyle).toHaveBeenCalledWith(0xffaa00, 1);
    });

    it("sets blue color for conversation state", () => {
      const badge = scene.add.graphics.mock.results[0].value;
      agentSprite.setBadgeState("conversation");
      expect(badge.fillStyle).toHaveBeenCalledWith(0x4488ff, 1);
    });
  });

  describe("setPermissionPending", () => {
    it("shows permission indicator when pending", () => {
      const permObj = scene.add.text.mock.results[3].value;
      agentSprite.setPermissionPending(true);
      expect(permObj.setVisible).toHaveBeenCalledWith(true);
    });

    it("hides permission indicator when not pending", () => {
      const permObj = scene.add.text.mock.results[3].value;
      agentSprite.setPermissionPending(false);
      expect(permObj.setVisible).toHaveBeenCalledWith(false);
    });
  });

  describe("setProgress", () => {
    it("shows progress dots when active", () => {
      const dotsObj = scene.add.text.mock.results[4].value;
      agentSprite.setProgress(true);
      expect(dotsObj.setVisible).toHaveBeenCalledWith(true);
      expect(dotsObj.setText).toHaveBeenCalledWith(".");
      expect(scene.time.addEvent).toHaveBeenCalledWith(
        expect.objectContaining({ delay: 400, loop: true }),
      );
    });

    it("hides progress dots when inactive", () => {
      const dotsObj = scene.add.text.mock.results[4].value;
      agentSprite.setProgress(true);
      agentSprite.setProgress(false);
      expect(dotsObj.setVisible).toHaveBeenCalledWith(false);
    });
  });
});

describe("formatToolName", () => {
  it("maps known tool names to friendly display text", () => {
    expect(formatToolName("file_read")).toBe("Reading file...");
    expect(formatToolName("code_write")).toBe("Writing code...");
    expect(formatToolName("web_search")).toBe("Searching...");
    expect(formatToolName("run_tests")).toBe("Running tests...");
  });

  it("formats unknown tool names with capitalization", () => {
    expect(formatToolName("custom_tool")).toBe("Custom Tool...");
  });

  it("truncates long tool names to 20 chars", () => {
    const result = formatToolName("very_long_tool_name_that_exceeds_limit");
    expect(result.length).toBeLessThanOrEqual(20);
  });
});

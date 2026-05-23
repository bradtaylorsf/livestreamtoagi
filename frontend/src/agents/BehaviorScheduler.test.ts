import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { BehaviorScheduler } from "./BehaviorScheduler";
import type { AgentSprite } from "./AgentSprite";

function createMockSprite(agentId: string, busy = false): AgentSprite {
  return {
    agentId,
    isBusy: busy,
    playMicroAnimation: vi.fn(),
    playAnimation: vi.fn(),
    moveTo: vi.fn(),
    cancelPath: vi.fn(),
    setStatus: vi.fn(),
    getStatus: vi.fn(() => "idle" as const),
    getCurrentAnimation: vi.fn(() => "idle"),
    getPosition: vi.fn(() => ({ x: 0, y: 0 })),
    destroy: vi.fn(),
    sprite: {} as any,
  } as unknown as AgentSprite;
}

describe("BehaviorScheduler", () => {
  let sprites: Map<string, AgentSprite>;
  let scheduler: BehaviorScheduler;

  beforeEach(() => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    sprites = new Map();
    sprites.set("vera", createMockSprite("vera"));
    sprites.set("rex", createMockSprite("rex"));
    scheduler = new BehaviorScheduler(sprites);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not trigger animations immediately", () => {
    scheduler.update(100); // 100ms
    const vera = sprites.get("vera")!;
    expect(vera.playMicroAnimation).not.toHaveBeenCalled();
  });

  it("triggers micro-animation after enough elapsed time", () => {
    // Advance past the maximum possible interval (60s * 1.5 scale factor)
    scheduler.update(100_000);
    const vera = sprites.get("vera")!;
    expect(vera.playMicroAnimation).toHaveBeenCalled();
  });

  it("skips busy agents", () => {
    const busySprite = createMockSprite("vera", true);
    sprites.set("vera", busySprite);
    scheduler = new BehaviorScheduler(sprites);

    scheduler.update(100_000);
    expect(busySprite.playMicroAnimation).not.toHaveBeenCalled();
  });

  it("resets timer after triggering", () => {
    // Trigger once
    scheduler.update(100_000);
    const vera = sprites.get("vera")!;
    const firstCallCount = (vera.playMicroAnimation as ReturnType<typeof vi.fn>).mock.calls.length;
    expect(firstCallCount).toBeGreaterThan(0);

    // Small update should not trigger again
    scheduler.update(100);
    expect((vera.playMicroAnimation as ReturnType<typeof vi.fn>).mock.calls.length).toBe(firstCallCount);
  });

  it("handles empty sprite map", () => {
    const emptyScheduler = new BehaviorScheduler(new Map());
    // Should not throw
    emptyScheduler.update(100_000);
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AutoStateManager } from "./AutoStateManager";
import type { FurnitureInstance } from "./FurnitureInstance";
import type { FurnitureManifest } from "./FurnitureManifest";

function createMockInstance(hasStates: boolean): FurnitureInstance {
  const manifest: FurnitureManifest = {
    id: hasStates ? "MONITOR" : "DESK",
    name: hasStates ? "Monitor" : "Desk",
    category: hasStates ? "electronics" : "desks",
    footprint: [1, 1],
    isDesk: !hasStates,
    states: hasStates ? { off: "monitor_off", on: "monitor_on" } : undefined,
    canPlaceOnSurfaces: hasStates,
    zSortOffset: 0,
  };

  return {
    manifest,
    setState: vi.fn(),
    getState: vi.fn(() => "off"),
    sprite: {} as any,
    x: 0,
    y: 0,
    updateDepth: vi.fn(),
    destroy: vi.fn(),
  } as unknown as FurnitureInstance;
}

describe("AutoStateManager", () => {
  let manager: AutoStateManager;
  let monitor1: FurnitureInstance;
  let monitor2: FurnitureInstance;
  let desk: FurnitureInstance;

  beforeEach(() => {
    vi.useFakeTimers();
    monitor1 = createMockInstance(true);
    monitor2 = createMockInstance(true);
    desk = createMockInstance(false);

    const workspaceFurniture = new Map<string, FurnitureInstance[]>();
    workspaceFurniture.set("vera", [monitor1, monitor2, desk]);
    workspaceFurniture.set("rex", [createMockInstance(true)]);

    manager = new AutoStateManager(workspaceFurniture);
  });

  afterEach(() => {
    manager.destroy();
    vi.useRealTimers();
  });

  it("switches stateful furniture to 'on' when agent becomes active (building)", () => {
    manager.onAgentStatusChange("vera", "building");
    expect(monitor1.setState).toHaveBeenCalledWith("on");
    expect(monitor2.setState).toHaveBeenCalledWith("on");
  });

  it("switches stateful furniture to 'on' for thinking status", () => {
    manager.onAgentStatusChange("vera", "thinking");
    expect(monitor1.setState).toHaveBeenCalledWith("on");
  });

  it("switches stateful furniture to 'on' for speaking status", () => {
    manager.onAgentStatusChange("vera", "speaking");
    expect(monitor1.setState).toHaveBeenCalledWith("on");
  });

  it("does not call setState on non-stateful furniture (desk)", () => {
    manager.onAgentStatusChange("vera", "building");
    expect(desk.setState).not.toHaveBeenCalled();
  });

  it("sets furniture to 'off' after delay when agent goes idle", () => {
    manager.onAgentStatusChange("vera", "building");
    vi.mocked(monitor1.setState).mockClear();
    vi.mocked(monitor2.setState).mockClear();

    manager.onAgentStatusChange("vera", "idle");

    // Not yet off — delay hasn't elapsed
    expect(monitor1.setState).not.toHaveBeenCalled();

    // Fast-forward past the delay
    vi.advanceTimersByTime(3000);

    expect(monitor1.setState).toHaveBeenCalledWith("off");
    expect(monitor2.setState).toHaveBeenCalledWith("off");
  });

  it("cancels off timer when agent becomes active again before delay", () => {
    manager.onAgentStatusChange("vera", "building");
    vi.mocked(monitor1.setState).mockClear();

    manager.onAgentStatusChange("vera", "idle");
    // Agent goes active again before timer fires
    vi.advanceTimersByTime(1000);
    manager.onAgentStatusChange("vera", "building");

    // Fast-forward past original timer
    vi.advanceTimersByTime(5000);

    // setState should have been called with "on" (from re-activation), never "off"
    const calls = vi.mocked(monitor1.setState).mock.calls;
    expect(calls).toEqual([["on"]]);
  });

  it("does nothing for unknown agent", () => {
    // Should not throw
    manager.onAgentStatusChange("unknown_agent", "building");
  });

  it("only affects the target agent's workspace, not others", () => {
    manager.onAgentStatusChange("vera", "building");
    const rexFurniture = (manager as any).workspaceFurniture.get("rex")![0];
    expect(rexFurniture.setState).not.toHaveBeenCalled();
  });

  it("destroy clears all pending timers", () => {
    manager.onAgentStatusChange("vera", "building");
    manager.onAgentStatusChange("vera", "idle");
    manager.destroy();

    // Advance timers — off should NOT fire after destroy
    vi.mocked(monitor1.setState).mockClear();
    vi.advanceTimersByTime(5000);
    expect(monitor1.setState).not.toHaveBeenCalled();
  });
});

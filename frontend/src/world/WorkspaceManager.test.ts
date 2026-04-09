import { describe, it, expect, vi } from "vitest";
import { WorkspaceManager } from "./WorkspaceManager";
import { WORKSPACE_DEFINITIONS } from "./workspaces";

function createMockWorldManager(areas: Record<string, { x: number; y: number; width: number; height: number }> = {}) {
  return {
    getAreaPosition: vi.fn((areaName: string) => {
      const area = areas[areaName];
      if (!area) return null;
      return { x: area.x + area.width / 2, y: area.y + area.height / 2 };
    }),
    getAreas: vi.fn(() => ({ ...areas })),
  };
}

describe("WorkspaceManager", () => {
  it("returns tilemap area center as spawn position when area exists", () => {
    const areas = {
      workspace_vera: { x: 64, y: 64, width: 128, height: 96 },
    };
    const wm = new WorkspaceManager(createMockWorldManager(areas) as any);
    const pos = wm.getAgentSpawnPosition("vera");
    expect(pos).toEqual({ x: 128, y: 112 });
  });

  it("falls back to hardcoded deskPosition when area is missing", () => {
    const wm = new WorkspaceManager(createMockWorldManager({}) as any);
    const pos = wm.getAgentSpawnPosition("vera");
    // vera's deskPosition: { x: 2*32+48=112, y: 6*32=192 }
    expect(pos).toEqual({ x: 112, y: 192 });
  });

  it("returns {0,0} for unknown agent", () => {
    const wm = new WorkspaceManager(createMockWorldManager({}) as any);
    expect(wm.getAgentSpawnPosition("unknown_agent")).toEqual({ x: 0, y: 0 });
  });

  it("returns workspace furniture with absolute positions from tilemap area", () => {
    const areas = {
      workspace_vera: { x: 100, y: 200, width: 128, height: 96 },
    };
    const wm = new WorkspaceManager(createMockWorldManager(areas) as any);
    const items = wm.getWorkspaceFurniture("vera");
    expect(items.length).toBeGreaterThan(0);
    // First item (desk) at offset 0,0 → absolute 100, 200
    expect(items[0]).toEqual({ key: "desk", x: 100, y: 200 });
  });

  it("returns workspace furniture with fallback positions when area is missing", () => {
    const wm = new WorkspaceManager(createMockWorldManager({}) as any);
    const items = wm.getWorkspaceFurniture("vera");
    expect(items.length).toBeGreaterThan(0);
    // Fallback: baseX = deskPosition.x - 48 = 112-48=64, baseY = deskPosition.y - 96 = 192-96=96
    expect(items[0]).toEqual({ key: "desk", x: 64, y: 96 });
  });

  it("returns empty array for unknown agent", () => {
    const wm = new WorkspaceManager(createMockWorldManager({}) as any);
    expect(wm.getWorkspaceFurniture("unknown")).toEqual([]);
  });

  it("has workspace definitions for all 9 agents", () => {
    const expectedAgents = ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok", "alpha", "management"];
    for (const id of expectedAgents) {
      expect(WORKSPACE_DEFINITIONS[id]).toBeDefined();
    }
  });

  it("getAllFurnitureKeys returns unique keys from all workspaces", () => {
    const keys = WorkspaceManager.getAllFurnitureKeys();
    expect(keys.length).toBeGreaterThan(0);
    // Should include personality items
    expect(keys).toContain("desk");
    expect(keys).toContain("disco_ball");
    expect(keys).toContain("dog_bed");
    // No duplicates
    expect(new Set(keys).size).toBe(keys.length);
  });
});

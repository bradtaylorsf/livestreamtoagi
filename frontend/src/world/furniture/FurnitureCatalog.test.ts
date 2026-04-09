import { describe, it, expect } from "vitest";
import { FurnitureCatalog } from "./FurnitureCatalog";
import type { FurnitureManifest } from "./FurnitureManifest";

const SAMPLE_MANIFESTS: FurnitureManifest[] = [
  {
    id: "DESK",
    name: "Standard Desk",
    category: "desks",
    footprint: [3, 2],
    isDesk: true,
    canPlaceOnSurfaces: false,
    zSortOffset: 0,
  },
  {
    id: "MONITOR",
    name: "Monitor",
    category: "electronics",
    footprint: [1, 1],
    isDesk: false,
    states: { off: "monitor_off", on: "monitor_on" },
    canPlaceOnSurfaces: true,
    zSortOffset: 0.001,
  },
  {
    id: "PLANT",
    name: "Plant",
    category: "plants",
    footprint: [1, 1],
    isDesk: false,
    canPlaceOnSurfaces: false,
    zSortOffset: 0,
  },
  {
    id: "CHAIR",
    name: "Office Chair",
    category: "chairs",
    footprint: [1, 1],
    isDesk: false,
    rotations: ["front", "back"],
    canPlaceOnSurfaces: false,
    zSortOffset: 0,
  },
];

describe("FurnitureCatalog", () => {
  it("loads manifests from array", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    expect(catalog.allManifests()).toHaveLength(4);
  });

  it("retrieves manifest by ID", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    const desk = catalog.getManifest("DESK");
    expect(desk).toBeDefined();
    expect(desk!.name).toBe("Standard Desk");
    expect(desk!.isDesk).toBe(true);
  });

  it("returns undefined for unknown ID", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    expect(catalog.getManifest("NONEXISTENT")).toBeUndefined();
  });

  it("filters by category", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    const electronics = catalog.getByCategory("electronics");
    expect(electronics).toHaveLength(1);
    expect(electronics[0].id).toBe("MONITOR");
  });

  it("returns empty array for unused category", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    expect(catalog.getByCategory("surfaces")).toEqual([]);
  });

  it("hasStates returns true for stateful furniture", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    expect(catalog.hasStates("MONITOR")).toBe(true);
  });

  it("hasStates returns false for non-stateful furniture", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    expect(catalog.hasStates("DESK")).toBe(false);
  });

  it("hasStates returns false for unknown ID", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    expect(catalog.hasStates("NONEXISTENT")).toBe(false);
  });

  it("getAllTextureKeys includes default and state textures", () => {
    const catalog = FurnitureCatalog.fromArray(SAMPLE_MANIFESTS);
    const keys = catalog.getAllTextureKeys();
    expect(keys).toContain("monitor_off");
    expect(keys).toContain("monitor_on");
    expect(keys).toContain("desk");
    expect(keys).toContain("plant");
  });

  it("fromCache handles missing cache gracefully", () => {
    const mockScene = {
      cache: {
        json: {
          get: () => null,
        },
      },
    };
    const catalog = FurnitureCatalog.fromCache(mockScene as any, "missing");
    expect(catalog.allManifests()).toHaveLength(0);
  });
});

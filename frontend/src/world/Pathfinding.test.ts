import { describe, it, expect } from "vitest";
import {
  findPath,
  pixelToTile,
  tileToPixel,
  buildWalkabilityGrid,
  updateWalkability,
  type WalkabilityGrid,
} from "./Pathfinding";

/** Helper: create a grid from a string template (. = walkable, # = blocked). */
function gridFromString(template: string): WalkabilityGrid {
  return template
    .trim()
    .split("\n")
    .map((row) => [...row.trim()].map((c) => c === "."));
}

describe("findPath", () => {
  it("finds straight path on open grid", () => {
    const grid = gridFromString(`
      .....
      .....
      .....
    `);
    const path = findPath(grid, { tx: 0, ty: 0 }, { tx: 4, ty: 0 });
    expect(path).not.toBeNull();
    expect(path!.length).toBe(5);
    expect(path![0]).toEqual({ tx: 0, ty: 0 });
    expect(path![4]).toEqual({ tx: 4, ty: 0 });
  });

  it("navigates around a wall", () => {
    const grid = gridFromString(`
      ...
      .#.
      ...
    `);
    const path = findPath(grid, { tx: 0, ty: 1 }, { tx: 2, ty: 1 });
    expect(path).not.toBeNull();
    // Must go around the wall — path length should be > 3
    expect(path!.length).toBeGreaterThan(3);
    // Should not pass through the wall at (1,1)
    const passesWall = path!.some((p) => p.tx === 1 && p.ty === 1);
    expect(passesWall).toBe(false);
  });

  it("returns null when no path exists", () => {
    const grid = gridFromString(`
      .#.
      .#.
      .#.
    `);
    const path = findPath(grid, { tx: 0, ty: 0 }, { tx: 2, ty: 0 });
    expect(path).toBeNull();
  });

  it("returns single-element path when start equals end", () => {
    const grid = gridFromString(`
      ...
      ...
    `);
    const path = findPath(grid, { tx: 1, ty: 0 }, { tx: 1, ty: 0 });
    expect(path).toEqual([{ tx: 1, ty: 0 }]);
  });

  it("returns null when start is blocked", () => {
    const grid = gridFromString(`
      #..
      ...
    `);
    const path = findPath(grid, { tx: 0, ty: 0 }, { tx: 2, ty: 0 });
    expect(path).toBeNull();
  });

  it("returns null when end is blocked", () => {
    const grid = gridFromString(`
      ..#
      ...
    `);
    const path = findPath(grid, { tx: 0, ty: 0 }, { tx: 2, ty: 0 });
    expect(path).toBeNull();
  });

  it("returns null for out-of-bounds coordinates", () => {
    const grid = gridFromString(`
      ...
      ...
    `);
    expect(findPath(grid, { tx: -1, ty: 0 }, { tx: 2, ty: 0 })).toBeNull();
    expect(findPath(grid, { tx: 0, ty: 0 }, { tx: 5, ty: 0 })).toBeNull();
  });

  it("uses only 4-directional movement (no diagonals)", () => {
    const grid = gridFromString(`
      ...
      ...
      ...
    `);
    const path = findPath(grid, { tx: 0, ty: 0 }, { tx: 2, ty: 2 });
    expect(path).not.toBeNull();
    // Each step should differ by exactly 1 in either x or y (not both)
    for (let i = 1; i < path!.length; i++) {
      const dx = Math.abs(path![i].tx - path![i - 1].tx);
      const dy = Math.abs(path![i].ty - path![i - 1].ty);
      expect(dx + dy).toBe(1);
    }
  });

  it("finds path on realistic 40x22 grid size", () => {
    // Create a 40x22 open grid with some obstacles
    const grid: WalkabilityGrid = Array.from({ length: 22 }, () =>
      Array(40).fill(true),
    );
    // Add a wall
    for (let y = 0; y < 20; y++) {
      grid[y][20] = false;
    }
    const path = findPath(grid, { tx: 0, ty: 0 }, { tx: 39, ty: 0 });
    expect(path).not.toBeNull();
    // Must go around the wall via bottom
    expect(path!.some((p) => p.ty >= 20)).toBe(true);
  });
});

describe("pixelToTile", () => {
  it("converts pixel to tile coordinates", () => {
    expect(pixelToTile(48, 64, 32)).toEqual({ tx: 1, ty: 2 });
  });

  it("floors fractional positions", () => {
    expect(pixelToTile(33, 33, 32)).toEqual({ tx: 1, ty: 1 });
  });

  it("handles origin", () => {
    expect(pixelToTile(0, 0, 32)).toEqual({ tx: 0, ty: 0 });
  });
});

describe("tileToPixel", () => {
  it("converts tile to center pixel coordinates", () => {
    expect(tileToPixel(1, 2, 32)).toEqual({ x: 48, y: 80 });
  });

  it("centers on tile", () => {
    const result = tileToPixel(0, 0, 32);
    expect(result).toEqual({ x: 16, y: 16 });
  });
});

describe("buildWalkabilityGrid", () => {
  it("builds grid from collision layer", () => {
    const mockLayer = {
      getTileAt: (x: number, y: number) => {
        // Row 0: all walkable (null tiles)
        if (y === 0) return null;
        // Row 1: blocked at x=1
        if (y === 1 && x === 1) return { index: 1 };
        return { index: 0 };
      },
    };

    const grid = buildWalkabilityGrid(mockLayer, 3, 2);
    expect(grid).toEqual([
      [true, true, true],   // row 0: all null (walkable)
      [true, false, true],  // row 1: x=1 blocked (index 1)
    ]);
  });

  it("treats negative tile indices as walkable", () => {
    const mockLayer = {
      getTileAt: () => ({ index: -1 }),
    };
    const grid = buildWalkabilityGrid(mockLayer, 2, 2);
    expect(grid).toEqual([
      [true, true],
      [true, true],
    ]);
  });
});

describe("updateWalkability", () => {
  it("blocks specified tiles", () => {
    const grid = gridFromString(`
      ...
      ...
      ...
    `);
    updateWalkability(grid, [{ tx: 1, ty: 1 }], false);
    expect(grid[1][1]).toBe(false);
    // Others unchanged
    expect(grid[0][0]).toBe(true);
    expect(grid[0][1]).toBe(true);
  });

  it("unblocks specified tiles", () => {
    const grid = gridFromString(`
      .#.
      ...
    `);
    expect(grid[0][1]).toBe(false);
    updateWalkability(grid, [{ tx: 1, ty: 0 }], true);
    expect(grid[0][1]).toBe(true);
  });

  it("handles multiple tiles at once", () => {
    const grid = gridFromString(`
      ...
      ...
    `);
    updateWalkability(grid, [
      { tx: 0, ty: 0 },
      { tx: 1, ty: 0 },
      { tx: 2, ty: 0 },
    ], false);
    expect(grid[0]).toEqual([false, false, false]);
    expect(grid[1]).toEqual([true, true, true]);
  });

  it("ignores out-of-bounds coordinates", () => {
    const grid = gridFromString(`
      ..
      ..
    `);
    // Should not throw
    updateWalkability(grid, [{ tx: -1, ty: 0 }, { tx: 5, ty: 0 }, { tx: 0, ty: 5 }], false);
    expect(grid[0]).toEqual([true, true]);
  });

  it("blocks tiles so pathfinding routes around them", () => {
    const grid = gridFromString(`
      .....
      .....
      .....
    `);
    // Block the middle row center
    updateWalkability(grid, [
      { tx: 1, ty: 1 },
      { tx: 2, ty: 1 },
      { tx: 3, ty: 1 },
    ], false);

    // Path from left to right must go around
    const path = findPath(grid, { tx: 0, ty: 1 }, { tx: 4, ty: 1 });
    expect(path).not.toBeNull();
    // Path should detour through row 0 or 2
    expect(path!.some((p) => p.ty !== 1)).toBe(true);
  });
});

/**
 * A* pathfinding on a tile-based grid.
 * Pure algorithm — no Phaser dependency in core functions.
 */

export interface TileCoord {
  tx: number;
  ty: number;
}

/** true = walkable, false = blocked */
export type WalkabilityGrid = boolean[][];

interface AStarNode {
  tx: number;
  ty: number;
  g: number; // cost from start
  h: number; // heuristic to end
  f: number; // g + h
  parent: AStarNode | null;
}

/** 4-directional neighbors (no diagonals — matches walk animations). */
const NEIGHBORS = [
  { dx: 0, dy: -1 }, // up
  { dx: 0, dy: 1 },  // down
  { dx: -1, dy: 0 }, // left
  { dx: 1, dy: 0 },  // right
];

function manhattanDistance(ax: number, ay: number, bx: number, by: number): number {
  return Math.abs(ax - bx) + Math.abs(ay - by);
}

/**
 * Build a walkability grid from a Phaser collision layer.
 * Tiles with index -1 or 0 are walkable; all others are blocked.
 */
export function buildWalkabilityGrid(
  collisionLayer: { getTileAt: (x: number, y: number) => { index: number } | null },
  width: number,
  height: number,
): WalkabilityGrid {
  const grid: WalkabilityGrid = [];
  for (let y = 0; y < height; y++) {
    const row: boolean[] = [];
    for (let x = 0; x < width; x++) {
      const tile = collisionLayer.getTileAt(x, y);
      // No tile or tile index -1/0 means walkable
      row.push(!tile || tile.index <= 0);
    }
    grid.push(row);
  }
  return grid;
}

/**
 * A* pathfinding. Returns array of tile coordinates from start to end (inclusive),
 * or null if no path exists.
 */
export function findPath(
  grid: WalkabilityGrid,
  start: TileCoord,
  end: TileCoord,
): TileCoord[] | null {
  const height = grid.length;
  if (height === 0) return null;
  const width = grid[0].length;

  // Bounds check
  if (
    start.tx < 0 || start.tx >= width || start.ty < 0 || start.ty >= height ||
    end.tx < 0 || end.tx >= width || end.ty < 0 || end.ty >= height
  ) {
    return null;
  }

  // Start or end blocked
  if (!grid[start.ty][start.tx] || !grid[end.ty][end.tx]) {
    return null;
  }

  // Already there
  if (start.tx === end.tx && start.ty === end.ty) {
    return [{ tx: start.tx, ty: start.ty }];
  }

  const openSet: AStarNode[] = [];
  const closedSet = new Set<string>();

  const key = (tx: number, ty: number) => `${tx},${ty}`;

  const startNode: AStarNode = {
    tx: start.tx,
    ty: start.ty,
    g: 0,
    h: manhattanDistance(start.tx, start.ty, end.tx, end.ty),
    f: manhattanDistance(start.tx, start.ty, end.tx, end.ty),
    parent: null,
  };
  openSet.push(startNode);

  // Track best g-score per tile for open set deduplication
  const bestG = new Map<string, number>();
  bestG.set(key(start.tx, start.ty), 0);

  while (openSet.length > 0) {
    // Find node with lowest f (simple linear scan — fine for 40x22 grid)
    let bestIdx = 0;
    for (let i = 1; i < openSet.length; i++) {
      if (openSet[i].f < openSet[bestIdx].f) {
        bestIdx = i;
      }
    }
    const current = openSet[bestIdx];
    openSet.splice(bestIdx, 1);

    const currentKey = key(current.tx, current.ty);
    if (closedSet.has(currentKey)) continue;
    closedSet.add(currentKey);

    // Reached the goal
    if (current.tx === end.tx && current.ty === end.ty) {
      const path: TileCoord[] = [];
      let node: AStarNode | null = current;
      while (node) {
        path.push({ tx: node.tx, ty: node.ty });
        node = node.parent;
      }
      path.reverse();
      return path;
    }

    // Expand neighbors
    for (const { dx, dy } of NEIGHBORS) {
      const nx = current.tx + dx;
      const ny = current.ty + dy;

      if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
      if (!grid[ny][nx]) continue;

      const nKey = key(nx, ny);
      if (closedSet.has(nKey)) continue;

      const g = current.g + 1;
      const existingG = bestG.get(nKey);
      if (existingG !== undefined && g >= existingG) continue;

      bestG.set(nKey, g);
      const h = manhattanDistance(nx, ny, end.tx, end.ty);
      openSet.push({
        tx: nx,
        ty: ny,
        g,
        h,
        f: g + h,
        parent: current,
      });
    }
  }

  return null; // No path found
}

/** Convert pixel coordinates to tile coordinates. */
export function pixelToTile(px: number, py: number, tileSize: number): TileCoord {
  return {
    tx: Math.floor(px / tileSize),
    ty: Math.floor(py / tileSize),
  };
}

/** Convert tile coordinates to pixel coordinates (center of tile). */
export function tileToPixel(tx: number, ty: number, tileSize: number): { x: number; y: number } {
  return {
    x: tx * tileSize + tileSize / 2,
    y: ty * tileSize + tileSize / 2,
  };
}

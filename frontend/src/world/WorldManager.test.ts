import { describe, it, expect, vi, beforeEach } from "vitest";
import { WorldManager } from "./WorldManager";

// Minimal Phaser scene mock
function createMockScene() {
  const layers: Array<{
    layer: { name: string };
    setCollisionByExclusion: ReturnType<typeof vi.fn>;
    setVisible: ReturnType<typeof vi.fn>;
    destroy: ReturnType<typeof vi.fn>;
  }> = [];

  const tilemapData = {
    width: 40,
    height: 22,
    tilewidth: 32,
    tileheight: 32,
    tilesets: [{ name: "floor", firstgid: 1 }],
    layers: [
      { name: "ground", data: [] },
      { name: "furniture", data: [] },
      { name: "collision", data: [] },
    ],
    areas: {
      desk_vera: { x: 128, y: 128, width: 96, height: 64 },
      meeting_area: { x: 768, y: 96, width: 192, height: 160 },
    },
  };

  const mockTilemap = {
    width: 40,
    height: 22,
    widthInPixels: 1280,
    heightInPixels: 704,
    tilesets: [],
    addTilesetImage: vi.fn(),
    createLayer: vi.fn((_name: string, _tilesets: unknown) => {
      const layer = {
        layer: { name: _name },
        setCollisionByExclusion: vi.fn(),
        setVisible: vi.fn(),
        setAlpha: vi.fn(),
        setPosition: vi.fn(),
        getTileAt: vi.fn(() => null), // all tiles walkable by default
        destroy: vi.fn(),
      };
      layers.push(layer);
      return layer;
    }),
    destroy: vi.fn(),
  };

  const scene = {
    cache: {
      tilemap: {
        get: vi.fn((key: string) => {
          if (key === "tilemap_office") {
            return { data: tilemapData };
          }
          return null;
        }),
      },
    },
    make: {
      tilemap: vi.fn(() => mockTilemap),
    },
    cameras: {
      main: {
        width: 1280,
        height: 720,
        setBounds: vi.fn(),
        setZoom: vi.fn(),
        centerOn: vi.fn(),
      },
    },
  };

  return { scene, mockTilemap, layers };
}

describe("WorldManager", () => {
  let worldManager: WorldManager;
  let mockScene: ReturnType<typeof createMockScene>;

  beforeEach(() => {
    mockScene = createMockScene();
    worldManager = new WorldManager(mockScene.scene as any);
  });

  it("loads the office chunk on create", () => {
    worldManager.create();
    expect(mockScene.scene.make.tilemap).toHaveBeenCalled();
  });

  it("provides area positions", () => {
    worldManager.create();
    const pos = worldManager.getAreaPosition("desk_vera");
    expect(pos).not.toBeNull();
    // Center of desk_vera: x=128+96/2=176, y=128+64/2=160
    expect(pos!.x).toBe(176);
    expect(pos!.y).toBe(160);
  });

  it("returns null for unknown area", () => {
    worldManager.create();
    expect(worldManager.getAreaPosition("nonexistent")).toBeNull();
  });

  it("hides collision layer", () => {
    worldManager.create();
    const collisionLayer = mockScene.layers.find(
      (l) => l.layer.name === "collision",
    );
    expect(collisionLayer).toBeDefined();
    expect(collisionLayer!.setVisible).toHaveBeenCalledWith(false);
    expect(collisionLayer!.setCollisionByExclusion).toHaveBeenCalledWith([
      -1, 0,
    ]);
  });

  it("configures camera bounds to world size", () => {
    worldManager.create();
    expect(mockScene.scene.cameras.main.setBounds).toHaveBeenCalledWith(
      -16,
      -16,
      1312,
      736,
    );
  });

  it("returns world size", () => {
    worldManager.create();
    const size = worldManager.getWorldSize();
    expect(size.width).toBe(1280);
    expect(size.height).toBe(704);
  });

  it("returns all areas", () => {
    worldManager.create();
    const areas = worldManager.getAreas();
    expect(Object.keys(areas)).toContain("desk_vera");
    expect(Object.keys(areas)).toContain("meeting_area");
  });

  it("cleans up on destroy", () => {
    worldManager.create();
    worldManager.destroy();
    // Layers should be destroyed
    for (const layer of mockScene.layers) {
      expect(layer.destroy).toHaveBeenCalled();
    }
  });

  describe("furniture collision", () => {
    it("registerFurnitureCollision marks tiles as non-walkable", () => {
      // Provide a collision layer mock with getTileAt so grid gets built
      let layerMockRef: any = null;
      mockScene.mockTilemap.createLayer = vi.fn((_name: string) => {
        const layer: any = {
          layer: { name: _name },
          setCollisionByExclusion: vi.fn(),
          setVisible: vi.fn(),
          destroy: vi.fn(),
          setAlpha: vi.fn(),
          setPosition: vi.fn(),
        };
        if (_name === "collision") {
          layer.getTileAt = (_x: number, _y: number) => null; // all walkable
          layerMockRef = layer;
        }
        mockScene.layers.push(layer);
        return layer;
      });

      worldManager = new WorldManager(mockScene.scene as any);
      worldManager.create();

      const grid = worldManager.getWalkabilityGrid();
      expect(grid).not.toBeNull();
      // Tile at (3,3) should be walkable initially
      expect(grid![3][3]).toBe(true);

      // Register furniture at pixel (96, 96) with 2x2 footprint
      worldManager.registerFurnitureCollision(96, 96, 2, 2);

      // Tile (3,3), (4,3), (3,4), (4,4) should be blocked
      expect(grid![3][3]).toBe(false);
      expect(grid![3][4]).toBe(false);
      expect(grid![4][3]).toBe(false);
      expect(grid![4][4]).toBe(false);

      // Adjacent tiles should still be walkable
      expect(grid![3][2]).toBe(true);
      expect(grid![2][3]).toBe(true);
    });

    it("markTilesWalkable restores walkability", () => {
      let layerMockRef: any = null;
      mockScene.mockTilemap.createLayer = vi.fn((_name: string) => {
        const layer: any = {
          layer: { name: _name },
          setCollisionByExclusion: vi.fn(),
          setVisible: vi.fn(),
          destroy: vi.fn(),
          setAlpha: vi.fn(),
          setPosition: vi.fn(),
        };
        if (_name === "collision") {
          layer.getTileAt = () => null;
          layerMockRef = layer;
        }
        mockScene.layers.push(layer);
        return layer;
      });

      worldManager = new WorldManager(mockScene.scene as any);
      worldManager.create();

      const grid = worldManager.getWalkabilityGrid()!;
      worldManager.markTilesBlocked([{ tx: 5, ty: 5 }]);
      expect(grid[5][5]).toBe(false);

      worldManager.markTilesWalkable([{ tx: 5, ty: 5 }]);
      expect(grid[5][5]).toBe(true);
    });
  });
});

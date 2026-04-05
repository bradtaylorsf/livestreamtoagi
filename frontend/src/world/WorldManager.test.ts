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
    widthInPixels: 1280,
    heightInPixels: 704,
    tilesets: [],
    addTilesetImage: vi.fn(),
    createLayer: vi.fn((_name: string, _tilesets: unknown) => {
      const layer = {
        layer: { name: _name },
        setCollisionByExclusion: vi.fn(),
        setVisible: vi.fn(),
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
      0,
      0,
      1280,
      704,
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
});

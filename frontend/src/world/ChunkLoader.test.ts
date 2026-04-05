import { describe, it, expect, vi, beforeEach } from "vitest";
import { ChunkLoader } from "./ChunkLoader";

function createMockScene() {
  const mockTilemap = {
    widthInPixels: 320,
    heightInPixels: 256,
    tilesets: [],
    addTilesetImage: vi.fn(),
    createLayer: vi.fn((_name: string) => ({
      layer: { name: _name },
      destroy: vi.fn(),
    })),
    destroy: vi.fn(),
  };

  const tilemapData = {
    width: 10,
    height: 8,
    tilewidth: 32,
    tileheight: 32,
    tilesets: [{ name: "floor", firstgid: 1 }],
    layers: [
      { name: "ground", data: [] },
      { name: "collision", data: [] },
    ],
  };

  return {
    scene: {
      cache: {
        tilemap: {
          get: vi.fn((key: string) => {
            if (key === "tilemap_test") {
              return { data: tilemapData };
            }
            return null;
          }),
        },
      },
      make: {
        tilemap: vi.fn(() => mockTilemap),
      },
    },
    mockTilemap,
  };
}

describe("ChunkLoader", () => {
  let loader: ChunkLoader;
  let mockScene: ReturnType<typeof createMockScene>;

  beforeEach(() => {
    mockScene = createMockScene();
    loader = new ChunkLoader(mockScene.scene as any);
  });

  it("loads a chunk from cache", () => {
    const chunk = loader.loadChunk("test");
    expect(chunk).not.toBeNull();
    expect(chunk!.id).toBe("test");
    expect(chunk!.layers).toHaveLength(2);
  });

  it("returns null for missing chunk", () => {
    const chunk = loader.loadChunk("nonexistent");
    expect(chunk).toBeNull();
  });

  it("returns cached chunk on second load", () => {
    const chunk1 = loader.loadChunk("test");
    const chunk2 = loader.loadChunk("test");
    expect(chunk1).toBe(chunk2);
    // tilemap should only be created once
    expect(mockScene.scene.make.tilemap).toHaveBeenCalledTimes(1);
  });

  it("tracks loaded chunks", () => {
    expect(loader.getLoadedChunks()).toHaveLength(0);
    loader.loadChunk("test");
    expect(loader.getLoadedChunks()).toEqual(["test"]);
  });

  it("unloads chunk and frees resources", () => {
    const chunk = loader.loadChunk("test");
    expect(chunk).not.toBeNull();

    loader.unloadChunk("test");
    expect(loader.getLoadedChunks()).toHaveLength(0);
    expect(mockScene.mockTilemap.destroy).toHaveBeenCalled();
  });

  it("unloading nonexistent chunk is a no-op", () => {
    loader.unloadChunk("nonexistent");
    expect(loader.getLoadedChunks()).toHaveLength(0);
  });

  it("destroy cleans up all chunks", () => {
    loader.loadChunk("test");
    loader.destroy();
    expect(loader.getLoadedChunks()).toHaveLength(0);
  });
});

import Phaser from "phaser";

export interface ChunkData {
  id: string;
  tilemap: Phaser.Tilemaps.Tilemap;
  layers: Phaser.Tilemaps.TilemapLayer[];
}

interface TilemapJSON {
  width: number;
  height: number;
  tilewidth: number;
  tileheight: number;
  tilesets: Array<{ name: string; firstgid: number; image?: string }>;
  layers: Array<{ name: string; data: number[] }>;
  areas?: Record<string, { x: number; y: number; width: number; height: number }>;
}

/**
 * Manages loading and unloading of tilemap chunks.
 * For the office, the entire space is a single chunk.
 * Designed for future multi-chunk world expansion.
 */
export class ChunkLoader {
  private scene: Phaser.Scene;
  private chunks: Map<string, ChunkData> = new Map();

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
  }

  /**
   * Load a chunk from a backend API URL. Fetches tilemap JSON, registers it
   * in Phaser cache, loads tileset, then creates layers at the given pixel offset.
   */
  async loadChunkFromURL(
    chunkId: string,
    tilemapUrl: string,
    tilesetUrl: string,
    offset: { x: number; y: number },
  ): Promise<ChunkData | null> {
    if (this.chunks.has(chunkId)) {
      return this.chunks.get(chunkId)!;
    }

    try {
      const response = await fetch(tilemapUrl);
      if (!response.ok) return null;
      const chunkData = await response.json();

      // Build a minimal Tiled-format tilemap JSON from the chunk data
      const tilemapJSON: TilemapJSON = {
        width: chunkData.width ?? 10,
        height: chunkData.height ?? 10,
        tilewidth: 32,
        tileheight: 32,
        tilesets: [{ name: `tileset_${chunkId}`, firstgid: 1, image: `tileset_${chunkId}` }],
        layers: [],
        areas: chunkData.areas,
      };

      // Convert tile_data into layers
      if (chunkData.tile_data?.tiles) {
        tilemapJSON.layers.push({
          name: "Ground",
          data: (chunkData.tile_data.tiles as number[][]).flat(),
        });
      }

      // Register in Phaser cache
      const jsonKey = `tilemap_${chunkId}`;
      this.scene.cache.tilemap.add(jsonKey, { format: 1, data: tilemapJSON });

      // Load tileset image
      return new Promise<ChunkData | null>((resolve) => {
        const tilesetKey = `tileset_${chunkId}`;
        if (!this.scene.textures.exists(tilesetKey)) {
          this.scene.load.image(tilesetKey, tilesetUrl);
          this.scene.load.once("complete", () => {
            const chunk = this.loadChunk(chunkId);
            if (chunk) {
              // Apply pixel offset to all layers
              for (const layer of chunk.layers) {
                layer.setPosition(offset.x * 32, offset.y * 32);
              }
            }
            resolve(chunk);
          });
          this.scene.load.start();
        } else {
          const chunk = this.loadChunk(chunkId);
          if (chunk) {
            for (const layer of chunk.layers) {
              layer.setPosition(offset.x * 32, offset.y * 32);
            }
          }
          resolve(chunk);
        }
      });
    } catch (err) {
      console.warn(`Failed to load chunk from URL: ${tilemapUrl}`, err);
      return null;
    }
  }

  loadChunk(chunkId: string): ChunkData | null {
    if (this.chunks.has(chunkId)) {
      return this.chunks.get(chunkId)!;
    }

    const jsonKey = `tilemap_${chunkId}`;
    const cacheEntry = this.scene.cache.tilemap.get(jsonKey);
    if (!cacheEntry) {
      return null;
    }
    const tilemapData = cacheEntry.data as TilemapJSON;

    const tilemap = this.scene.make.tilemap({ key: jsonKey });

    // Add tilesets (image key may differ from tileset name)
    for (const ts of tilemapData.tilesets) {
      tilemap.addTilesetImage(ts.name, ts.image ?? ts.name);
    }

    // Create layers
    const allTilesets = tilemap.tilesets;
    const layers: Phaser.Tilemaps.TilemapLayer[] = [];
    for (const layerData of tilemapData.layers) {
      const layer = tilemap.createLayer(layerData.name, allTilesets);
      if (layer) {
        layers.push(layer);
      }
    }

    const chunk: ChunkData = { id: chunkId, tilemap, layers };
    this.chunks.set(chunkId, chunk);
    return chunk;
  }

  unloadChunk(chunkId: string): void {
    const chunk = this.chunks.get(chunkId);
    if (!chunk) return;

    for (const layer of chunk.layers) {
      layer.destroy();
    }
    chunk.tilemap.destroy();
    this.chunks.delete(chunkId);
  }

  getLoadedChunks(): string[] {
    return Array.from(this.chunks.keys());
  }

  getChunk(chunkId: string): ChunkData | null {
    return this.chunks.get(chunkId) ?? null;
  }

  destroy(): void {
    for (const chunkId of this.chunks.keys()) {
      this.unloadChunk(chunkId);
    }
  }
}

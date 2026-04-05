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
  tilesets: Array<{ name: string; firstgid: number }>;
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

    // Add tilesets
    for (const ts of tilemapData.tilesets) {
      tilemap.addTilesetImage(ts.name, ts.name);
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

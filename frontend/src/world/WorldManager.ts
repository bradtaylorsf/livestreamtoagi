import Phaser from "phaser";
import { ChunkLoader } from "./ChunkLoader";

interface AreaRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface TilemapAreas {
  [name: string]: AreaRect;
}

/**
 * High-level world management. Loads the office chunk,
 * configures collision and camera, provides area lookups.
 */
export class WorldManager {
  private scene: Phaser.Scene;
  private chunkLoader: ChunkLoader;
  private areas: TilemapAreas = {};
  private collisionLayer: Phaser.Tilemaps.TilemapLayer | null = null;
  private worldWidth = 0;
  private worldHeight = 0;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    this.chunkLoader = new ChunkLoader(scene);
  }

  create(): void {
    const chunk = this.chunkLoader.loadChunk("office");
    if (!chunk) {
      return;
    }

    const tilemap = chunk.tilemap;
    this.worldWidth = tilemap.widthInPixels;
    this.worldHeight = tilemap.heightInPixels;

    // Find collision layer
    for (const layer of chunk.layers) {
      if (layer.layer.name === "collision") {
        this.collisionLayer = layer;
        // Mark any non-zero tile as colliding
        layer.setCollisionByExclusion([-1, 0]);
        layer.setVisible(false);
        break;
      }
    }

    // Load areas from tilemap JSON cache
    const cacheEntry = this.scene.cache.tilemap.get("tilemap_office");
    if (cacheEntry?.data?.areas) {
      this.areas = cacheEntry.data.areas as TilemapAreas;
    }

    // Configure camera
    const cam = this.scene.cameras.main;
    cam.setBounds(0, 0, this.worldWidth, this.worldHeight);

    // Zoom to fit the full office in view
    const zoomX = cam.width / this.worldWidth;
    const zoomY = cam.height / this.worldHeight;
    const zoom = Math.min(zoomX, zoomY, 1);
    cam.setZoom(zoom);
    cam.centerOn(this.worldWidth / 2, this.worldHeight / 2);
  }

  getCollisionLayer(): Phaser.Tilemaps.TilemapLayer | null {
    return this.collisionLayer;
  }

  getAreaPosition(areaName: string): { x: number; y: number } | null {
    const area = this.areas[areaName];
    if (!area) return null;
    // Return center of area in pixel coordinates
    return {
      x: area.x + area.width / 2,
      y: area.y + area.height / 2,
    };
  }

  getAreas(): TilemapAreas {
    return { ...this.areas };
  }

  getWorldSize(): { width: number; height: number } {
    return { width: this.worldWidth, height: this.worldHeight };
  }

  updateVisibleChunks(_cameraX: number, _cameraY: number): void {
    // For single-chunk office, nothing to load/unload.
    // Future: load/unload chunks based on camera viewport.
  }

  destroy(): void {
    this.chunkLoader.destroy();
  }
}

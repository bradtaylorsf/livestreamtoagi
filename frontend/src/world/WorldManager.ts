import Phaser from "phaser";
import { ChunkLoader } from "./ChunkLoader";
import {
  buildWalkabilityGrid,
  findPath,
  pixelToTile,
  type TileCoord,
  type WalkabilityGrid,
} from "./Pathfinding";

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
  private walkabilityGrid: WalkabilityGrid | null = null;

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
      if (layer.layer.name.toLowerCase() === "collision") {
        this.collisionLayer = layer;
        // Mark any non-zero tile as colliding
        layer.setCollisionByExclusion([-1, 0]);
        layer.setVisible(false);
        break;
      }
    }

    // Build walkability grid from collision layer
    if (this.collisionLayer) {
      this.walkabilityGrid = buildWalkabilityGrid(
        this.collisionLayer,
        tilemap.width,
        tilemap.height,
      );
    }

    // Load areas from tilemap JSON cache (top-level or Tiled properties)
    const cacheEntry = this.scene.cache.tilemap.get("tilemap_office");
    if (cacheEntry?.data?.areas) {
      this.areas = cacheEntry.data.areas as TilemapAreas;
    } else if (cacheEntry?.data?.properties) {
      const areasProp = (cacheEntry.data.properties as any[]).find(
        (p: any) => p.name === "areas",
      );
      if (areasProp?.value) {
        this.areas = typeof areasProp.value === "string"
          ? JSON.parse(areasProp.value)
          : areasProp.value;
      }
    }

    // Configure camera — zoom to fit entire office in viewport with padding
    const cam = this.scene.cameras.main;
    const pad = 16; // pixels of padding around the edges
    cam.setBounds(-pad, -pad, this.worldWidth + pad * 2, this.worldHeight + pad * 2);
    const zoomX = cam.width / (this.worldWidth + pad * 2);
    const zoomY = cam.height / (this.worldHeight + pad * 2);
    cam.setZoom(Math.min(zoomX, zoomY));
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

  getWalkabilityGrid(): WalkabilityGrid | null {
    return this.walkabilityGrid;
  }

  getTileSize(): number {
    return 32;
  }

  /**
   * Find a path between two pixel positions using A*.
   * Returns tile coordinates array or null if no path exists.
   */
  findPath(fromX: number, fromY: number, toX: number, toY: number): TileCoord[] | null {
    if (!this.walkabilityGrid) return null;
    const tileSize = this.getTileSize();
    const start = pixelToTile(fromX, fromY, tileSize);
    const end = pixelToTile(toX, toY, tileSize);
    return findPath(this.walkabilityGrid, start, end);
  }

  /**
   * Dynamically load a new world zone chunk. If the tilemap JSON is already
   * in the Phaser cache, loads immediately. Otherwise triggers async preload.
   * After loading, pans camera to reveal the new area.
   */
  expandWorld(zone: string, description: string): void {
    const jsonKey = `tilemap_${zone}`;
    const cacheEntry = this.scene.cache.tilemap.get(jsonKey);

    if (cacheEntry) {
      // Tilemap already cached — load chunk directly
      this.loadExpansionChunk(zone, description);
    } else {
      // Dynamic tilemap load: preload then create
      this.scene.load.tilemapTiledJSON(jsonKey, `assets/tilesets/${zone}/tilemap_${zone}.json`);
      this.scene.load.once("complete", () => {
        this.loadExpansionChunk(zone, description);
      });
      this.scene.load.start();
    }
  }

  private loadExpansionChunk(zone: string, description: string): void {
    const chunk = this.chunkLoader.loadChunk(zone);
    if (!chunk) {
      console.warn(`Failed to load expansion chunk: ${zone}`);
      return;
    }

    // Pan camera to center of new chunk
    const centerX = chunk.tilemap.widthInPixels / 2;
    const centerY = chunk.tilemap.heightInPixels / 2;
    this.scene.cameras.main.pan(centerX, centerY, 1000, "Power2");

    // Show expansion notification
    const notifyText = this.scene.add.text(
      this.scene.cameras.main.centerX,
      this.scene.cameras.main.centerY + 60,
      `World expanded: ${description}`,
      {
        fontSize: "12px",
        color: "#ffffff",
        fontFamily: "monospace",
        backgroundColor: "#1a1a2ecc",
        padding: { x: 8, y: 4 },
        stroke: "#44cc44",
        strokeThickness: 1,
      },
    );
    notifyText.setOrigin(0.5, 0.5);
    notifyText.setScrollFactor(0);
    notifyText.setDepth(50);

    this.scene.tweens.add({
      targets: notifyText,
      alpha: 0,
      delay: 3000,
      duration: 1000,
      onComplete: () => notifyText.destroy(),
    });
  }

  updateVisibleChunks(_cameraX: number, _cameraY: number): void {
    // For single-chunk office, nothing to load/unload.
    // Future: load/unload chunks based on camera viewport.
  }

  destroy(): void {
    this.chunkLoader.destroy();
  }
}

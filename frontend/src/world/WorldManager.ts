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
  private worldBounds = { minX: 0, minY: 0, maxX: 0, maxY: 0 };

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

    // Track world bounds for camera expansion
    this.worldBounds = {
      minX: 0, minY: 0,
      maxX: this.worldWidth, maxY: this.worldHeight,
    };

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
   * Dynamically load a new world zone chunk. Supports two modes:
   * 1. URL-based: fetches tilemap from backend API (used for agent-built chunks)
   * 2. Cache-based: loads from Phaser cache or local assets (legacy/preloaded chunks)
   * After loading, expands camera bounds, pans to reveal, and applies fade-in.
   */
  expandWorld(
    zone: string,
    description: string,
    options?: {
      tilemapUrl?: string;
      tilesetUrl?: string;
      offset?: { x: number; y: number };
      agentId?: string;
    },
  ): void {
    if (options?.tilemapUrl && options?.tilesetUrl) {
      // URL-based dynamic loading from backend
      const offset = options.offset ?? { x: 0, y: 0 };
      this.chunkLoader
        .loadChunkFromURL(zone, options.tilemapUrl, options.tilesetUrl, offset)
        .then((chunk) => {
          if (chunk) {
            this.onChunkLoaded(chunk, description, offset);
          } else {
            console.warn(`Failed to load expansion chunk from URL: ${zone}`);
          }
        });
    } else {
      // Legacy: cache-based loading
      const jsonKey = `tilemap_${zone}`;
      const cacheEntry = this.scene.cache.tilemap.get(jsonKey);

      if (cacheEntry) {
        this.loadExpansionChunk(zone, description);
      } else {
        this.scene.load.tilemapTiledJSON(jsonKey, `assets/tilesets/${zone}/tilemap_${zone}.json`);
        this.scene.load.once("complete", () => {
          this.loadExpansionChunk(zone, description);
        });
        this.scene.load.start();
      }
    }
  }

  private loadExpansionChunk(zone: string, description: string): void {
    const chunk = this.chunkLoader.loadChunk(zone);
    if (!chunk) {
      console.warn(`Failed to load expansion chunk: ${zone}`);
      return;
    }
    this.onChunkLoaded(chunk, description, { x: 0, y: 0 });
  }

  private onChunkLoaded(
    chunk: import("./ChunkLoader").ChunkData,
    description: string,
    offset: { x: number; y: number },
  ): void {
    const tileSize = this.getTileSize();
    const chunkPixelX = offset.x * tileSize;
    const chunkPixelY = offset.y * tileSize;
    const chunkW = chunk.tilemap.widthInPixels;
    const chunkH = chunk.tilemap.heightInPixels;

    // Expand world bounds to include new chunk
    this.worldBounds.minX = Math.min(this.worldBounds.minX, chunkPixelX);
    this.worldBounds.minY = Math.min(this.worldBounds.minY, chunkPixelY);
    this.worldBounds.maxX = Math.max(this.worldBounds.maxX, chunkPixelX + chunkW);
    this.worldBounds.maxY = Math.max(this.worldBounds.maxY, chunkPixelY + chunkH);

    // Update camera bounds
    const pad = 16;
    const cam = this.scene.cameras.main;
    const bw = this.worldBounds.maxX - this.worldBounds.minX;
    const bh = this.worldBounds.maxY - this.worldBounds.minY;
    cam.setBounds(
      this.worldBounds.minX - pad,
      this.worldBounds.minY - pad,
      bw + pad * 2,
      bh + pad * 2,
    );

    // Update walkability grid for new chunk's collision layer
    for (const layer of chunk.layers) {
      if (layer.layer.name.toLowerCase() === "collision") {
        layer.setCollisionByExclusion([-1, 0]);
        layer.setVisible(false);
        // Merge collision into walkability grid
        if (this.walkabilityGrid) {
          const newGrid = buildWalkabilityGrid(layer, chunk.tilemap.width, chunk.tilemap.height);
          this.mergeWalkabilityGrid(newGrid, offset.x, offset.y);
        }
        break;
      }
    }

    // Fade-in effect on new chunk layers
    for (const layer of chunk.layers) {
      if (layer.layer.name.toLowerCase() !== "collision") {
        layer.setAlpha(0);
        this.scene.tweens.add({
          targets: layer,
          alpha: 1,
          duration: 500,
          ease: "Power2",
        });
      }
    }

    // Pan camera to new chunk center
    const centerX = chunkPixelX + chunkW / 2;
    const centerY = chunkPixelY + chunkH / 2;
    cam.pan(centerX, centerY, 1000, "Power2");

    // Show expansion notification
    const notifyText = this.scene.add.text(
      cam.centerX,
      cam.centerY + 60,
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

  /**
   * Merge a new walkability grid from an expansion chunk into the main grid.
   * Extends the grid dimensions if needed.
   */
  private mergeWalkabilityGrid(
    newGrid: WalkabilityGrid,
    offsetTX: number,
    offsetTY: number,
  ): void {
    if (!this.walkabilityGrid) return;

    const existingH = this.walkabilityGrid.length;
    const existingW = existingH > 0 ? this.walkabilityGrid[0].length : 0;
    const neededW = offsetTX + (newGrid[0]?.length ?? 0);
    const neededH = offsetTY + newGrid.length;
    const finalW = Math.max(existingW, neededW);
    const finalH = Math.max(existingH, neededH);

    // Extend rows if needed
    while (this.walkabilityGrid.length < finalH) {
      this.walkabilityGrid.push(new Array(finalW).fill(false));
    }
    // Extend columns if needed
    for (let y = 0; y < this.walkabilityGrid.length; y++) {
      while (this.walkabilityGrid[y].length < finalW) {
        this.walkabilityGrid[y].push(false);
      }
    }

    // Overlay new grid values
    for (let y = 0; y < newGrid.length; y++) {
      for (let x = 0; x < newGrid[y].length; x++) {
        this.walkabilityGrid[offsetTY + y][offsetTX + x] = newGrid[y][x];
      }
    }
  }

  updateVisibleChunks(_cameraX: number, _cameraY: number): void {
    // Keep all loaded chunks visible for now. In the future, chunks far from
    // the camera viewport could be hidden to save rendering cost:
    //   const viewport = cam.worldView;
    //   for (const chunk of this.chunkLoader.getLoadedChunks()) { ... }
    // Currently the world is small enough that all chunks render simultaneously.
  }

  destroy(): void {
    this.chunkLoader.destroy();
  }
}

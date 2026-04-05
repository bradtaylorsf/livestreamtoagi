import Phaser from "phaser";
import { WorldManager } from "../world/WorldManager";

export class MainScene extends Phaser.Scene {
  private worldManager: WorldManager | null = null;

  constructor() {
    super({ key: "MainScene" });
  }

  preload(): void {
    // Tileset images loaded by WorldManager's ChunkLoader from cache.
    // Tilemap JSON and tileset textures should be loaded before this scene
    // starts, or loaded here if assets exist locally.
  }

  create(): void {
    this.cameras.main.setBackgroundColor("#1a1a2e");

    this.worldManager = new WorldManager(this);
    this.worldManager.create();
  }

  getWorldManager(): WorldManager | null {
    return this.worldManager;
  }

  update(): void {
    // Game loop logic will be added as features are implemented.
  }
}

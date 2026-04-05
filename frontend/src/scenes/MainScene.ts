import Phaser from "phaser";

export class MainScene extends Phaser.Scene {
  constructor() {
    super({ key: "MainScene" });
  }

  preload(): void {
    // Asset loading will be added when tilemap and sprites are ready.
  }

  create(): void {
    this.cameras.main.setBackgroundColor("#000000");
  }

  update(): void {
    // Game loop logic will be added as features are implemented.
  }
}

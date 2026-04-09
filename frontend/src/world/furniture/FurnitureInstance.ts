import type { FurnitureManifest } from "./FurnitureManifest";

/**
 * Runtime representation of a placed furniture item.
 * Wraps a Phaser sprite with manifest-driven state and z-sorting.
 */
export class FurnitureInstance {
  readonly manifest: FurnitureManifest;
  readonly sprite: Phaser.GameObjects.Image;
  readonly x: number;
  readonly y: number;
  private currentState: string;
  private parentSurface: FurnitureInstance | null;

  constructor(
    scene: Phaser.Scene,
    manifest: FurnitureManifest,
    x: number,
    y: number,
    initialState?: string,
    parentSurface?: FurnitureInstance,
  ) {
    this.manifest = manifest;
    this.x = x;
    this.y = y;
    this.parentSurface = parentSurface ?? null;

    // Determine initial texture key
    this.currentState = initialState ?? this.getDefaultState();
    const textureKey = this.getTextureKey();

    this.sprite = scene.add.image(x, y, textureKey);
    this.sprite.setOrigin(0, 0);
    this.updateDepth();
  }

  /**
   * Switch to a named state. Swaps the sprite texture using the manifest's states map.
   */
  setState(state: string): void {
    if (!this.manifest.states || !this.manifest.states[state]) return;
    this.currentState = state;
    const textureKey = this.manifest.states[state];
    this.sprite.setTexture(textureKey);
  }

  getState(): string {
    return this.currentState;
  }

  /**
   * Recalculate depth based on Y position and z-sort offset.
   * Surface items render above their parent.
   */
  updateDepth(): void {
    let depth = 1 + this.y / 10000 + this.manifest.zSortOffset;
    if (this.parentSurface) {
      depth = this.parentSurface.sprite.depth + 0.01;
    }
    this.sprite.setDepth(depth);
  }

  destroy(): void {
    this.sprite.destroy();
  }

  private getDefaultState(): string {
    if (this.manifest.states) {
      // Prefer "off" as default, otherwise use the first state
      if ("off" in this.manifest.states) return "off";
      const keys = Object.keys(this.manifest.states);
      if (keys.length > 0) return keys[0];
    }
    return "default";
  }

  private getTextureKey(): string {
    if (this.manifest.states && this.manifest.states[this.currentState]) {
      return this.manifest.states[this.currentState];
    }
    // Fallback: use the manifest id (lowercased) as texture key
    return this.manifest.id.toLowerCase();
  }
}

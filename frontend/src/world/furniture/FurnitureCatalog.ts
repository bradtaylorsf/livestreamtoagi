import type { FurnitureCategory, FurnitureManifest } from "./FurnitureManifest";

/**
 * Loads and indexes furniture manifests from a preloaded JSON file.
 * The JSON is expected to be an array of FurnitureManifest objects.
 */
export class FurnitureCatalog {
  private manifests: Map<string, FurnitureManifest> = new Map();

  /**
   * Creates a FurnitureCatalog from a Phaser scene's cache.
   * The JSON must be preloaded with the given cache key.
   */
  static fromCache(scene: Phaser.Scene, cacheKey: string): FurnitureCatalog {
    const catalog = new FurnitureCatalog();
    const jsonData = scene.cache.json.get(cacheKey);
    if (Array.isArray(jsonData)) {
      catalog.loadManifests(jsonData);
    }
    return catalog;
  }

  /**
   * Creates a FurnitureCatalog from an array of manifest objects.
   */
  static fromArray(manifests: FurnitureManifest[]): FurnitureCatalog {
    const catalog = new FurnitureCatalog();
    catalog.loadManifests(manifests);
    return catalog;
  }

  private loadManifests(data: FurnitureManifest[]): void {
    for (const manifest of data) {
      this.manifests.set(manifest.id, manifest);
    }
  }

  getManifest(id: string): FurnitureManifest | undefined {
    return this.manifests.get(id);
  }

  getByCategory(category: FurnitureCategory): FurnitureManifest[] {
    return this.allManifests().filter((m) => m.category === category);
  }

  allManifests(): FurnitureManifest[] {
    return Array.from(this.manifests.values());
  }

  hasStates(id: string): boolean {
    const manifest = this.manifests.get(id);
    return manifest?.states !== undefined && Object.keys(manifest.states).length > 0;
  }

  /**
   * Returns all unique texture keys referenced by manifests (default key = id, plus state textures).
   */
  getAllTextureKeys(): string[] {
    const keys = new Set<string>();
    for (const manifest of this.manifests.values()) {
      keys.add(manifest.id.toLowerCase());
      if (manifest.states) {
        for (const textureKey of Object.values(manifest.states)) {
          keys.add(textureKey);
        }
      }
    }
    return Array.from(keys);
  }
}

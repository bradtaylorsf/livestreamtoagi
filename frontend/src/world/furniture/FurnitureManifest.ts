/**
 * Type definitions for JSON-driven furniture manifests.
 */

export type FurnitureCategory =
  | "desks"
  | "chairs"
  | "electronics"
  | "decor"
  | "plants"
  | "surfaces";

export interface FurnitureManifest {
  id: string;
  name: string;
  category: FurnitureCategory;
  footprint: [number, number]; // [width, height] in tiles
  isDesk: boolean;
  states?: Record<string, string>; // state name → texture key (e.g. { off: 'monitor_off', on: 'monitor_on' })
  rotations?: string[];
  canPlaceOnSurfaces: boolean;
  zSortOffset: number;
}

/**
 * Workspace definitions for each agent.
 * Maps agent IDs to their named tilemap area and personality furniture items.
 * Furniture offsets are relative to the workspace area's top-left corner (pixels).
 */

export interface WorkspaceFurnitureItem {
  key: string;
  offsetX: number;
  offsetY: number;
}

export interface WorkspaceDefinition {
  areaName: string;
  furniture: WorkspaceFurnitureItem[];
}

/**
 * Per-agent workspace definitions. Each agent gets a named area in the tilemap
 * and a list of personality-reflecting furniture items placed relative to that area.
 *
 * Room assignments:
 *   Top-left:  Vera's Office (hardwood)
 *   Top-mid:   Kitchen (white tile) — shared
 *   Top-right: Dev Bay (blue-grey) — Sentinel, Fork, Pixel sub-zones
 *   Bot-left:  Rex's Workshop (hardwood)
 *   Bot-mid:   Aurora's Studio (teal)
 *   Bot-mid2:  Grok's Space (purple)
 *   Bot-right: Meeting + Alpha/Management (blue-grey)
 */
export const WORKSPACE_DEFINITIONS: Record<string, WorkspaceDefinition> = {
  vera: {
    areaName: "workspace_vera",
    furniture: [
      { key: "desk", offsetX: 0, offsetY: 0 },
      { key: "monitor", offsetX: 16, offsetY: -8 },
      { key: "monitor", offsetX: 48, offsetY: -8 },
      { key: "clipboard", offsetX: 80, offsetY: 4 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  rex: {
    areaName: "workspace_rex",
    furniture: [
      { key: "engineering_bench", offsetX: 0, offsetY: 0 },
      { key: "monitor", offsetX: 16, offsetY: -8 },
      { key: "monitor", offsetX: 48, offsetY: -8 },
      { key: "tools", offsetX: 80, offsetY: 4 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  aurora: {
    areaName: "workspace_aurora",
    furniture: [
      { key: "art_desk", offsetX: 0, offsetY: 0 },
      { key: "color_palette", offsetX: 16, offsetY: -8 },
      { key: "easel", offsetX: 80, offsetY: 4 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  pixel: {
    areaName: "workspace_pixel",
    furniture: [
      { key: "research_desk", offsetX: 0, offsetY: 0 },
      { key: "bookstack", offsetX: 16, offsetY: -8 },
      { key: "magnifying_glass", offsetX: 48, offsetY: -8 },
      { key: "antenna", offsetX: 80, offsetY: -12 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  fork: {
    areaName: "workspace_fork",
    furniture: [
      { key: "minimal_desk", offsetX: 0, offsetY: 0 },
      { key: "monitor", offsetX: 32, offsetY: -8 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  sentinel: {
    areaName: "workspace_sentinel",
    furniture: [
      { key: "organized_desk", offsetX: 0, offsetY: 0 },
      { key: "calculator", offsetX: 16, offsetY: -8 },
      { key: "ledger", offsetX: 48, offsetY: -8 },
      { key: "neat_stack", offsetX: 80, offsetY: 4 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  grok: {
    areaName: "workspace_grok",
    furniture: [
      { key: "chaotic_desk", offsetX: 0, offsetY: 0 },
      { key: "random_objects", offsetX: 16, offsetY: -8 },
      { key: "disco_ball", offsetX: 48, offsetY: -16 },
      { key: "chair", offsetX: 32, offsetY: 64 },
    ],
  },
  alpha: {
    areaName: "workspace_alpha",
    furniture: [
      { key: "dog_bed", offsetX: 0, offsetY: 0 },
      { key: "bone", offsetX: 32, offsetY: 16 },
      { key: "mobile_station", offsetX: 64, offsetY: 0 },
    ],
  },
  management: {
    areaName: "workspace_management",
    furniture: [
      { key: "elevated_platform", offsetX: 0, offsetY: 0 },
    ],
  },
};

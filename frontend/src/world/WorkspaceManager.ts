import type { WorldManager } from "./WorldManager";
import { WORKSPACE_DEFINITIONS } from "./workspaces";
import { AGENTS } from "../agents";

export interface PlacedFurnitureItem {
  key: string;
  x: number;
  y: number;
}

/**
 * Manages agent workspace areas — resolves spawn positions from tilemap areas
 * and computes absolute furniture positions for each agent's workspace.
 */
export class WorkspaceManager {
  private worldManager: WorldManager;

  constructor(worldManager: WorldManager) {
    this.worldManager = worldManager;
  }

  /**
   * Returns the spawn position for an agent within their workspace area.
   * Falls back to the agent's hardcoded deskPosition if the tilemap area is missing.
   */
  getAgentSpawnPosition(agentId: string): { x: number; y: number } {
    const workspace = WORKSPACE_DEFINITIONS[agentId];
    if (workspace) {
      const areaPos = this.worldManager.getAreaPosition(workspace.areaName);
      if (areaPos) {
        return areaPos;
      }
    }

    // Fallback to hardcoded deskPosition from agents.ts
    const agent = AGENTS.find((a) => a.id === agentId);
    if (agent) {
      return agent.deskPosition;
    }

    return { x: 0, y: 0 };
  }

  /**
   * Returns placed furniture items with absolute pixel positions for an agent's workspace.
   * If no tilemap area is found, positions are computed relative to the agent's deskPosition.
   */
  getWorkspaceFurniture(agentId: string): PlacedFurnitureItem[] {
    const workspace = WORKSPACE_DEFINITIONS[agentId];
    if (!workspace) return [];

    const areas = this.worldManager.getAreas();
    const area = areas[workspace.areaName];

    let baseX: number;
    let baseY: number;

    if (area) {
      baseX = area.x;
      baseY = area.y;
    } else {
      // Fallback: place furniture relative to the agent's hardcoded desk position
      const agent = AGENTS.find((a) => a.id === agentId);
      if (!agent) return [];
      baseX = agent.deskPosition.x - 48; // offset back to left edge (desk center is +48)
      baseY = agent.deskPosition.y - 96;  // offset above agent position
    }

    return workspace.furniture.map((item) => ({
      key: item.key,
      x: baseX + item.offsetX,
      y: baseY + item.offsetY,
    }));
  }

  /**
   * Returns all unique furniture texture keys needed across all workspaces.
   */
  static getAllFurnitureKeys(): string[] {
    const keys = new Set<string>();
    for (const workspace of Object.values(WORKSPACE_DEFINITIONS)) {
      for (const item of workspace.furniture) {
        keys.add(item.key);
      }
    }
    return Array.from(keys);
  }
}

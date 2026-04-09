import Phaser from "phaser";
import { AgentSprite, type StatusType } from "./AgentSprite";
import { AGENTS, type Agent } from "../agents";
import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";
import type { WorldManager } from "../world/WorldManager";
import type { WorkspaceManager } from "../world/WorkspaceManager";
import type { AutoStateManager } from "../world/furniture/AutoStateManager";

/** Agents that get sprite representations (excludes management which has no sprite). */
const SPRITE_AGENTS = AGENTS.filter((a) => a.id !== "management");

/**
 * Manages all agent sprites: creation, event handling, and lifecycle.
 */
export class AgentSpriteManager {
  private scene: Phaser.Scene;
  private sprites: Map<string, AgentSprite> = new Map();
  private worldManager: WorldManager | null;
  private workspaceManager: WorkspaceManager | null;
  private autoStateManager: AutoStateManager | null = null;
  private unsubscribe: (() => void) | null = null;

  constructor(
    scene: Phaser.Scene,
    wsClient: WebSocketClient | null,
    worldManager: WorldManager | null,
    workspaceManager?: WorkspaceManager | null,
  ) {
    this.scene = scene;
    this.worldManager = worldManager;
    this.workspaceManager = workspaceManager ?? null;

    // Create sprites for each agent
    for (const agent of SPRITE_AGENTS) {
      const pos = this.getDeskPosition(agent);
      const config = {
        agentId: agent.id,
        name: agent.name,
        spriteKey: `sprite_${agent.id}`,
        frameSize: agent.id === "alpha" ? 24 : 32,
        x: pos.x,
        y: pos.y,
      };
      const sprite = new AgentSprite(scene, config);
      this.sprites.set(agent.id, sprite);
    }

    // Register WebSocket event handlers
    if (wsClient) {
      this.unsubscribe = wsClient.onEvent((event) =>
        this.handleEvent(event),
      );
    }
  }

  setAutoStateManager(manager: AutoStateManager): void {
    this.autoStateManager = manager;
  }

  getSprite(agentId: string): AgentSprite | undefined {
    return this.sprites.get(agentId);
  }

  getAllSprites(): AgentSprite[] {
    return Array.from(this.sprites.values());
  }

  getSpriteMap(): Map<string, AgentSprite> {
    return this.sprites;
  }

  getSpriteCount(): number {
    return this.sprites.size;
  }

  destroy(): void {
    if (this.unsubscribe) {
      this.unsubscribe();
    }
    for (const sprite of this.sprites.values()) {
      sprite.destroy();
    }
    this.sprites.clear();
  }

  private handleEvent(event: ServerEvent): void {
    switch (event.event_type) {
      case EventType.AGENT_MOVE:
        this.handleMove(event.data);
        break;
      case EventType.AGENT_SPEAK:
        this.handleSpeak(event.data);
        break;
      case EventType.AGENT_ACTION:
        this.handleAction(event.data);
        break;
      case EventType.TOOL_EXECUTED:
        this.handleToolExecuted(event.data);
        break;
      case EventType.MANAGEMENT_SHADOW:
        this.handleManagementShadow(event.data);
        break;
    }
  }

  private handleMove(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const to = data.to as { x: number; y: number };
    const sprite = this.sprites.get(agentId);
    if (sprite && to) {
      sprite.moveTo(to.x, to.y, this.worldManager ?? undefined);
    }
  }

  private handleSpeak(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const sprite = this.sprites.get(agentId);
    if (sprite) {
      sprite.playAnimation("talking");
      sprite.setStatus("speaking");
      sprite.setBadgeState("conversation");
      sprite.setPermissionPending(false);
      this.autoStateManager?.onAgentStatusChange(agentId, "speaking");
      // Return to idle after speech duration
      this.scene.time.delayedCall(3000, () => {
        sprite.playAnimation("idle");
        sprite.setStatus("idle");
        sprite.setBadgeState("idle");
        this.autoStateManager?.onAgentStatusChange(agentId, "idle");
      });
    }
  }

  private handleAction(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const action = data.action as string;
    const sprite = this.sprites.get(agentId);
    if (!sprite) return;

    let anim = "idle";
    let status: StatusType = "idle";

    if (action === "building" || action === "coding") {
      anim = "building";
      status = "building";
      sprite.setBadgeState("active");
    } else if (action === "thinking" || action === "reflecting") {
      anim = "thinking";
      status = "thinking";
      sprite.setBadgeState("active");
    } else if (action === "getting_coffee" || action === "visiting") {
      anim = "walk_down";
      status = "idle";
      sprite.setBadgeState("idle");
    } else {
      sprite.setBadgeState("idle");
    }

    sprite.playAnimation(anim);
    sprite.setStatus(status);
    this.autoStateManager?.onAgentStatusChange(agentId, status);
  }

  private handleToolExecuted(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const toolName = data.tool_name as string;
    const success = data.success as boolean | undefined;
    const sprite = this.sprites.get(agentId);
    if (!sprite) return;

    sprite.setActivity(toolName);
    sprite.setBadgeState("active");

    if (success !== undefined && success !== null) {
      // Tool completed — show result briefly then clear
      sprite.setProgress(false);
      sprite.setBadgeState(success ? "active" : "error");
      this.scene.time.delayedCall(2000, () => {
        sprite.setActivity(null);
        sprite.setBadgeState("idle");
      });
    } else {
      // Tool in progress — show spinner
      sprite.setProgress(true);
    }
  }

  private handleManagementShadow(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const sprite = this.sprites.get(agentId);
    if (!sprite) return;

    sprite.setPermissionPending(true);
    sprite.setBadgeState("waiting");
    // Clear after 3s (matching the content filter delay)
    this.scene.time.delayedCall(3000, () => {
      sprite.setPermissionPending(false);
      // Only reset badge if still waiting
      if (sprite.getBadgeState() === "waiting") {
        sprite.setBadgeState("idle");
      }
    });
  }

  private getDeskPosition(agent: Agent): { x: number; y: number } {
    if (this.workspaceManager) {
      return this.workspaceManager.getAgentSpawnPosition(agent.id);
    }
    return agent.deskPosition;
  }
}

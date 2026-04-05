import Phaser from "phaser";
import { AgentSprite, StatusType } from "./AgentSprite";
import { AGENTS, type Agent } from "../agents";
import { EventType, type ServerEvent } from "../types/events";
import type { WebSocketClient } from "../network/WebSocketClient";
import type { WorldManager } from "../world/WorldManager";

/** Agents that get sprite representations (excludes overseer which has no sprite). */
const SPRITE_AGENTS = AGENTS.filter((a) => a.id !== "overseer");

/**
 * Manages all agent sprites: creation, event handling, and lifecycle.
 */
export class AgentSpriteManager {
  private scene: Phaser.Scene;
  private sprites: Map<string, AgentSprite> = new Map();
  private unsubscribe: (() => void) | null = null;

  constructor(
    scene: Phaser.Scene,
    wsClient: WebSocketClient | null,
    worldManager: WorldManager | null,
  ) {
    this.scene = scene;

    // Create sprites for each agent
    for (const agent of SPRITE_AGENTS) {
      const pos = this.getDeskPosition(agent, worldManager);
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

  getSprite(agentId: string): AgentSprite | undefined {
    return this.sprites.get(agentId);
  }

  getAllSprites(): AgentSprite[] {
    return Array.from(this.sprites.values());
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
    }
  }

  private handleMove(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const to = data.to as { x: number; y: number };
    const sprite = this.sprites.get(agentId);
    if (sprite && to) {
      sprite.moveTo(to.x, to.y);
    }
  }

  private handleSpeak(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const sprite = this.sprites.get(agentId);
    if (sprite) {
      sprite.playAnimation("talking");
      sprite.setStatus("speaking");
      // Return to idle after speech duration
      this.scene.time.delayedCall(3000, () => {
        sprite.playAnimation("idle");
        sprite.setStatus("idle");
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
    } else if (action === "thinking" || action === "reflecting") {
      anim = "thinking";
      status = "thinking";
    }

    sprite.playAnimation(anim);
    sprite.setStatus(status);
  }

  private getDeskPosition(
    agent: Agent,
    worldManager: WorldManager | null,
  ): { x: number; y: number } {
    // Try to get position from WorldManager areas
    if (worldManager) {
      const areaName = `desk_${agent.id}`;
      const pos = worldManager.getAreaPosition(areaName);
      if (pos) return pos;
    }

    // Fallback desk positions (pixel coordinates matching 50x34 office_layout.json)
    // Center of each 6x6 tile area: (tileX + 3) * 32, (tileY + 3) * 32
    const fallbackPositions: Record<string, { x: number; y: number }> = {
      vera: { x: 192, y: 192 },       // area (3,3) center at (6,6)*32
      aurora: { x: 448, y: 192 },     // area (11,3) center at (14,6)*32
      fork: { x: 704, y: 192 },       // area (19,3) center at (22,6)*32
      sentinel: { x: 1152, y: 192 },  // area (33,3) center at (36,6)*32
      grok: { x: 1408, y: 192 },      // area (41,3) center at (44,6)*32
      rex: { x: 192, y: 896 },        // area (3,25) center at (6,28)*32
      pixel: { x: 448, y: 896 },      // area (11,25) center at (14,28)*32
      alpha: { x: 240, y: 240 },      // Near Vera
    };

    return fallbackPositions[agent.id] ?? { x: 100, y: 100 };
  }
}

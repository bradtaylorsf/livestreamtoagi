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

/** Delay before reverting to idle after tool completes (prevents flicker). */
const TOOL_DONE_DELAY_MS = 300;

/** Tools that map to the "thinking" (reading/searching) animation. */
const READING_TOOLS = new Set([
  "code_read", "web_search", "memory_recall", "file_read", "file_search",
]);

/** Tools that map to the "building" (writing/executing) animation. */
const WRITING_TOOLS = new Set([
  "code_write", "file_edit", "terminal", "code_execute", "sandbox_run", "file_write",
]);

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
  private toolIdleTimers: Map<string, Phaser.Time.TimerEvent> = new Map();

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
    for (const timer of this.toolIdleTimers.values()) {
      timer.destroy();
    }
    this.toolIdleTimers.clear();
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
      case EventType.WORLD_EXPANSION:
        this.handleWorldExpansion(event.data);
        break;
      case EventType.MANAGEMENT_INTERVENTION:
        this.handleManagementIntervention(event.data);
        break;
      case EventType.MANAGEMENT_WARNING:
        this.handleManagementWarning(event.data);
        break;
      case EventType.ALPHA_DISPATCH:
        this.handleAlphaDispatch(event.data);
        break;
      case EventType.ALPHA_RETURN:
        this.handleAlphaReturn(event.data);
        break;
      case EventType.CONFIG_RELOADED:
        console.log("Config reloaded:", event.data.config_type, event.data.changes);
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

    // Cancel any pending idle timer for this agent
    const existingTimer = this.toolIdleTimers.get(agentId);
    if (existingTimer) {
      existingTimer.destroy();
      this.toolIdleTimers.delete(agentId);
    }

    if (success !== undefined && success !== null) {
      // Tool completed — show result briefly, then revert to idle after delay
      sprite.setProgress(false);
      sprite.setBadgeState(success ? "active" : "error");
      const timer = this.scene.time.delayedCall(TOOL_DONE_DELAY_MS, () => {
        sprite.playAnimation("idle");
        sprite.setActivity(null);
        sprite.setBadgeState("idle");
        this.autoStateManager?.onAgentStatusChange(agentId, "idle");
        this.toolIdleTimers.delete(agentId);
      });
      this.toolIdleTimers.set(agentId, timer);
    } else {
      // Tool in progress — play mapped animation and show spinner
      const anim = this.getToolAnimation(toolName);
      sprite.playAnimation(anim);
      sprite.setProgress(true);
      this.autoStateManager?.onAgentStatusChange(agentId, anim === "building" ? "building" : "thinking");
    }
  }

  /** Map a tool name to the appropriate animation. */
  private getToolAnimation(toolName: string): string {
    if (WRITING_TOOLS.has(toolName)) return "building";
    if (READING_TOOLS.has(toolName)) return "thinking";
    return "thinking"; // default for unknown tools
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

  private handleWorldExpansion(data: Record<string, unknown>): void {
    const zone = data.zone as string;
    const description = data.description as string;
    if (this.worldManager) {
      this.worldManager.expandWorld(zone, description);
    }
  }

  private handleManagementIntervention(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const sprite = this.sprites.get(agentId);

    // Red camera flash
    this.scene.cameras.main.flash(500, 255, 50, 50);

    // Warning text overlay
    const warningText = this.scene.add.text(
      this.scene.cameras.main.centerX,
      this.scene.cameras.main.centerY,
      "MANAGEMENT INTERVENTION",
      {
        fontSize: "16px",
        color: "#ff4444",
        fontFamily: "monospace",
        stroke: "#000000",
        strokeThickness: 3,
        align: "center",
      },
    );
    warningText.setOrigin(0.5, 0.5);
    warningText.setScrollFactor(0);
    warningText.setDepth(100);

    this.scene.tweens.add({
      targets: warningText,
      alpha: 0,
      delay: 1000,
      duration: 1000,
      onComplete: () => warningText.destroy(),
    });

    // Shake the targeted agent sprite
    if (sprite) {
      const origX = sprite.sprite.x;
      sprite.setBadgeState("error");
      this.scene.tweens.add({
        targets: sprite.sprite,
        x: origX + 3,
        duration: 50,
        yoyo: true,
        repeat: 5,
        onComplete: () => {
          sprite.sprite.x = origX;
        },
      });
    }
  }

  private handleManagementWarning(data: Record<string, unknown>): void {
    const agentId = data.agent_id as string;
    const sprite = this.sprites.get(agentId);
    if (!sprite) return;

    // Show a yellow warning via activity label for 3s
    sprite.setActivity("warning");
    sprite.setBadgeState("waiting");
    this.scene.time.delayedCall(3000, () => {
      sprite.setActivity(null);
      if (sprite.getBadgeState() === "waiting") {
        sprite.setBadgeState("idle");
      }
    });
  }

  private handleAlphaDispatch(_data: Record<string, unknown>): void {
    const alpha = this.sprites.get("alpha");
    if (!alpha) return;

    alpha.playAnimation("running");
    alpha.setBadgeState("active");

    // Tween alpha off-screen to the left
    this.scene.tweens.add({
      targets: alpha.sprite,
      x: -50,
      duration: 1000,
      ease: "Power2",
      onComplete: () => {
        alpha.setVisible(false);
        alpha.setBadgeState("idle");
      },
    });
  }

  private handleAlphaReturn(data: Record<string, unknown>): void {
    const alpha = this.sprites.get("alpha");
    if (!alpha) return;

    const success = data.success as boolean;
    const result = data.result as string | undefined;
    const deskPos = this.getDeskPosition(
      AGENTS.find((a) => a.id === "alpha")!,
    );

    alpha.setPosition(-50, deskPos.y);
    alpha.setVisible(true);
    alpha.playAnimation("running");
    alpha.setBadgeState("active");

    this.scene.tweens.add({
      targets: alpha.sprite,
      x: deskPos.x,
      y: deskPos.y,
      duration: 1000,
      ease: "Power2",
      onComplete: () => {
        alpha.setPosition(deskPos.x, deskPos.y);
        alpha.playAnimation(success ? "celebrate" : "confused");
        alpha.setBadgeState("idle");
        if (result) {
          const truncated = result.length > 20 ? result.slice(0, 19) + "\u2026" : result;
          alpha.setActivity(truncated);
          this.scene.time.delayedCall(3000, () => {
            alpha.setActivity(null);
            alpha.playAnimation("idle");
          });
        } else {
          this.scene.time.delayedCall(2000, () => {
            alpha.playAnimation("idle");
          });
        }
      },
    });
  }

  private getDeskPosition(agent: Agent): { x: number; y: number } {
    if (this.workspaceManager) {
      return this.workspaceManager.getAgentSpawnPosition(agent.id);
    }
    return agent.deskPosition;
  }
}

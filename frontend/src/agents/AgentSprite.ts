import Phaser from "phaser";
import type { WorldManager } from "../world/WorldManager";
import { tileToPixel } from "../world/Pathfinding";

export type AnimationName =
  | "idle"
  | "walk_up"
  | "walk_down"
  | "walk_left"
  | "walk_right"
  | "talking"
  | "thinking"
  | "building";

export type StatusType = "thinking" | "speaking" | "building" | "idle";

export type BadgeState = "active" | "waiting" | "error" | "idle" | "conversation";

const STATUS_ICONS: Record<StatusType, string> = {
  thinking: "\u{1F4AD}", // thought bubble
  speaking: "\u{1F4AC}", // speech bubble
  building: "\u{1F528}", // hammer
  idle: "",
};

const BADGE_COLORS: Record<BadgeState, number> = {
  active: 0x44cc44,
  waiting: 0xffaa00,
  error: 0xff4444,
  idle: 0x888888,
  conversation: 0x4488ff,
};

const BADGE_RADIUS = 3;
const ACTIVITY_MAX_CHARS = 20;

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  file_read: "Reading file...",
  code_write: "Writing code...",
  web_search: "Searching...",
  code_review: "Reviewing code...",
  run_tests: "Running tests...",
  file_write: "Writing file...",
  file_search: "Searching files...",
  code_execute: "Executing code...",
  budget_check: "Checking budget...",
  memory_recall: "Recalling...",
  memory_store: "Storing memory...",
};

/** Format a backend tool_name into a friendly display string, truncated to 20 chars. */
export function formatToolName(name: string): string {
  const display = TOOL_DISPLAY_NAMES[name];
  if (display) return display;
  // Fallback: capitalize and add ellipsis
  const friendly = name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) + "...";
  if (friendly.length > ACTIVITY_MAX_CHARS) {
    return friendly.slice(0, ACTIVITY_MAX_CHARS - 1) + "\u2026";
  }
  return friendly;
}

const TWEEN_DURATION_MS = 500;
const STEP_DURATION_MS = 250; // per-tile step for pathfinding (4 tiles/sec)

export interface AgentSpriteConfig {
  agentId: string;
  name: string;
  spriteKey: string;
  frameSize: number;
  x: number;
  y: number;
}

/**
 * Wraps a Phaser sprite for a single agent with animations,
 * movement tweens, name label, and status indicator.
 */
export class AgentSprite {
  readonly agentId: string;
  readonly sprite: Phaser.GameObjects.Sprite;
  private nameLabel: Phaser.GameObjects.Text;
  private statusLabel: Phaser.GameObjects.Text;
  private activityLabel: Phaser.GameObjects.Text;
  private statusBadge: Phaser.GameObjects.Graphics;
  private permissionIndicator: Phaser.GameObjects.Text;
  private progressDots: Phaser.GameObjects.Text;
  private scene: Phaser.Scene;
  private currentAnimation: string = "idle";
  private currentStatus: StatusType = "idle";
  private currentBadgeState: BadgeState = "idle";
  private moveTweens: Phaser.Tweens.Tween[] = [];
  private pathStepIndex = -1;
  private currentPath: Array<{ x: number; y: number }> = [];
  private pulseTween: Phaser.Tweens.Tween | null = null;
  private progressTimer: Phaser.Time.TimerEvent | null = null;
  private progressDotCount = 0;
  isBusy = false;

  constructor(scene: Phaser.Scene, config: AgentSpriteConfig) {
    this.scene = scene;
    this.agentId = config.agentId;

    this.sprite = scene.add.sprite(config.x, config.y, config.spriteKey);
    this.sprite.setOrigin(0.5, 1);
    this.sprite.setDepth(2); // Render above furniture (depth 1)

    // Name label below sprite
    this.nameLabel = scene.add.text(config.x, config.y + 4, config.name, {
      fontSize: "10px",
      color: "#ffffff",
      fontFamily: "monospace",
      align: "center",
      stroke: "#000000",
      strokeThickness: 2,
    });
    this.nameLabel.setOrigin(0.5, 0);
    this.nameLabel.setDepth(3);

    // Status indicator above sprite (emoji)
    this.statusLabel = scene.add.text(
      config.x,
      config.y - config.frameSize - 4,
      "",
      {
        fontSize: "14px",
        align: "center",
      },
    );
    this.statusLabel.setOrigin(0.5, 1);
    this.statusLabel.setDepth(3);
    this.statusLabel.setVisible(false);

    // Activity label above status (tool name text)
    this.activityLabel = scene.add.text(
      config.x,
      config.y - config.frameSize - 20,
      "",
      {
        fontSize: "9px",
        color: "#ffffff",
        fontFamily: "monospace",
        align: "center",
        stroke: "#000000",
        strokeThickness: 2,
      },
    );
    this.activityLabel.setOrigin(0.5, 1);
    this.activityLabel.setDepth(3);
    this.activityLabel.setVisible(false);

    // Status badge (colored dot next to name)
    this.statusBadge = scene.add.graphics();
    this.statusBadge.setDepth(3);
    this.drawBadge(
      config.x + this.nameLabel.width / 2 + 6,
      config.y + 4 + 5,
      "idle",
    );

    // Permission indicator (shown during Management content filter review)
    this.permissionIndicator = scene.add.text(
      config.x,
      config.y - config.frameSize - 34,
      "\u{1F50D} reviewing...",
      {
        fontSize: "8px",
        color: "#ffaa00",
        fontFamily: "monospace",
        align: "center",
        stroke: "#000000",
        strokeThickness: 2,
      },
    );
    this.permissionIndicator.setOrigin(0.5, 1);
    this.permissionIndicator.setDepth(3);
    this.permissionIndicator.setVisible(false);

    // Progress dots for long-running tools
    this.progressDots = scene.add.text(
      config.x + 40,
      config.y - config.frameSize - 20,
      "",
      {
        fontSize: "9px",
        color: "#44cc44",
        fontFamily: "monospace",
        stroke: "#000000",
        strokeThickness: 2,
      },
    );
    this.progressDots.setOrigin(0, 1);
    this.progressDots.setDepth(3);
    this.progressDots.setVisible(false);

    // Auto-play idle animation if it exists
    this.playAnimation("idle");
  }

  playAnimation(name: string): void {
    this.currentAnimation = name;
    const animKey = `${this.agentId}_${name}`;
    if (this.sprite.anims?.exists?.(animKey)) {
      this.sprite.play(animKey);
    } else {
      // Set frame directly if animation not loaded
      const animIndex = this.getAnimationIndex(name);
      if (animIndex >= 0) {
        this.sprite.setFrame(animIndex);
      }
    }
  }

  /**
   * Move to target position. If worldManager is provided, uses A* pathfinding
   * to navigate around obstacles tile-by-tile. Falls back to direct tween.
   */
  moveTo(x: number, y: number, worldManager?: WorldManager): void {
    this.cancelPath();

    if (worldManager) {
      const path = worldManager.findPath(this.sprite.x, this.sprite.y, x, y);
      if (path && path.length > 1) {
        const tileSize = worldManager.getTileSize();
        this.currentPath = path.map((t) => tileToPixel(t.tx, t.ty, tileSize));
        this.pathStepIndex = 1; // skip index 0 (current position)
        this.isBusy = true;
        this.stepToNextTile();
        return;
      }
    }

    // Fallback: direct tween (no pathfinding available or no path found)
    this.isBusy = true;
    this.directMoveTo(x, y, () => {
      this.isBusy = false;
    });
  }

  /** Cancel any in-progress path following. */
  cancelPath(): void {
    for (const tween of this.moveTweens) {
      tween.stop();
    }
    this.moveTweens = [];
    this.currentPath = [];
    this.pathStepIndex = -1;
    this.isBusy = false;
    this.playAnimation("idle");
  }

  /** Tween directly to a position (single segment). */
  private directMoveTo(x: number, y: number, onComplete?: () => void): void {
    const dx = x - this.sprite.x;
    const dy = y - this.sprite.y;
    if (Math.abs(dx) > Math.abs(dy)) {
      this.playAnimation(dx > 0 ? "walk_right" : "walk_left");
    } else if (dy !== 0) {
      this.playAnimation(dy > 0 ? "walk_down" : "walk_up");
    }

    const h = this.sprite.height;
    const tweenProps = { x, duration: TWEEN_DURATION_MS, ease: "Power2" };

    const spriteTween = this.scene.tweens.add({
      targets: this.sprite,
      ...tweenProps,
      y,
      onComplete: () => {
        this.moveTweens = [];
        this.playAnimation("idle");
        onComplete?.();
      },
    });

    const nameTween = this.scene.tweens.add({
      targets: this.nameLabel,
      ...tweenProps,
      y: y + 4,
    });

    const statusTween = this.scene.tweens.add({
      targets: this.statusLabel,
      ...tweenProps,
      y: y - h - 4,
    });

    const activityTween = this.scene.tweens.add({
      targets: this.activityLabel,
      ...tweenProps,
      y: y - h - 20,
    });

    const permissionTween = this.scene.tweens.add({
      targets: this.permissionIndicator,
      ...tweenProps,
      y: y - h - 34,
    });

    const progressTween = this.scene.tweens.add({
      targets: this.progressDots,
      x: x + 40,
      y: y - h - 20,
      duration: TWEEN_DURATION_MS,
      ease: "Power2",
    });

    const nameHalfW = this.nameLabel.width / 2;
    const badgeTween = this.scene.tweens.add({
      targets: this.statusBadge,
      x: x + nameHalfW + 6,
      y: y + 4 + 5,
      duration: TWEEN_DURATION_MS,
      ease: "Power2",
    });

    this.moveTweens = [
      spriteTween, nameTween, statusTween,
      activityTween, permissionTween, progressTween, badgeTween,
    ];
  }

  /** Walk one tile along the current path, then chain to next. */
  private stepToNextTile(): void {
    if (this.pathStepIndex < 0 || this.pathStepIndex >= this.currentPath.length) {
      this.currentPath = [];
      this.pathStepIndex = -1;
      this.isBusy = false;
      this.playAnimation("idle");
      return;
    }

    const target = this.currentPath[this.pathStepIndex];
    const dx = target.x - this.sprite.x;
    const dy = target.y - this.sprite.y;

    if (Math.abs(dx) > Math.abs(dy)) {
      this.playAnimation(dx > 0 ? "walk_right" : "walk_left");
    } else if (dy !== 0) {
      this.playAnimation(dy > 0 ? "walk_down" : "walk_up");
    }

    const h = this.sprite.height;
    const stepProps = { x: target.x, duration: STEP_DURATION_MS, ease: "Linear" };

    const spriteTween = this.scene.tweens.add({
      targets: this.sprite,
      ...stepProps,
      y: target.y,
      onComplete: () => {
        this.pathStepIndex++;
        this.stepToNextTile();
      },
    });

    const nameTween = this.scene.tweens.add({
      targets: this.nameLabel,
      ...stepProps,
      y: target.y + 4,
    });

    const statusTween = this.scene.tweens.add({
      targets: this.statusLabel,
      ...stepProps,
      y: target.y - h - 4,
    });

    const activityTween = this.scene.tweens.add({
      targets: this.activityLabel,
      ...stepProps,
      y: target.y - h - 20,
    });

    const permissionTween = this.scene.tweens.add({
      targets: this.permissionIndicator,
      ...stepProps,
      y: target.y - h - 34,
    });

    const progressTween = this.scene.tweens.add({
      targets: this.progressDots,
      x: target.x + 40,
      y: target.y - h - 20,
      duration: STEP_DURATION_MS,
      ease: "Linear",
    });

    const nameHalfW = this.nameLabel.width / 2;
    const badgeTween = this.scene.tweens.add({
      targets: this.statusBadge,
      x: target.x + nameHalfW + 6,
      y: target.y + 4 + 5,
      duration: STEP_DURATION_MS,
      ease: "Linear",
    });

    this.moveTweens = [
      spriteTween, nameTween, statusTween,
      activityTween, permissionTween, progressTween, badgeTween,
    ];
  }

  setStatus(status: StatusType): void {
    this.currentStatus = status;
    const icon = STATUS_ICONS[status];
    if (icon) {
      this.statusLabel.setText(icon);
      this.statusLabel.setVisible(true);
    } else {
      this.statusLabel.setVisible(false);
    }
  }

  getStatus(): StatusType {
    return this.currentStatus;
  }

  getBadgeState(): BadgeState {
    return this.currentBadgeState;
  }

  /** Set visibility of all game objects (sprite, labels, badge). */
  setVisible(visible: boolean): void {
    this.sprite.setVisible(visible);
    this.nameLabel.setVisible(visible);
    this.statusBadge.setVisible(visible);
    if (!visible) {
      this.statusLabel.setVisible(false);
      this.activityLabel.setVisible(false);
      this.permissionIndicator.setVisible(false);
      this.progressDots.setVisible(false);
    }
  }

  /** Instantly reposition all game objects to a new position. */
  setPosition(x: number, y: number): void {
    const h = this.sprite.height;
    this.sprite.x = x;
    this.sprite.y = y;
    this.nameLabel.x = x;
    this.nameLabel.y = y + 4;
    this.statusLabel.x = x;
    this.statusLabel.y = y - h - 4;
    this.activityLabel.x = x;
    this.activityLabel.y = y - h - 20;
    this.permissionIndicator.x = x;
    this.permissionIndicator.y = y - h - 34;
    this.progressDots.x = x + 40;
    this.progressDots.y = y - h - 20;
    const nameHalfW = this.nameLabel.width / 2;
    this.drawBadge(x + nameHalfW + 6, y + 4 + 5, this.currentBadgeState);
  }

  /** Show or hide activity label above character. Pass null to fade out. */
  setActivity(toolName: string | null): void {
    if (toolName) {
      this.activityLabel.setText(formatToolName(toolName));
      this.activityLabel.setAlpha(1);
      this.activityLabel.setVisible(true);
    } else {
      // Fade out over 1s
      if (this.activityLabel.visible) {
        this.scene.tweens.add({
          targets: this.activityLabel,
          alpha: 0,
          duration: 1000,
          onComplete: () => {
            this.activityLabel.setVisible(false);
          },
        });
      }
    }
  }

  /** Set the colored status badge state. */
  setBadgeState(state: BadgeState): void {
    this.currentBadgeState = state;
    const nameWidth = this.nameLabel.width / 2;
    this.drawBadge(
      this.nameLabel.x + nameWidth + 6,
      this.nameLabel.y + 5,
      state,
    );

    // Manage pulse tween for active state
    if (this.pulseTween) {
      this.pulseTween.stop();
      this.pulseTween = null;
      this.statusBadge.setAlpha(1);
    }
    if (state === "active") {
      this.pulseTween = this.scene.tweens.add({
        targets: this.statusBadge,
        alpha: 0.6,
        duration: 500,
        yoyo: true,
        repeat: -1,
      });
    }
  }

  /** Show/hide permission pending indicator (Management content filter). */
  setPermissionPending(pending: boolean): void {
    this.permissionIndicator.setVisible(pending);
  }

  /** Show/hide progress dots animation for long-running tools. */
  setProgress(active: boolean): void {
    if (active) {
      this.progressDotCount = 0;
      this.progressDots.setText(".");
      this.progressDots.setVisible(true);
      this.progressTimer = this.scene.time.addEvent({
        delay: 400,
        loop: true,
        callback: () => {
          this.progressDotCount = (this.progressDotCount + 1) % 3;
          this.progressDots.setText(".".repeat(this.progressDotCount + 1));
        },
      });
    } else {
      this.progressDots.setVisible(false);
      if (this.progressTimer) {
        this.progressTimer.destroy();
        this.progressTimer = null;
      }
    }
  }

  private drawBadge(x: number, y: number, state: BadgeState): void {
    this.statusBadge.clear();
    this.statusBadge.setPosition(x, y);
    this.statusBadge.fillStyle(BADGE_COLORS[state], 1);
    this.statusBadge.fillCircle(0, 0, BADGE_RADIUS);
  }

  getCurrentAnimation(): string {
    return this.currentAnimation;
  }

  /**
   * Play a short idle micro-animation at the agent's desk.
   * Used by BehaviorScheduler for client-side ambient activity.
   */
  playMicroAnimation(type: "typing" | "looking" | "stretching"): void {
    if (this.isBusy) return;

    this.isBusy = true;

    switch (type) {
      case "typing":
        this.playAnimation("building");
        this.scene.time.delayedCall(2000, () => {
          this.playAnimation("idle");
          this.isBusy = false;
        });
        break;
      case "looking":
        this.playAnimation("thinking");
        this.scene.time.delayedCall(1500, () => {
          this.playAnimation("idle");
          this.isBusy = false;
        });
        break;
      case "stretching":
        // Brief scale tween for a stretch effect, then return to idle
        this.scene.tweens.add({
          targets: this.sprite,
          scaleY: 1.15,
          duration: 500,
          yoyo: true,
          ease: "Sine.easeInOut",
          onComplete: () => {
            this.sprite.setScale(1, 1);
            this.isBusy = false;
          },
        });
        break;
    }
  }

  getPosition(): { x: number; y: number } {
    return { x: this.sprite.x, y: this.sprite.y };
  }

  destroy(): void {
    for (const tween of this.moveTweens) {
      tween.stop();
    }
    if (this.pulseTween) {
      this.pulseTween.stop();
    }
    if (this.progressTimer) {
      this.progressTimer.destroy();
    }
    this.sprite.destroy();
    this.nameLabel.destroy();
    this.statusLabel.destroy();
    this.activityLabel.destroy();
    this.statusBadge.destroy();
    this.permissionIndicator.destroy();
    this.progressDots.destroy();
  }

  private getAnimationIndex(name: string): number {
    const AGENT_ANIMS = [
      "idle",
      "walk_up",
      "walk_down",
      "walk_left",
      "walk_right",
      "talking",
      "thinking",
      "building",
    ];
    const ALPHA_ANIMS = [
      "idle",
      "running",
      "carrying",
      "confused",
      "celebrate",
      "sleeping",
    ];
    const anims = this.agentId === "alpha" ? ALPHA_ANIMS : AGENT_ANIMS;
    return anims.indexOf(name);
  }
}

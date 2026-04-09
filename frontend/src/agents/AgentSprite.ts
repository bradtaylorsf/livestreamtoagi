import Phaser from "phaser";

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

const STATUS_ICONS: Record<StatusType, string> = {
  thinking: "\u{1F4AD}", // thought bubble
  speaking: "\u{1F4AC}", // speech bubble
  building: "\u{1F528}", // hammer
  idle: "",
};

const TWEEN_DURATION_MS = 500;

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
  private scene: Phaser.Scene;
  private currentAnimation: string = "idle";
  private currentStatus: StatusType = "idle";
  private moveTweens: Phaser.Tweens.Tween[] = [];

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

    // Status indicator above sprite
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

  moveTo(x: number, y: number): Phaser.Tweens.Tween {
    // Cancel all existing movement tweens
    for (const tween of this.moveTweens) {
      tween.stop();
    }
    this.moveTweens = [];

    // Determine walk direction animation
    const dx = x - this.sprite.x;
    const dy = y - this.sprite.y;
    if (Math.abs(dx) > Math.abs(dy)) {
      this.playAnimation(dx > 0 ? "walk_right" : "walk_left");
    } else if (dy !== 0) {
      this.playAnimation(dy > 0 ? "walk_down" : "walk_up");
    }

    // Tween sprite to target
    const spriteTween = this.scene.tweens.add({
      targets: this.sprite,
      x,
      y,
      duration: TWEEN_DURATION_MS,
      ease: "Power2",
      onComplete: () => {
        this.moveTweens = [];
        this.playAnimation("idle");
      },
    });

    // Tween labels to follow
    const nameTween = this.scene.tweens.add({
      targets: this.nameLabel,
      x,
      y: y + 4,
      duration: TWEEN_DURATION_MS,
      ease: "Power2",
    });

    const statusTween = this.scene.tweens.add({
      targets: this.statusLabel,
      x,
      y: y - this.sprite.height - 4,
      duration: TWEEN_DURATION_MS,
      ease: "Power2",
    });

    this.moveTweens = [spriteTween, nameTween, statusTween];
    return spriteTween;
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

  getCurrentAnimation(): string {
    return this.currentAnimation;
  }

  getPosition(): { x: number; y: number } {
    return { x: this.sprite.x, y: this.sprite.y };
  }

  destroy(): void {
    for (const tween of this.moveTweens) {
      tween.stop();
    }
    this.sprite.destroy();
    this.nameLabel.destroy();
    this.statusLabel.destroy();
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

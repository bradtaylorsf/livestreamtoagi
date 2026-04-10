import Phaser from "phaser";
import type { AgentSprite } from "../agents/AgentSprite";

/** Duration of spawn/despawn effect in milliseconds. */
const EFFECT_DURATION_MS = 400;

/** Number of particles in the dissolve effect. */
const PARTICLE_COUNT = 24;

/** Key for the generated particle texture. */
const PARTICLE_TEXTURE_KEY = "__spawn_particle";

/**
 * Handles visual spawn and despawn effects for agent sprites.
 * Uses Phaser tweens and particle-like squares for a pixel dissolve effect.
 */
export class SpawnEffect {
  private scene: Phaser.Scene;

  constructor(scene: Phaser.Scene) {
    this.scene = scene;
    this.ensureParticleTexture();
  }

  /**
   * Play a spawn (appear) effect: small squares converge inward
   * while sprite fades in over EFFECT_DURATION_MS.
   */
  playSpawn(sprite: AgentSprite, onComplete?: () => void): void {
    sprite.spawning = true;
    sprite.sprite.setAlpha(0);

    const pos = sprite.getPosition();
    const particles = this.createParticles(pos.x, pos.y, "inward");

    // Fade in the sprite
    this.scene.tweens.add({
      targets: sprite.sprite,
      alpha: 1,
      duration: EFFECT_DURATION_MS,
      ease: "Power2",
      onComplete: () => {
        this.destroyParticles(particles);
        sprite.spawning = false;
        onComplete?.();
      },
    });
  }

  /**
   * Play a despawn (disappear) effect: sprite fades out while
   * small squares scatter outward over EFFECT_DURATION_MS.
   */
  playDespawn(sprite: AgentSprite, onComplete?: () => void): void {
    sprite.spawning = true;

    const pos = sprite.getPosition();
    const particles = this.createParticles(pos.x, pos.y, "outward");

    // Fade out the sprite
    this.scene.tweens.add({
      targets: sprite.sprite,
      alpha: 0,
      duration: EFFECT_DURATION_MS,
      ease: "Power2",
      onComplete: () => {
        this.destroyParticles(particles);
        sprite.spawning = false;
        onComplete?.();
      },
    });
  }

  /** Create a simple 2x2 white square texture for particles if it doesn't exist. */
  private ensureParticleTexture(): void {
    if (this.scene.textures.exists(PARTICLE_TEXTURE_KEY)) return;
    const canvas = this.scene.textures.createCanvas(PARTICLE_TEXTURE_KEY, 2, 2);
    if (canvas) {
      const ctx = canvas.getContext();
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, 2, 2);
      canvas.refresh();
    }
  }

  /**
   * Create particle-like rectangles that move inward or outward.
   * Returns the created game objects for later cleanup.
   */
  private createParticles(
    cx: number,
    cy: number,
    direction: "inward" | "outward",
  ): Phaser.GameObjects.Rectangle[] {
    const particles: Phaser.GameObjects.Rectangle[] = [];
    const spread = 40;

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const angle = (i / PARTICLE_COUNT) * Math.PI * 2;
      const dist = spread + Math.random() * 20;

      const outerX = cx + Math.cos(angle) * dist;
      const outerY = cy - 16 + Math.sin(angle) * dist; // offset up to center on sprite
      const innerX = cx + Math.cos(angle) * (Math.random() * 8);
      const innerY = cy - 16 + Math.sin(angle) * (Math.random() * 8);

      const startX = direction === "inward" ? outerX : innerX;
      const startY = direction === "inward" ? outerY : innerY;
      const endX = direction === "inward" ? innerX : outerX;
      const endY = direction === "inward" ? innerY : outerY;

      const size = 2 + Math.floor(Math.random() * 2);
      const rect = this.scene.add.rectangle(startX, startY, size, size, 0xffffff);
      rect.setDepth(10);
      rect.setAlpha(0.8);

      this.scene.tweens.add({
        targets: rect,
        x: endX,
        y: endY,
        alpha: direction === "inward" ? 0.2 : 0,
        duration: EFFECT_DURATION_MS,
        ease: direction === "inward" ? "Power2" : "Power2",
      });

      particles.push(rect);
    }

    return particles;
  }

  private destroyParticles(particles: Phaser.GameObjects.Rectangle[]): void {
    for (const p of particles) {
      p.destroy();
    }
  }
}

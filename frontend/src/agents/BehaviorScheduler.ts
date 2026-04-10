import type { AgentSprite } from "./AgentSprite";
import { AGENTS } from "../agents";

export type MicroAnimationType = "typing" | "looking" | "stretching";

const MICRO_ANIMATIONS: MicroAnimationType[] = ["typing", "looking", "stretching"];

/** Min/max idle interval in milliseconds. */
const BASE_MIN_INTERVAL_MS = 30_000;
const BASE_MAX_INTERVAL_MS = 60_000;

/**
 * Client-side scheduler for idle micro-animations.
 * Agents play small desk animations (typing, looking around, stretching)
 * without requiring backend events.
 */
export class BehaviorScheduler {
  private sprites: Map<string, AgentSprite>;
  private timers: Map<string, number> = new Map();
  private nextIntervals: Map<string, number> = new Map();
  /** Per-agent chattiness cached from AGENTS at construction time. Avoids linear scans each frame. */
  private chattiness: Map<string, number> = new Map();

  constructor(sprites: Map<string, AgentSprite>) {
    this.sprites = sprites;

    // Cache chattiness and initialize per-agent timers with randomized initial delays.
    for (const [agentId] of sprites) {
      const chattiness = AGENTS.find((a) => a.id === agentId)?.chattiness ?? 0.5;
      this.chattiness.set(agentId, chattiness);
      const interval = this.randomInterval(chattiness);
      // Stagger initial timers so they don't all fire at once
      this.timers.set(agentId, Math.random() * interval);
      this.nextIntervals.set(agentId, interval);
    }
  }

  /**
   * Called each frame from MainScene.update().
   * Checks if any idle agent should play a micro-animation.
   */
  update(deltaMs: number): void {
    for (const [agentId, sprite] of this.sprites) {
      // Skip busy or spawning agents
      if (sprite.isBusy || sprite.spawning) continue;

      const elapsed = (this.timers.get(agentId) ?? 0) + deltaMs;
      const interval = this.nextIntervals.get(agentId) ?? BASE_MAX_INTERVAL_MS;

      if (elapsed >= interval) {
        // Pick and play a random micro-animation
        const animType = MICRO_ANIMATIONS[Math.floor(Math.random() * MICRO_ANIMATIONS.length)];
        sprite.playMicroAnimation(animType);

        // Reset timer with new random interval using cached chattiness
        this.timers.set(agentId, 0);
        this.nextIntervals.set(agentId, this.randomInterval(this.chattiness.get(agentId) ?? 0.5));
      } else {
        this.timers.set(agentId, elapsed);
      }
    }
  }

  destroy(): void {
    this.timers.clear();
    this.nextIntervals.clear();
  }

  /**
   * Calculate a random interval, shorter for chattier agents.
   * Higher chattiness → shorter intervals (more fidgety).
   */
  private randomInterval(chattiness: number): number {
    // Scale factor: chattiness 1.0 → 0.5x interval, chattiness 0.0 → 1.5x interval
    const scale = 1.5 - chattiness;
    const min = BASE_MIN_INTERVAL_MS * scale;
    const max = BASE_MAX_INTERVAL_MS * scale;
    return min + Math.random() * (max - min);
  }
}

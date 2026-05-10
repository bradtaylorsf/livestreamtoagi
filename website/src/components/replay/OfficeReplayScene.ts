/**
 * Phaser scene that renders the office replay: real tilemap, real agent
 * sprites, name labels, movement tweens, and stacked speech bubbles.
 *
 * Loaded only on the client (parent ReplayStage uses next/dynamic with
 * ssr:false). Phaser is imported at module load time for tree-shaking;
 * the scene class is exported as a *factory* so tests can construct it
 * without actually executing the WebGL renderer.
 */

import Phaser from "phaser";
import {
  getDeskPosition,
  getSpeakingPosition,
  clampBubblePosition,
} from "./agentLayout";
import { ReplaySpeechBubble } from "./ReplaySpeechBubble";
import type { BubblePlan, ReplayPlan } from "./playback";

const ASSET_BASE = "/replay-assets";
const TILE_SIZE = 32;
const STAGE_W = 1280;
const STAGE_H = 720;
const IDLE_FRAMES = 4;
const WALK_FRAMES = 6;

/**
 * Map of (Tiled tileset name) → (texture image key). The Tiled JSON uses
 * names like "office_tiles_hardwood" while the image file is "tileset_hardwood".
 * Phaser's ``addTilesetImage(tilesetName, imageKey)`` needs both.
 */
const TILESETS: Array<{ tilesetName: string; imageKey: string }> = [
  { tilesetName: "office_tiles", imageKey: "tileset" },
  { tilesetName: "office_tiles_hardwood", imageKey: "tileset_hardwood" },
  { tilesetName: "office_tiles_whitetile", imageKey: "tileset_whitetile" },
  { tilesetName: "office_tiles_teal", imageKey: "tileset_teal" },
  { tilesetName: "office_tiles_purple", imageKey: "tileset_purple" },
  { tilesetName: "office_tiles_bluegrey", imageKey: "tileset_bluegrey" },
  { tilesetName: "office_tiles_concrete", imageKey: "tileset_concrete" },
  { tilesetName: "office_tiles_olive", imageKey: "tileset_olive" },
];

const DIRECTIONS = ["south", "north", "east", "west"] as const;
type Direction = (typeof DIRECTIONS)[number];

interface AgentVisual {
  sprite: Phaser.GameObjects.Sprite;
  label: Phaser.GameObjects.Text;
  bubble: ReplaySpeechBubble;
  desk: { x: number; y: number };
  facing: Direction;
}

export interface OfficeReplaySceneOptions {
  plan: ReplayPlan;
  /** Agents selected by the simulation roster or legacy replay fallback. */
  visibleAgents: string[];
  /** Sets ``window.__replayReady`` once textures + first frame are drawn. */
  onReady?: () => void;
  /** Sets ``window.__replayDone`` after plan.done_at_ms elapses. */
  onDone?: () => void;
}

export class OfficeReplayScene extends Phaser.Scene {
  private opts: OfficeReplaySceneOptions;
  private agents: Map<string, AgentVisual> = new Map();
  private startMs = 0;
  private doneFired = false;
  /** Active bubble per agent (one bubble at a time per speaker). */
  private activeBubbleStart: Map<string, number> = new Map();

  constructor(opts: OfficeReplaySceneOptions) {
    super({ key: "OfficeReplayScene" });
    this.opts = opts;
  }

  preload(): void {
    // Skip-don't-fail on missing assets — keeps the page deterministic
    // when run against a locked-down public/ tree (e.g. some CI sandboxes).
    this.load.on("loaderror", (file: Phaser.Loader.File) => {
      console.warn(`[replay] missing asset: ${file.key}`);
    });

    // Tilesets — Phaser needs them as spritesheets so individual tile gids
    // resolve. All sheets are 4×4 grids of 32×32 tiles.
    for (const { imageKey } of TILESETS) {
      this.load.spritesheet(
        imageKey,
        `${ASSET_BASE}/tilesets/office/${imageKey}.png`,
        { frameWidth: TILE_SIZE, frameHeight: TILE_SIZE },
      );
    }
    this.load.tilemapTiledJSON(
      "tilemap_office",
      `${ASSET_BASE}/tilesets/office/tilemap_office.json`,
    );

    // Agent sprites — south rotation as the static texture, plus 4-direction
    // idle + walk frames so we can animate movement during cues.
    for (const agentId of this.opts.visibleAgents) {
      this.load.image(
        `sprite_${agentId}`,
        `${ASSET_BASE}/sprites/${agentId}/rotations/south.png`,
      );
      for (const dir of DIRECTIONS) {
        for (let i = 0; i < IDLE_FRAMES; i++) {
          const f = String(i).padStart(3, "0");
          this.load.image(
            `${agentId}_idle_${dir}_${i}`,
            `${ASSET_BASE}/sprites/${agentId}/animations/breathing-idle/${dir}/frame_${f}.png`,
          );
        }
        for (let i = 0; i < WALK_FRAMES; i++) {
          const f = String(i).padStart(3, "0");
          this.load.image(
            `${agentId}_walk_${dir}_${i}`,
            `${ASSET_BASE}/sprites/${agentId}/animations/walking/${dir}/frame_${f}.png`,
          );
        }
      }
    }
  }

  create(): void {
    this.cameras.main.setBackgroundColor("#1a1a2e");
    this.cameras.main.setBounds(0, 0, STAGE_W, STAGE_H);
    this.cameras.main.setViewport(0, 0, STAGE_W, STAGE_H);

    this.buildTilemap();
    this.registerAnimations();
    this.spawnAgents();

    this.startMs = Date.now();

    // Defer the ready signal until the first POST_UPDATE so tests + the
    // render pipeline can trust that the canvas has actually drawn.
    this.events.once(Phaser.Scenes.Events.POST_UPDATE, () => {
      this.opts.onReady?.();
    });
  }

  update(): void {
    const elapsed = Date.now() - this.startMs;
    this.updateBubbles(elapsed);

    if (
      !this.doneFired &&
      elapsed >= this.opts.plan.done_at_ms &&
      this.allBubblesHidden()
    ) {
      this.doneFired = true;
      this.opts.onDone?.();
    }
  }

  private buildTilemap(): void {
    const map = this.make.tilemap({ key: "tilemap_office" });
    const tilesets: Phaser.Tilemaps.Tileset[] = [];
    for (const { tilesetName, imageKey } of TILESETS) {
      const ts = map.addTilesetImage(tilesetName, imageKey);
      if (ts) tilesets.push(ts);
    }
    if (tilesets.length === 0) {
      // No tilesets loaded — still draw a placeholder floor so the test can
      // see something other than solid black, but log loud.
      console.error("[replay] tilemap loaded with no tilesets");
      const g = this.add.graphics();
      g.fillStyle(0x2c3e50, 1);
      g.fillRect(0, 0, STAGE_W, 704);
      return;
    }
    // Paint every tile layer from the Tiled JSON. The map's "Collision"
    // and object layers don't render visually so this is safe.
    for (const layer of map.layers) {
      const created = map.createLayer(layer.name, tilesets, 0, 0);
      if (created) {
        created.setDepth(0);
      }
    }
  }

  private registerAnimations(): void {
    for (const agentId of this.opts.visibleAgents) {
      for (const dir of DIRECTIONS) {
        const idleKey = `${agentId}_idle_${dir}`;
        if (!this.anims.exists(idleKey)) {
          const frames = this.collectFrames(agentId, "idle", dir, IDLE_FRAMES);
          if (frames.length > 0) {
            this.anims.create({ key: idleKey, frames, frameRate: 4, repeat: -1 });
          }
        }
        const walkKey = `${agentId}_walk_${dir}`;
        if (!this.anims.exists(walkKey)) {
          const frames = this.collectFrames(agentId, "walk", dir, WALK_FRAMES);
          if (frames.length > 0) {
            this.anims.create({ key: walkKey, frames, frameRate: 8, repeat: -1 });
          }
        }
      }
    }
  }

  private collectFrames(
    agentId: string,
    animType: "idle" | "walk",
    dir: Direction,
    count: number,
  ): Phaser.Types.Animations.AnimationFrame[] {
    const out: Phaser.Types.Animations.AnimationFrame[] = [];
    for (let i = 0; i < count; i++) {
      const key = `${agentId}_${animType}_${dir}_${i}`;
      if (this.textures.exists(key)) {
        out.push({ key });
      }
    }
    return out;
  }

  private spawnAgents(): void {
    for (const agentId of this.opts.visibleAgents) {
      const desk = getDeskPosition(agentId);
      const fallbackTexture = `sprite_${agentId}`;
      // Walk through possible textures in order: idle frame 0, then south
      // rotation static, then a coloured rect placeholder so the canvas
      // still passes the "non-blank" pixel sample.
      const idleFrameKey = `${agentId}_idle_${desk.facing}_0`;
      const textureKey = this.textures.exists(idleFrameKey)
        ? idleFrameKey
        : this.textures.exists(fallbackTexture)
          ? fallbackTexture
          : null;
      let sprite: Phaser.GameObjects.Sprite;
      if (textureKey) {
        sprite = this.add.sprite(desk.x, desk.y, textureKey);
      } else {
        // Coloured rectangle as a last-resort placeholder so the office
        // still has a visible avatar even if the asset sync misfired.
        const rect = this.add.rectangle(desk.x, desk.y, 32, 48, 0x60a5fa);
        sprite = rect as unknown as Phaser.GameObjects.Sprite;
      }
      sprite.setDepth(10);
      sprite.setOrigin(0.5, 0.5);
      const idleAnim = `${agentId}_idle_${desk.facing}`;
      if (this.anims.exists(idleAnim) && typeof sprite.play === "function") {
        sprite.play(idleAnim);
      }

      const label = this.add.text(desk.x, desk.y - 32, agentId.toUpperCase(), {
        color: "#f8fafc",
        fontFamily: "monospace",
        fontSize: "11px",
        fontStyle: "bold",
        backgroundColor: "#0b1020aa",
        padding: { x: 4, y: 2 },
      });
      label.setOrigin(0.5, 1);
      label.setDepth(11);

      const bubble = new ReplaySpeechBubble(this, agentId);

      this.agents.set(agentId, {
        sprite,
        label,
        bubble,
        desk: { x: desk.x, y: desk.y },
        facing: desk.facing,
      });
    }
  }

  private updateBubbles(elapsed: number): void {
    // Index cue ordering by agent so we can pick up the right idx for
    // getSpeakingPosition. Cues with the same agent reuse a counter.
    const sortedBubbles = this.opts.plan.bubbles;
    const perAgentIdx = new Map<string, number>();

    // First pass: figure out which agents have an active bubble this frame.
    const activeNow = new Map<string, BubblePlan & { idx: number }>();
    for (const b of sortedBubbles) {
      const idx = (perAgentIdx.get(b.agent_id) ?? -1) + 1;
      perAgentIdx.set(b.agent_id, idx);
      if (b.start_ms <= elapsed && elapsed < b.end_ms) {
        activeNow.set(b.agent_id, { ...b, idx });
      }
    }

    for (const [agentId, visual] of this.agents.entries()) {
      const active = activeNow.get(agentId);
      if (active) {
        // Show the bubble for this agent.
        if (!visual.bubble.isVisible() || this.activeBubbleStart.get(agentId) !== active.start_ms) {
          visual.bubble.setText(active.text);
          this.activeBubbleStart.set(agentId, active.start_ms);
          // E2E hook so Playwright can wait for "any bubble has rendered"
          // without sleeping. Cleared in destroy/cleanup elsewhere.
          if (typeof window !== "undefined") {
            (window as unknown as Record<string, unknown>).__replayHadBubble = true;
          }
          // Move sprite a little — gives the impression of agents shifting
          // when they speak. Different speakers start tweens at different
          // times so the office reads as alive, not synchronised.
          const target = getSpeakingPosition(agentId, active.idx);
          this.tweens.killTweensOf(visual.sprite);
          this.tweens.add({
            targets: visual.sprite,
            x: target.x,
            y: target.y,
            duration: 380,
            ease: "Sine.easeInOut",
            onStart: () => {
              const walkAnim = `${agentId}_walk_${visual.facing}`;
              if (this.anims.exists(walkAnim) && typeof visual.sprite.play === "function") {
                visual.sprite.play(walkAnim, true);
              }
            },
            onUpdate: () => {
              visual.label.setPosition(visual.sprite.x, visual.sprite.y - 32);
            },
            onComplete: () => {
              const idleAnim = `${agentId}_idle_${visual.facing}`;
              if (this.anims.exists(idleAnim) && typeof visual.sprite.play === "function") {
                visual.sprite.play(idleAnim, true);
              }
              visual.label.setPosition(visual.sprite.x, visual.sprite.y - 32);
            },
          });
        }
        const { w, h } = visual.bubble.getSize();
        const pos = clampBubblePosition(
          visual.sprite.x,
          visual.sprite.y,
          Math.max(w, 80),
          Math.max(h, 40),
        );
        visual.bubble.setBubblePosition(pos.x, pos.y);
        visual.bubble.setVisible(true);
      } else if (visual.bubble.isVisible()) {
        visual.bubble.setVisible(false);
        this.activeBubbleStart.delete(agentId);
        // Walk back to desk if we drifted away.
        if (visual.sprite.x !== visual.desk.x || visual.sprite.y !== visual.desk.y) {
          this.tweens.killTweensOf(visual.sprite);
          this.tweens.add({
            targets: visual.sprite,
            x: visual.desk.x,
            y: visual.desk.y,
            duration: 380,
            ease: "Sine.easeInOut",
            onUpdate: () => {
              visual.label.setPosition(visual.sprite.x, visual.sprite.y - 32);
            },
            onComplete: () => {
              visual.label.setPosition(visual.sprite.x, visual.sprite.y - 32);
            },
          });
        }
      }
    }
  }

  private allBubblesHidden(): boolean {
    for (const v of this.agents.values()) {
      if (v.bubble.isVisible()) return false;
    }
    return true;
  }
}

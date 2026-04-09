import Phaser from "phaser";
import { WorldManager } from "../world/WorldManager";
import { AgentSpriteManager } from "../agents/AgentSpriteManager";
import { SpeechBubbleManager } from "../ui/SpeechBubbleManager";
import { StreamOverlay } from "../ui/StreamOverlay";
import { AudioManager } from "../audio/AudioManager";
import { WebSocketClient } from "../network/WebSocketClient";
import { AGENTS } from "../agents";

const TILE_SIZE = 32;

/** Agents that have sprite assets (excludes management). */
const SPRITE_AGENT_IDS = AGENTS
  .filter((a) => a.spriteSize > 0)
  .map((a) => a.id);


/** Cardinal + ordinal directions available for animations. */
const DIRECTIONS = [
  "south",
  "south-east",
  "east",
  "north-east",
  "north",
  "north-west",
  "west",
  "south-west",
] as const;

/** Number of frames per animation type. */
const IDLE_FRAME_COUNT = 4;
const WALK_FRAME_COUNT = 6;

/**
 * Furniture objects placed as sprites on top of the tile layer.
 * Positions are in pixel coordinates (tile * 32).
 */
interface FurniturePlacement {
  key: string;
  x: number;
  y: number;
}

// Desk image is 96px wide. Desk x is top-left. Agent stands at desk center x (desk.x + 48).
// Top row: desks at y=2 tiles, chairs at y=5, agents at y=5 (below desk)
// Bottom row: desks at y=17 tiles, chairs at y=16, agents at y=16 (above desk)
const DESK_TOP_Y = 2;     // desk tile row (top)
const DESK_BOT_Y = 17;    // desk tile row (bottom)

// Top-row desk x positions (in tiles, left edge of 3-tile-wide desk)
const TOP_DESKS = [2, 10, 24, 33]; // Vera, Aurora, Sentinel, Grok
// Bottom-row desk x positions
const BOT_DESKS = [2, 10, 24];     // Rex, Fork, Pixel

const FURNITURE: FurniturePlacement[] = [
  // Top-row desks + chairs
  ...TOP_DESKS.map(tx => ({ key: "desk", x: tx * 32, y: DESK_TOP_Y * 32 })),
  ...TOP_DESKS.map(tx => ({ key: "chair", x: (tx + 1) * 32, y: (DESK_TOP_Y + 3) * 32 })),
  // Bottom-row desks + chairs
  ...BOT_DESKS.map(tx => ({ key: "desk", x: tx * 32, y: DESK_BOT_Y * 32 })),
  ...BOT_DESKS.map(tx => ({ key: "chair", x: (tx + 1) * 32, y: (DESK_BOT_Y - 1) * 32 })),
  // Center: meeting table + rug
  { key: "rug", x: 16 * 32, y: 7 * 32 },
  { key: "meeting_table", x: 15 * 32, y: 7 * 32 },
  // Workshop below meeting
  { key: "workshop_bench", x: 15 * 32, y: 13 * 32 },
  // Coffee machine (top center between Aurora and Sentinel)
  { key: "coffee_machine", x: 19 * 32, y: 2 * 32 },
  // Bookshelf + whiteboard on right side
  { key: "bookshelf", x: 35 * 32, y: 12 * 32 },
  { key: "whiteboard", x: 33 * 32, y: 17 * 32 },
  // Plants in corners
  { key: "plant", x: 1 * 32, y: 1 * 32 },
  { key: "plant", x: 38 * 32, y: 1 * 32 },
  { key: "plant", x: 1 * 32, y: 20 * 32 },
  { key: "plant", x: 38 * 32, y: 20 * 32 },
];

export class MainScene extends Phaser.Scene {
  private worldManager: WorldManager | null = null;
  private agentSpriteManager: AgentSpriteManager | null = null;
  private speechBubbleManager: SpeechBubbleManager | null = null;
  private streamOverlay: StreamOverlay | null = null;
  private audioManager: AudioManager | null = null;
  private wsClient: WebSocketClient | null = null;

  constructor() {
    super({ key: "MainScene" });
  }

  setWebSocketClient(client: WebSocketClient): void {
    this.wsClient = client;
  }

  preload(): void {
    // Silently skip missing asset files (e.g. Grok missing some directions)
    this.load.on("loaderror", (file: Phaser.Loader.File) => {
      console.warn(`Skipping missing asset: ${file.key}`);
    });

    // ── Tileset spritesheet + tilemap JSON ────────────────────────
    this.load.spritesheet("office_tiles", "assets/tilesets/office/tileset.png", {
      frameWidth: TILE_SIZE,
      frameHeight: TILE_SIZE,
    });
    this.load.tilemapTiledJSON("tilemap_office", "assets/tilesets/office/tilemap_office.json");

    // ── Agent rotation sprites (default facing south) ───────────
    for (const agentId of SPRITE_AGENT_IDS) {
      // Load south rotation as the default sprite texture
      this.load.image(
        `sprite_${agentId}`,
        `assets/sprites/${agentId}/rotations/south.png`,
      );

      // Load all rotation images
      for (const dir of DIRECTIONS) {
        this.load.image(
          `${agentId}_rot_${dir}`,
          `assets/sprites/${agentId}/rotations/${dir}.png`,
        );
      }

      // Load idle animation frames (breathing-idle)
      for (const dir of DIRECTIONS) {
        for (let i = 0; i < IDLE_FRAME_COUNT; i++) {
          const frame = String(i).padStart(3, "0");
          this.load.image(
            `${agentId}_idle_${dir}_${i}`,
            `assets/sprites/${agentId}/animations/breathing-idle/${dir}/frame_${frame}.png`,
          );
        }
      }

      // Load walking animation frames
      for (const dir of DIRECTIONS) {
        for (let i = 0; i < WALK_FRAME_COUNT; i++) {
          const frame = String(i).padStart(3, "0");
          this.load.image(
            `${agentId}_walk_${dir}_${i}`,
            `assets/sprites/${agentId}/animations/walking/${dir}/frame_${frame}.png`,
          );
        }
      }
    }

    // ── Furniture object images ─────────────────────────────────
    const furnitureItems = [
      "desk",
      "meeting_table",
      "workshop_bench",
      "whiteboard",
      "coffee_machine",
      "chair",
      "bookshelf",
      "plant",
      "rug",
    ];
    for (const item of furnitureItems) {
      this.load.image(item, `assets/tilesets/office/objects/${item}.png`);
    }

  }

  create(): void {
    this.cameras.main.setBackgroundColor("#1a1a2e");

    // ── WebSocket client (auto-create if not externally provided) ──
    if (!this.wsClient) {
      this.wsClient = new WebSocketClient();
      this.wsClient.connect();
    }

    // ── Register agent animations ───────────────────────────────
    this.registerAnimations();

    // ── World (tilemap + collision) ─────────────────────────────
    this.worldManager = new WorldManager(this);
    this.worldManager.create();

    // ── Place furniture sprites on top of tiles ─────────────────
    this.placeFurniture();

    // ── Create agent sprites at their desk positions ────────────
    this.agentSpriteManager = new AgentSpriteManager(
      this,
      this.wsClient,
      this.worldManager,
    );

    // ── Audio playback (TTS queue) ───────────────────────────────
    this.audioManager = new AudioManager(this.wsClient);

    // ── Speech bubbles (DOM overlay above canvas) ──────────────
    this.speechBubbleManager = new SpeechBubbleManager(
      this,
      this.wsClient,
      this.agentSpriteManager,
      this.audioManager,
    );

    // ── Stream overlay (budget, AGI progress, viewers, topic, agent status) ──
    this.streamOverlay = new StreamOverlay(this.wsClient);
  }

  getWorldManager(): WorldManager | null {
    return this.worldManager;
  }

  getAgentSpriteManager(): AgentSpriteManager | null {
    return this.agentSpriteManager;
  }

  update(): void {
    this.speechBubbleManager?.update();
  }

  shutdown(): void {
    this.speechBubbleManager?.destroy();
    this.speechBubbleManager = null;
    this.streamOverlay?.destroy();
    this.streamOverlay = null;
    this.audioManager?.destroy();
    this.audioManager = null;
    this.agentSpriteManager?.destroy();
    this.agentSpriteManager = null;
    this.worldManager?.destroy();
    this.worldManager = null;
    this.wsClient?.disconnect();
    this.wsClient = null;
  }

  /**
   * Register Phaser animations for each agent from loaded frame images.
   * Skips animations whose textures failed to load (e.g. missing directions).
   */
  private registerAnimations(): void {
    for (const agentId of SPRITE_AGENT_IDS) {
      // Idle animation (south-facing, used as default)
      this.tryCreateAnim(`${agentId}_idle`, agentId, "idle", "south", IDLE_FRAME_COUNT, 4);

      // Walking animations mapped to directional names
      const walkMapping: Record<string, string> = {
        walk_down: "south",
        walk_up: "north",
        walk_right: "east",
        walk_left: "west",
      };

      for (const [animName, direction] of Object.entries(walkMapping)) {
        this.tryCreateAnim(`${agentId}_${animName}`, agentId, "walk", direction, WALK_FRAME_COUNT, 8);
      }

      // Talking = idle south-east, fallback to south
      if (!this.tryCreateAnim(`${agentId}_talking`, agentId, "idle", "south-east", IDLE_FRAME_COUNT, 6)) {
        this.tryCreateAnim(`${agentId}_talking`, agentId, "idle", "south", IDLE_FRAME_COUNT, 6);
      }

      // Thinking = idle north (looking up)
      this.tryCreateAnim(`${agentId}_thinking`, agentId, "idle", "north", IDLE_FRAME_COUNT, 3);

      // Building = idle east (focused sideways)
      this.tryCreateAnim(`${agentId}_building`, agentId, "idle", "east", IDLE_FRAME_COUNT, 5);
    }
  }

  /**
   * Try to create an animation. Returns false if any frame texture is missing.
   */
  private tryCreateAnim(
    key: string,
    agentId: string,
    animType: string,
    direction: string,
    frameCount: number,
    frameRate: number,
  ): boolean {
    const frames = this.buildFrameKeys(agentId, animType, direction, frameCount);
    // Check all frame textures exist
    for (const frame of frames) {
      if (!this.textures.exists(frame.key!)) {
        return false;
      }
    }
    this.anims.create({ key, frames, frameRate, repeat: -1 });
    return true;
  }

  /**
   * Build an array of frame config objects for a multi-image animation.
   * Each frame was loaded as a separate image, so we create texture-key frames.
   */
  private buildFrameKeys(
    agentId: string,
    animType: string,
    direction: string,
    frameCount: number,
  ): Phaser.Types.Animations.AnimationFrame[] {
    const frames: Phaser.Types.Animations.AnimationFrame[] = [];
    for (let i = 0; i < frameCount; i++) {
      frames.push({ key: `${agentId}_${animType}_${direction}_${i}` });
    }
    return frames;
  }

  /**
   * Place furniture objects as sprites on top of the tile layer.
   */
  private placeFurniture(): void {
    for (const item of FURNITURE) {
      const sprite = this.add.image(item.x, item.y, item.key);
      sprite.setOrigin(0, 0);
      // Furniture renders above ground tiles but below agents
      sprite.setDepth(1);
    }
  }
}

import Phaser from "phaser";
import { WorldManager } from "../world/WorldManager";
import { WorkspaceManager } from "../world/WorkspaceManager";
import { FurnitureCatalog, FurnitureInstance } from "../world/furniture";
import { AgentSpriteManager } from "../agents/AgentSpriteManager";
import { SpeechBubbleManager } from "../ui/SpeechBubbleManager";
import { StreamOverlay } from "../ui/StreamOverlay";
import { DevPanel } from "../ui/DevPanel";
import { AudioManager } from "../audio/AudioManager";
import { BehaviorScheduler } from "../agents/BehaviorScheduler";
import { WebSocketClient } from "../network/WebSocketClient";
import { AGENTS } from "../agents";
import furnitureManifestsData from "../world/furniture/furniture-manifests.json";

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

/** Shared furniture not tied to any agent workspace. */
const SHARED_FURNITURE: Array<{ key: string; x: number; y: number }> = [
  { key: "rug", x: 16 * 32, y: 7 * 32 },
  { key: "meeting_table", x: 15 * 32, y: 7 * 32 },
  { key: "workshop_bench", x: 15 * 32, y: 13 * 32 },
  { key: "coffee_machine", x: 19 * 32, y: 2 * 32 },
  { key: "bookshelf", x: 35 * 32, y: 12 * 32 },
  { key: "whiteboard", x: 33 * 32, y: 17 * 32 },
  { key: "plant", x: 1 * 32, y: 1 * 32 },
  { key: "plant", x: 38 * 32, y: 1 * 32 },
  { key: "plant", x: 1 * 32, y: 20 * 32 },
  { key: "plant", x: 38 * 32, y: 20 * 32 },
];

export class MainScene extends Phaser.Scene {
  private worldManager: WorldManager | null = null;
  private workspaceManager: WorkspaceManager | null = null;
  private furnitureCatalog: FurnitureCatalog | null = null;
  private furnitureInstances: Map<string, FurnitureInstance> = new Map();
  /** Furniture instances grouped by agent workspace (agentId → instances). */
  private workspaceFurniture: Map<string, FurnitureInstance[]> = new Map();
  private agentSpriteManager: AgentSpriteManager | null = null;
  private speechBubbleManager: SpeechBubbleManager | null = null;
  private streamOverlay: StreamOverlay | null = null;
  private devPanel: DevPanel | null = null;
  private audioManager: AudioManager | null = null;
  private behaviorScheduler: BehaviorScheduler | null = null;
  private wsClient: WebSocketClient | null = null;
  private connectionOverlay: Phaser.GameObjects.Text | null = null;

  constructor() {
    super({ key: "MainScene" });
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
    // Collect all unique furniture keys from shared furniture and workspace definitions
    const furnitureKeys = new Set<string>();
    for (const item of SHARED_FURNITURE) {
      furnitureKeys.add(item.key);
    }
    for (const key of WorkspaceManager.getAllFurnitureKeys()) {
      furnitureKeys.add(key);
    }
    // Add state texture keys from furniture manifests (e.g. monitor_on, monitor_off)
    const tempCatalog = FurnitureCatalog.fromArray(furnitureManifestsData as any);
    for (const key of tempCatalog.getAllTextureKeys()) {
      furnitureKeys.add(key);
    }
    for (const item of furnitureKeys) {
      this.load.image(item, `assets/tilesets/office/objects/${item}.png`);
    }

  }

  create(): void {
    this.cameras.main.setBackgroundColor("#1a1a2e");

    // ── Register agent animations ───────────────────────────────
    this.registerAnimations();

    // ── World (tilemap + collision) ─────────────────────────────
    this.worldManager = new WorldManager(this);
    this.worldManager.create();

    // ── Workspace manager (agent desk areas) ────────────────────
    this.workspaceManager = new WorkspaceManager(this.worldManager);

    // ── Furniture catalog (JSON-driven manifests) ───────────────
    this.furnitureCatalog = FurnitureCatalog.fromArray(furnitureManifestsData as any);

    // ── Place furniture sprites on top of tiles ─────────────────
    this.placeFurniture();

    // ── WebSocket connection to backend ─────────────────────────
    const wsUrl = import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws";
    this.wsClient = new WebSocketClient(wsUrl);

    // ── Connection status overlay ───────────────────────────────
    this.connectionOverlay = this.add.text(
      this.cameras.main.centerX,
      this.cameras.main.centerY,
      "Connecting...",
      {
        fontSize: "16px",
        color: "#ffffff",
        fontFamily: "monospace",
        backgroundColor: "#000000aa",
        padding: { x: 12, y: 8 },
      },
    );
    this.connectionOverlay.setOrigin(0.5, 0.5);
    this.connectionOverlay.setScrollFactor(0);
    this.connectionOverlay.setDepth(100);

    this.wsClient.onConnect = () => {
      this.connectionOverlay?.setVisible(false);
    };
    this.wsClient.onDisconnect = () => {
      if (this.connectionOverlay) {
        this.connectionOverlay.setText("Reconnecting...");
        this.connectionOverlay.setVisible(true);
      }
    };

    this.wsClient.connect();

    // ── Create agent sprites at their desk positions ────────────
    this.agentSpriteManager = new AgentSpriteManager(
      this,
      this.wsClient,
      this.worldManager,
      this.workspaceManager,
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

    // ── Dev panel (test conversation trigger) ──────────────
    this.devPanel = new DevPanel();

    // ── Idle behavior scheduler (client-side micro-animations) ──
    this.behaviorScheduler = new BehaviorScheduler(
      this.agentSpriteManager.getSpriteMap(),
    );


    // ── Clean up WebSocket on scene shutdown ────────────────────
    this.events.on("shutdown", () => {
      this.wsClient?.disconnect();
    });
  }

  getWorldManager(): WorldManager | null {
    return this.worldManager;
  }

  getAgentSpriteManager(): AgentSpriteManager | null {
    return this.agentSpriteManager;
  }

  update(_time: number, delta: number): void {
    this.speechBubbleManager?.update();
    this.behaviorScheduler?.update(delta);
  }

  shutdown(): void {
    this.speechBubbleManager?.destroy();
    this.speechBubbleManager = null;
    this.streamOverlay?.destroy();
    this.streamOverlay = null;
    this.devPanel?.destroy();
    this.devPanel = null;
    this.audioManager?.destroy();
    this.audioManager = null;
    this.behaviorScheduler?.destroy();
    this.behaviorScheduler = null;
    this.agentSpriteManager?.destroy();
    this.agentSpriteManager = null;
    for (const instance of this.furnitureInstances.values()) {
      instance.destroy();
    }
    this.furnitureInstances.clear();
    this.workspaceFurniture.clear();
    this.furnitureCatalog = null;
    this.workspaceManager = null;
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
   * Creates FurnitureInstance objects for manifest-backed items (enabling state changes),
   * and falls back to raw sprites for shared furniture without manifests.
   */
  private placeFurniture(): void {
    // Place shared furniture
    for (const item of SHARED_FURNITURE) {
      const manifest = this.furnitureCatalog?.getManifest(item.key.toUpperCase());
      if (manifest && this.textures.exists(this.getFurnitureTextureKey(manifest))) {
        const instanceKey = `shared_${item.key}_${item.x}_${item.y}`;
        const instance = new FurnitureInstance(this, manifest, item.x, item.y);
        this.furnitureInstances.set(instanceKey, instance);
      } else if (this.textures.exists(item.key)) {
        const sprite = this.add.image(item.x, item.y, item.key);
        sprite.setOrigin(0, 0);
        sprite.setDepth(1);
      }
    }

    // Place per-agent workspace furniture
    if (this.workspaceManager) {
      for (const agent of AGENTS) {
        const items = this.workspaceManager.getWorkspaceFurniture(agent.id);
        const agentInstances: FurnitureInstance[] = [];

        for (const item of items) {
          const manifest = this.furnitureCatalog?.getManifest(item.key.toUpperCase());
          if (manifest && this.textures.exists(this.getFurnitureTextureKey(manifest))) {
            const instanceKey = `${agent.id}_${item.key}_${item.x}_${item.y}`;
            const instance = new FurnitureInstance(this, manifest, item.x, item.y);
            this.furnitureInstances.set(instanceKey, instance);
            agentInstances.push(instance);
          } else if (this.textures.exists(item.key)) {
            const sprite = this.add.image(item.x, item.y, item.key);
            sprite.setOrigin(0, 0);
            sprite.setDepth(1);
          }
        }

        if (agentInstances.length > 0) {
          this.workspaceFurniture.set(agent.id, agentInstances);
        }
      }
    }
  }

  /**
   * Resolve the initial texture key for a furniture manifest.
   */
  private getFurnitureTextureKey(manifest: import("../world/furniture").FurnitureManifest): string {
    if (manifest.states) {
      if (manifest.states["off"]) return manifest.states["off"];
      const firstKey = Object.values(manifest.states)[0];
      if (firstKey) return firstKey;
    }
    return manifest.id.toLowerCase();
  }
}

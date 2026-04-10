import Phaser from "phaser";
import { WorldManager } from "../world/WorldManager";
import { WorkspaceManager } from "../world/WorkspaceManager";
import { FurnitureCatalog, FurnitureInstance, AutoStateManager } from "../world/furniture";
import { AgentSpriteManager } from "../agents/AgentSpriteManager";
import { SpeechBubbleManager } from "../ui/SpeechBubbleManager";
import { StreamOverlay } from "../ui/StreamOverlay";
import { OverlayManager } from "../ui/OverlayManager";
import { DevPanel } from "../ui/DevPanel";
import { AudioManager } from "../audio/AudioManager";
import { BehaviorScheduler } from "../agents/BehaviorScheduler";
import { ManagementEffects } from "../effects/ManagementEffects";
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
// Continuous brick wall across north side of each room row.
// Base: solid brick tiles spanning full width. Decorations layered on top.
// Windows only on exterior wall (row 0). Interior walls (row 11, 17) get decor only.
const WALL_TILES: Array<{ key: string; x: number; y: number }> = [];

// Helper: fill a row range with brick, then overlay decorations.
// doorways: columns to skip (2-tile wide openings for walkways)
// Adds corner tiles at wall ends and doorway edges.
function addWallRow(
  row: number,
  colStart: number,
  colEnd: number,
  decorations: Array<{ col: number; key: string }>,
  doorways: number[] = [],
) {
  // Build sets: columns to skip (doorway) and columns that get corner tiles
  const skip = new Set<number>();
  const cornerCols = new Map<number, string>(); // col → corner key
  for (const d of doorways) {
    skip.add(d);
    skip.add(d + 1);
    // Corners replace the brick tiles adjacent to the gap
    cornerCols.set(d - 1, "wall_corner_right"); // end of left segment
    cornerCols.set(d + 2, "wall_corner_left");  // start of right segment
  }
  // Outer corners
  cornerCols.set(colStart - 1, "wall_corner_left");
  cornerCols.set(colEnd + 1, "wall_corner_right");

  // Place outer corners
  WALL_TILES.push({ key: "wall_corner_left", x: (colStart - 1) * 32, y: row * 32 });
  WALL_TILES.push({ key: "wall_corner_right", x: (colEnd + 1) * 32, y: row * 32 });

  // Base brick across range, replacing doorway-adjacent tiles with corners
  for (let c = colStart; c <= colEnd; c++) {
    if (skip.has(c)) continue;
    if (cornerCols.has(c)) {
      WALL_TILES.push({ key: cornerCols.get(c)!, x: c * 32, y: row * 32 });
    } else {
      WALL_TILES.push({ key: "wall_brick", x: c * 32, y: row * 32 });
    }
  }
  // Decorations on top of brick positions (skip doorways and corners)
  for (const d of decorations) {
    if (skip.has(d.col) || cornerCols.has(d.col)) continue;
    WALL_TILES.push({ key: d.key, x: d.col * 32, y: row * 32 });
  }
}

// ── EXTERIOR north wall (row 0, cols 1-38) — windows allowed ──
addWallRow(0, 1, 38, [
  // Vera's Office (cols 1-9)
  { col: 2, key: "wall_window" },
  { col: 4, key: "wall_bookshelf" },
  { col: 5, key: "wall_bookshelf2" },
  { col: 7, key: "wall_window2" },
  // Kitchen (cols 10-20)
  { col: 11, key: "wall_cabinet" },
  { col: 12, key: "wall_cabinet" },
  { col: 14, key: "wall_window" },
  { col: 17, key: "wall_window2" },
  { col: 18, key: "wall_cabinet" },
  { col: 19, key: "wall_cabinet" },
  // Dev Bay (cols 21-38)
  { col: 22, key: "wall_window" },
  { col: 24, key: "wall_bookshelf" },
  { col: 25, key: "wall_whiteboard" },
  { col: 28, key: "wall_window2" },
  { col: 30, key: "wall_whiteboard" },
  { col: 31, key: "wall_bookshelf2" },
  { col: 33, key: "wall_window" },
  { col: 35, key: "wall_bookshelf" },
  { col: 37, key: "wall_window2" },
]);

// ── INTERIOR wall (row 11, cols 1-38) — no windows, doorways between N/S ──
// Doorways at: col 5 (Vera↔Rex), col 15 (Kitchen↔Aurora), col 25 (DevBay↔Grok), col 34 (DevBay↔Meeting)
addWallRow(11, 1, 38, [
  // Rex's Workshop (cols 1-9)
  { col: 1, key: "wall_pegboard" },
  { col: 2, key: "wall_pegboard" },
  { col: 4, key: "wall_bookshelf" },
  { col: 7, key: "wall_pegboard" },
  { col: 8, key: "wall_bookshelf2" },
  // Aurora's Studio (cols 10-20)
  { col: 11, key: "wall_bookshelf" },
  { col: 13, key: "wall_whiteboard" },
  { col: 14, key: "wall_bookshelf2" },
  { col: 18, key: "wall_bookshelf" },
  // Grok's Den (cols 21-30)
  { col: 23, key: "wall_bookshelf" },
  { col: 24, key: "wall_bookshelf2" },
  { col: 27, key: "wall_whiteboard" },
  { col: 29, key: "wall_bookshelf" },
  // Meeting Area (cols 31-38)
  { col: 32, key: "wall_whiteboard" },
  { col: 33, key: "wall_whiteboard" },
  { col: 38, key: "wall_bookshelf" },
], [5, 15, 25, 34]);

// ── INTERIOR wall (row 17, cols 32-38) — Alpha/Management, doorway at col 34 ──
addWallRow(17, 32, 38, [
  { col: 33, key: "wall_bookshelf" },
  { col: 36, key: "wall_bookshelf2" },
], [34]);

// ── Side wall tiles (thin brick edge along left/right room walls) ──
// Helper: add side tiles for a column, skipping doorway rows
function addSideCol(col: number, rowStart: number, rowEnd: number, key: string, skipRows: number[] = []) {
  const skip = new Set(skipRows);
  for (let r = rowStart; r <= rowEnd; r++) {
    if (skip.has(r)) continue;
    WALL_TILES.push({ key, x: col * 32, y: r * 32 });
  }
}

// ── Top rooms (rows 1-10) ──
// Vera (cols 0-9, hardwood floor)
addSideCol(0, 1, 10, "side_left_hardwood");                    // left exterior wall
addSideCol(9, 1, 10, "side_right_hardwood", [4, 5]);           // right wall, doorway rows 4-5
// Kitchen (cols 10-20, whitetile floor)
addSideCol(10, 1, 10, "side_left_whitetile", [4, 5]);          // left wall, doorway rows 4-5
addSideCol(20, 1, 10, "side_right_whitetile", [4, 5]);         // right wall, doorway rows 4-5
// Dev Bay (cols 21-39, bluegrey floor)
addSideCol(21, 1, 10, "side_left_bluegrey", [4, 5]);           // left wall, doorway rows 4-5
addSideCol(39, 1, 10, "side_right_bluegrey");                   // right exterior wall

// ── Bottom rooms (rows 12-20) ──
// Rex (cols 0-9, concrete floor)
addSideCol(0, 12, 20, "side_left_concrete", [15, 16]);        // left exterior, skip exterior door
addSideCol(9, 12, 20, "side_right_concrete", [15, 16]);       // right wall, doorway rows 15-16
// Aurora (cols 10-20, teal floor)
addSideCol(10, 12, 20, "side_left_teal", [15, 16]);           // left wall, doorway rows 15-16
addSideCol(20, 12, 20, "side_right_teal", [15, 16]);          // right wall, doorway rows 15-16
// Grok (cols 21-30, purple floor)
addSideCol(21, 12, 20, "side_left_purple", [15, 16]);         // left wall, doorway rows 15-16
addSideCol(30, 12, 20, "side_right_purple", [15, 16]);        // right wall, doorway rows 15-16
// Meeting (cols 31-39, bluegrey floor, rows 12-16)
addSideCol(31, 12, 16, "side_left_bluegrey", [13, 14]);       // left wall, doorway rows 13-14
addSideCol(39, 12, 16, "side_right_bluegrey", [13, 14]);      // right exterior, skip exterior door
// Alpha/Management (cols 31-39, olive floor, rows 18-20)
addSideCol(31, 18, 20, "side_left_olive");                     // left wall
addSideCol(39, 18, 20, "side_right_olive");                    // right exterior wall

// Freestanding furniture (not against walls)
const SHARED_FURNITURE: Array<{ key: string; x: number; y: number }> = [
  // Kitchen area
  { key: "coffee_machine", x: 15 * 32, y: 2 * 32 },
  { key: "fridge", x: 17 * 32, y: 2 * 32 },
  { key: "cafe_table", x: 14 * 32, y: 5 * 32 },
  // Meeting area
  { key: "rug", x: 34 * 32, y: 13 * 32 },
  { key: "meeting_table", x: 34 * 32, y: 12 * 32 },
  // Dev Bay
  { key: "workshop_bench", x: 28 * 32, y: 6 * 32 },
  // Rex's Workshop — plants
  { key: "plant", x: 1 * 32, y: 20 * 32 },
  { key: "plant", x: 8 * 32, y: 20 * 32 },
  // Vera's Office — plant
  { key: "plant", x: 8 * 32, y: 9 * 32 },
  // Kitchen — plant
  { key: "plant", x: 19 * 32, y: 9 * 32 },
  // Aurora's Studio — plants
  { key: "plant", x: 11 * 32, y: 20 * 32 },
  { key: "plant", x: 19 * 32, y: 20 * 32 },
  // Grok's Den — plants
  { key: "plant", x: 22 * 32, y: 20 * 32 },
  { key: "plant", x: 29 * 32, y: 20 * 32 },
];

export class MainScene extends Phaser.Scene {
  private worldManager: WorldManager | null = null;
  private workspaceManager: WorkspaceManager | null = null;
  private furnitureCatalog: FurnitureCatalog | null = null;
  private furnitureInstances: Map<string, FurnitureInstance> = new Map();
  /** Furniture instances grouped by agent workspace (agentId → instances). */
  private workspaceFurniture: Map<string, FurnitureInstance[]> = new Map();
  private autoStateManager: AutoStateManager | null = null;
  private agentSpriteManager: AgentSpriteManager | null = null;
  private speechBubbleManager: SpeechBubbleManager | null = null;
  private streamOverlay: StreamOverlay | null = null;
  private overlayManager: OverlayManager | null = null;
  private devPanel: DevPanel | null = null;
  private audioManager: AudioManager | null = null;
  private behaviorScheduler: BehaviorScheduler | null = null;
  private managementEffects: ManagementEffects | null = null;
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

    // ── Tileset spritesheets + tilemap JSON ─────────────────────────
    // Each room type has its own 128x128 Wang tileset (wall↔floor transitions)
    const tilesetImages: Array<[string, string]> = [
      ["tileset",           "assets/tilesets/office/tileset.png"],
      ["tileset_hardwood",  "assets/tilesets/office/tileset_hardwood.png"],
      ["tileset_whitetile", "assets/tilesets/office/tileset_whitetile.png"],
      ["tileset_teal",      "assets/tilesets/office/tileset_teal.png"],
      ["tileset_purple",    "assets/tilesets/office/tileset_purple.png"],
      ["tileset_bluegrey",  "assets/tilesets/office/tileset_bluegrey.png"],
      ["tileset_concrete",  "assets/tilesets/office/tileset_concrete.png"],
      ["tileset_olive",     "assets/tilesets/office/tileset_olive.png"],
    ];
    for (const [key, path] of tilesetImages) {
      this.load.spritesheet(key, path, {
        frameWidth: TILE_SIZE,
        frameHeight: TILE_SIZE,
      });
    }
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
    for (const item of WALL_TILES) {
      furnitureKeys.add(item.key);
    }
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

    // ── Draw thin interior walls between rooms ───────────────────
    this.drawInteriorWalls();

    // ── Register wall tiles as non-walkable in pathfinding grid ──
    this.registerWallCollision();

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

    // ── Auto-state electronics (monitors on/off with agent activity) ──
    this.autoStateManager = new AutoStateManager(this.workspaceFurniture);
    this.agentSpriteManager.setAutoStateManager(this.autoStateManager);

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

    // ── Management environmental effects (CSS overlay) ──────
    this.managementEffects = new ManagementEffects(this.wsClient);

    // ── Notification overlay (polls, artifacts) ──────────────
    this.overlayManager = new OverlayManager(this.wsClient);

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
    this.overlayManager?.destroy();
    this.overlayManager = null;
    this.devPanel?.destroy();
    this.devPanel = null;
    this.audioManager?.destroy();
    this.audioManager = null;
    this.behaviorScheduler?.destroy();
    this.behaviorScheduler = null;
    this.managementEffects?.destroy();
    this.managementEffects = null;
    this.agentSpriteManager?.destroy();
    this.agentSpriteManager = null;
    this.autoStateManager?.destroy();
    this.autoStateManager = null;
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
   * Draw thin interior walls between rooms using Phaser Graphics.
   * Walls are 6px wide dark lines — much thinner than tile-based walls.
   */
  private drawInteriorWalls(): void {
    const WALL_COLOR = 0x2a2a3a;
    const WALL_WIDTH = 6;
    const T = TILE_SIZE; // 32

    const walls = this.add.graphics();
    walls.setDepth(1); // above floor tiles, below furniture/agents

    walls.fillStyle(WALL_COLOR, 1);

    // Horizontal wall between top row and bottom row — doorway gaps match brick wall
    // Gaps at: cols 5-6 (Vera↔Rex), 15-16 (Kitchen↔Aurora), 25-26 (DevBay↔Grok), 34-35 (DevBay↔Meeting)
    const hGaps = [5, 15, 25, 34]; // gap starts (2 tiles wide each)
    let hx = 0;
    for (const gapStart of hGaps) {
      const segW = gapStart * T - hx;
      if (segW > 0) walls.fillRect(hx, 11 * T - WALL_WIDTH / 2, segW, WALL_WIDTH);
      hx = (gapStart + 2) * T;
    }
    if (hx < 40 * T) walls.fillRect(hx, 11 * T - WALL_WIDTH / 2, 40 * T - hx, WALL_WIDTH);

    // Vertical walls — top row with doorway gaps at rows 4-5
    walls.fillRect(10 * T - WALL_WIDTH / 2, 0, WALL_WIDTH, 4 * T);         // Vera | Kitchen top
    walls.fillRect(10 * T - WALL_WIDTH / 2, 6 * T, WALL_WIDTH, 5 * T);     // Vera | Kitchen bottom
    walls.fillRect(21 * T - WALL_WIDTH / 2, 0, WALL_WIDTH, 4 * T);         // Kitchen | Dev Bay top
    walls.fillRect(21 * T - WALL_WIDTH / 2, 6 * T, WALL_WIDTH, 5 * T);     // Kitchen | Dev Bay bottom

    // Vertical walls — bottom row with doorway gaps at rows 15-16
    walls.fillRect(10 * T - WALL_WIDTH / 2, 11 * T, WALL_WIDTH, 4 * T);    // Rex | Aurora top
    walls.fillRect(10 * T - WALL_WIDTH / 2, 17 * T, WALL_WIDTH, 5 * T);    // Rex | Aurora bottom
    walls.fillRect(21 * T - WALL_WIDTH / 2, 11 * T, WALL_WIDTH, 4 * T);    // Aurora | Grok top
    walls.fillRect(21 * T - WALL_WIDTH / 2, 17 * T, WALL_WIDTH, 5 * T);    // Aurora | Grok bottom
    walls.fillRect(31 * T - WALL_WIDTH / 2, 11 * T, WALL_WIDTH, 2 * T);    // Grok | Meeting top
    walls.fillRect(31 * T - WALL_WIDTH / 2, 15 * T, WALL_WIDTH, 2 * T);    // Grok | Meeting bottom
    walls.fillRect(31 * T - WALL_WIDTH / 2, 19 * T, WALL_WIDTH, 3 * T);    // Alpha right wall

    // Horizontal wall between Meeting and Alpha — with doorway gap at cols 34-35
    walls.fillRect(31 * T, 17 * T - WALL_WIDTH / 2, 3 * T, WALL_WIDTH);
    walls.fillRect(36 * T, 17 * T - WALL_WIDTH / 2, 4 * T, WALL_WIDTH);
  }

  /**
   * Register all interior wall positions as non-walkable in the pathfinding grid.
   * The tilemap collision layer only covers exterior walls; interior walls
   * (brick rows, side columns) are visual-only sprites that need explicit blocking.
   */
  private registerWallCollision(): void {
    if (!this.worldManager) return;
    const T = TILE_SIZE;

    // Block all WALL_TILES positions (brick wall rows 0, 11, 17 + side wall columns)
    for (const item of WALL_TILES) {
      const tx = Math.floor(item.x / T);
      const ty = Math.floor(item.y / T);
      this.worldManager.markTilesBlocked([{ tx, ty }]);
    }

    // Block interior vertical wall columns between rooms (the Graphics walls).
    // These are drawn as thin lines but occupy the tile column they're on.
    // Top rooms: vertical walls at cols 10, 21 (rows 1-10), doorway gap at rows 4-5
    for (const col of [10, 21]) {
      for (let row = 1; row <= 10; row++) {
        if (row === 4 || row === 5) continue; // doorway
        this.worldManager.markTilesBlocked([{ tx: col, ty: row }]);
      }
    }
    // Bottom rooms: vertical walls at cols 10, 21 (rows 12-20), doorway gap at rows 15-16
    for (const col of [10, 21]) {
      for (let row = 12; row <= 20; row++) {
        if (row === 15 || row === 16) continue; // doorway
        this.worldManager.markTilesBlocked([{ tx: col, ty: row }]);
      }
    }
    // Col 31: Grok|Meeting (rows 12-16, doorway rows 13-14) + Alpha (rows 18-20)
    for (let row = 12; row <= 20; row++) {
      if (row === 13 || row === 14) continue; // Meeting doorway
      if (row === 17) continue; // horizontal wall row (already blocked by WALL_TILES if present)
      this.worldManager.markTilesBlocked([{ tx: 31, ty: row }]);
    }
  }

  /**
   * Place furniture objects as sprites on top of the tile layer.
   * Creates FurnitureInstance objects for manifest-backed items (enabling state changes),
   * and falls back to raw sprites for shared furniture without manifests.
   */
  private placeFurniture(): void {
    // Draw solid background strips behind wall tiles to eliminate sub-pixel gaps.
    const wallBg = this.add.graphics();
    wallBg.setDepth(0.5); // above floor, below wall tiles
    wallBg.fillStyle(0x733c26, 1); // matches average brick tile color
    const T = TILE_SIZE;

    // ── Horizontal wall backgrounds ──
    // Row 0: continuous exterior wall
    wallBg.fillRect(1 * T, 0, 38 * T, T);
    // Row 11: interior wall with doorway gaps at cols 5-6, 15-16, 25-26, 34-35
    wallBg.fillRect(1 * T, 11 * T, 4 * T, T);    // cols 1-4
    wallBg.fillRect(7 * T, 11 * T, 8 * T, T);    // cols 7-14
    wallBg.fillRect(17 * T, 11 * T, 8 * T, T);   // cols 17-24
    wallBg.fillRect(27 * T, 11 * T, 7 * T, T);   // cols 27-33
    wallBg.fillRect(36 * T, 11 * T, 3 * T, T);   // cols 36-38
    // Row 17: Alpha wall with doorway gap at cols 34-35
    wallBg.fillRect(32 * T, 17 * T, 2 * T, T);   // cols 32-33
    wallBg.fillRect(36 * T, 17 * T, 3 * T, T);   // cols 36-38

    // ── Vertical side wall backgrounds (6px wide strips, split at doorways) ──
    const STRIP = 6;
    // Top rooms (rows 1-10), doorway gap at rows 4-5 on interior walls
    wallBg.fillRect(0, 1 * T, STRIP, 10 * T);                           // col 0 left (no doorway)
    wallBg.fillRect(10 * T - STRIP, 1 * T, STRIP, 3 * T);              // col 9 right top (rows 1-3)
    wallBg.fillRect(10 * T - STRIP, 6 * T, STRIP, 5 * T);              // col 9 right bottom (rows 6-10)
    wallBg.fillRect(10 * T, 1 * T, STRIP, 3 * T);                       // col 10 left top
    wallBg.fillRect(10 * T, 6 * T, STRIP, 5 * T);                       // col 10 left bottom
    wallBg.fillRect(21 * T - STRIP, 1 * T, STRIP, 3 * T);              // col 20 right top
    wallBg.fillRect(21 * T - STRIP, 6 * T, STRIP, 5 * T);              // col 20 right bottom
    wallBg.fillRect(21 * T, 1 * T, STRIP, 3 * T);                       // col 21 left top
    wallBg.fillRect(21 * T, 6 * T, STRIP, 5 * T);                       // col 21 left bottom
    wallBg.fillRect(40 * T - STRIP, 1 * T, STRIP, 10 * T);             // col 39 right (no doorway)
    // Bottom rooms (rows 12-20), doorway gap at rows 15-16 on most walls
    wallBg.fillRect(0, 12 * T, STRIP, 3 * T);                           // col 0 left top (rows 12-14)
    wallBg.fillRect(0, 17 * T, STRIP, 4 * T);                           // col 0 left bottom (rows 17-20)
    wallBg.fillRect(10 * T - STRIP, 12 * T, STRIP, 3 * T);             // col 9 right top
    wallBg.fillRect(10 * T - STRIP, 17 * T, STRIP, 4 * T);             // col 9 right bottom
    wallBg.fillRect(10 * T, 12 * T, STRIP, 3 * T);                      // col 10 left top
    wallBg.fillRect(10 * T, 17 * T, STRIP, 4 * T);                      // col 10 left bottom
    wallBg.fillRect(21 * T - STRIP, 12 * T, STRIP, 3 * T);             // col 20 right top
    wallBg.fillRect(21 * T - STRIP, 17 * T, STRIP, 4 * T);             // col 20 right bottom
    wallBg.fillRect(21 * T, 12 * T, STRIP, 3 * T);                      // col 21 left top
    wallBg.fillRect(21 * T, 17 * T, STRIP, 4 * T);                      // col 21 left bottom
    wallBg.fillRect(31 * T - STRIP, 12 * T, STRIP, 3 * T);             // col 30 right top
    wallBg.fillRect(31 * T - STRIP, 17 * T, STRIP, 4 * T);             // col 30 right bottom
    wallBg.fillRect(31 * T, 12 * T, STRIP, 1 * T);                      // col 31 left (row 12)
    wallBg.fillRect(31 * T, 15 * T, STRIP, 2 * T);                      // col 31 left (rows 15-16)
    wallBg.fillRect(31 * T, 19 * T, STRIP, 2 * T);                      // col 31 left (rows 19-20)
    wallBg.fillRect(40 * T - STRIP, 12 * T, STRIP, 1 * T);             // col 39 right (row 12)
    wallBg.fillRect(40 * T - STRIP, 15 * T, STRIP, 2 * T);             // col 39 right (rows 15-16)
    wallBg.fillRect(40 * T - STRIP, 18 * T, STRIP, 3 * T);             // col 39 right (rows 18-20)

    // Place wall-face tiles (grid-snapped, north wall row of each room)
    for (const item of WALL_TILES) {
      if (this.textures.exists(item.key)) {
        const sprite = this.add.image(item.x, item.y, item.key);
        sprite.setOrigin(0, 0);
        sprite.setDepth(1);
      }
    }

    // Place shared furniture
    for (const item of SHARED_FURNITURE) {
      const manifest = this.furnitureCatalog?.getManifest(item.key.toUpperCase());
      if (manifest && this.textures.exists(this.getFurnitureTextureKey(manifest))) {
        const instanceKey = `shared_${item.key}_${item.x}_${item.y}`;
        const instance = new FurnitureInstance(this, manifest, item.x, item.y);
        this.furnitureInstances.set(instanceKey, instance);
        // Register floor-level furniture as non-walkable
        if (!manifest.canPlaceOnSurfaces && this.worldManager) {
          this.worldManager.registerFurnitureCollision(
            item.x, item.y, manifest.footprint[0], manifest.footprint[1],
          );
        }
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
            // Register floor-level furniture as non-walkable
            if (!manifest.canPlaceOnSurfaces && this.worldManager) {
              this.worldManager.registerFurnitureCollision(
                item.x, item.y, manifest.footprint[0], manifest.footprint[1],
              );
            }
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

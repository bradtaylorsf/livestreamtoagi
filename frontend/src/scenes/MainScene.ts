import Phaser from "phaser";
import { WorldManager } from "../world/WorldManager";
import { AgentSpriteManager } from "../agents/AgentSpriteManager";
import type { WebSocketClient } from "../network/WebSocketClient";
import { AGENTS } from "../agents";

/** Office grid dimensions in tiles. */
const GRID_W = 50;
const GRID_H = 34;
const TILE_SIZE = 32;

/** Agents that have sprite assets (excludes overseer). */
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

const FURNITURE: FurniturePlacement[] = [
  // Desks for top-row agents
  { key: "desk", x: 6 * 32, y: 5 * 32 },    // Vera
  { key: "desk", x: 14 * 32, y: 5 * 32 },   // Aurora
  { key: "desk", x: 22 * 32, y: 5 * 32 },   // Fork
  { key: "desk", x: 36 * 32, y: 5 * 32 },   // Sentinel
  { key: "desk", x: 44 * 32, y: 5 * 32 },   // Grok
  // Desks for bottom-row agents
  { key: "desk", x: 6 * 32, y: 27 * 32 },   // Rex
  { key: "desk", x: 14 * 32, y: 27 * 32 },  // Pixel
  // Meeting area
  { key: "meeting_table", x: 25 * 32, y: 14 * 32 },
  // Workshop
  { key: "workshop_bench", x: 25 * 32, y: 22 * 32 },
  // Whiteboard
  { key: "whiteboard", x: 35 * 32, y: 29 * 32 },
  // Coffee machine
  { key: "coffee_machine", x: 28 * 32, y: 4 * 32 },
  // Bookshelf
  { key: "bookshelf", x: 20 * 32, y: 29 * 32 },
  // Plants
  { key: "plant", x: 42 * 32, y: 29 * 32 },
  { key: "plant", x: 43 * 32, y: 29 * 32 },
  // Chairs (near desks, one per agent desk)
  { key: "chair", x: 6 * 32, y: 7 * 32 },
  { key: "chair", x: 14 * 32, y: 7 * 32 },
  { key: "chair", x: 22 * 32, y: 7 * 32 },
  { key: "chair", x: 36 * 32, y: 7 * 32 },
  { key: "chair", x: 44 * 32, y: 7 * 32 },
  { key: "chair", x: 6 * 32, y: 26 * 32 },
  { key: "chair", x: 14 * 32, y: 26 * 32 },
  // Rug in meeting area
  { key: "rug", x: 24 * 32, y: 13 * 32 },
];

export class MainScene extends Phaser.Scene {
  private worldManager: WorldManager | null = null;
  private agentSpriteManager: AgentSpriteManager | null = null;
  private wsClient: WebSocketClient | null = null;

  constructor() {
    super({ key: "MainScene" });
  }

  setWebSocketClient(client: WebSocketClient): void {
    this.wsClient = client;
  }

  preload(): void {
    // ── Tileset spritesheet ─────────────────────────────────────
    this.load.spritesheet("office_tiles", "assets/tilesets/office/tileset.png", {
      frameWidth: TILE_SIZE,
      frameHeight: TILE_SIZE,
    });

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

    // ── Generate and cache the tilemap JSON ─────────────────────
    this.generateTilemapJSON();
  }

  create(): void {
    this.cameras.main.setBackgroundColor("#1a1a2e");

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
  }

  getWorldManager(): WorldManager | null {
    return this.worldManager;
  }

  getAgentSpriteManager(): AgentSpriteManager | null {
    return this.agentSpriteManager;
  }

  update(): void {
    // Game loop logic will be added as features are implemented.
  }

  /**
   * Build a Phaser-compatible tilemap JSON and inject it into the
   * tilemap cache so ChunkLoader can load it via `tilemap_office`.
   */
  private generateTilemapJSON(): void {
    // Wang tile index 13 = first tile in spritesheet (index 0 in spritesheet)
    // We need to map from Wang IDs to spritesheet positions.
    // The spritesheet is a 4x4 grid. The metadata lists tiles in order:
    //   Row 0: wang_13, wang_10, wang_4, wang_12
    //   Row 1: wang_6,  wang_8,  wang_0, wang_1
    //   Row 2: wang_11, wang_3,  wang_2, wang_5
    //   Row 3: wang_15, wang_14, wang_9, wang_7
    // Phaser spritesheet index = row*4 + col
    // So wang_15 (full floor) is at spritesheet index 12 (row 3, col 0)
    // And wang_0 (full wall) is at spritesheet index 6 (row 1, col 2)

    const FLOOR_TILE = 13; // spritesheet index 12 + firstgid 1 = 13
    const WALL_TILE = 7;   // spritesheet index 6 + firstgid 1 = 7

    const groundData: number[] = [];
    const wallData: number[] = [];

    for (let row = 0; row < GRID_H; row++) {
      for (let col = 0; col < GRID_W; col++) {
        const isPerimeter =
          row === 0 || row === GRID_H - 1 || col === 0 || col === GRID_W - 1;

        // Ground layer: floor everywhere inside, 0 on perimeter
        groundData.push(isPerimeter ? WALL_TILE : FLOOR_TILE);

        // Collision layer: 1 on walls, 0 inside
        wallData.push(isPerimeter ? 1 : 0);
      }
    }

    // Areas from the layout (tile coordinates -> pixel coordinates)
    const areas: Record<string, { x: number; y: number; width: number; height: number }> = {
      desk_vera:     { x: 3 * TILE_SIZE, y: 3 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      desk_aurora:   { x: 11 * TILE_SIZE, y: 3 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      desk_fork:     { x: 19 * TILE_SIZE, y: 3 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      desk_sentinel: { x: 33 * TILE_SIZE, y: 3 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      desk_grok:     { x: 41 * TILE_SIZE, y: 3 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      desk_rex:      { x: 3 * TILE_SIZE, y: 25 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      desk_pixel:    { x: 11 * TILE_SIZE, y: 25 * TILE_SIZE, width: 6 * TILE_SIZE, height: 6 * TILE_SIZE },
      meeting_area:  { x: 20 * TILE_SIZE, y: 12 * TILE_SIZE, width: 10 * TILE_SIZE, height: 6 * TILE_SIZE },
      workshop:      { x: 20 * TILE_SIZE, y: 20 * TILE_SIZE, width: 10 * TILE_SIZE, height: 6 * TILE_SIZE },
    };

    const tilemapJSON = {
      width: GRID_W,
      height: GRID_H,
      tilewidth: TILE_SIZE,
      tileheight: TILE_SIZE,
      tilesets: [{ name: "office_tiles", firstgid: 1 }],
      layers: [
        { name: "ground", data: groundData },
        { name: "collision", data: wallData },
      ],
      areas,
    };

    // Inject into Phaser tilemap cache so ChunkLoader can find "tilemap_office"
    this.cache.tilemap.add("tilemap_office", {
      format: Phaser.Tilemaps.Formats.TILED_JSON,
      data: tilemapJSON,
    });
  }

  /**
   * Register Phaser animations for each agent from loaded frame images.
   */
  private registerAnimations(): void {
    for (const agentId of SPRITE_AGENT_IDS) {
      // Idle animation (south-facing, used as default)
      this.anims.create({
        key: `${agentId}_idle`,
        frames: this.buildFrameKeys(agentId, "idle", "south", IDLE_FRAME_COUNT),
        frameRate: 4,
        repeat: -1,
      });

      // Walking animations mapped to directional names
      const walkMapping: Record<string, string> = {
        walk_down: "south",
        walk_up: "north",
        walk_right: "east",
        walk_left: "west",
      };

      for (const [animName, direction] of Object.entries(walkMapping)) {
        this.anims.create({
          key: `${agentId}_${animName}`,
          frames: this.buildFrameKeys(agentId, "walk", direction, WALK_FRAME_COUNT),
          frameRate: 8,
          repeat: -1,
        });
      }

      // Talking = idle south-east (reuse idle frames with different direction)
      this.anims.create({
        key: `${agentId}_talking`,
        frames: this.buildFrameKeys(agentId, "idle", "south-east", IDLE_FRAME_COUNT),
        frameRate: 6,
        repeat: -1,
      });

      // Thinking = idle north (looking up)
      this.anims.create({
        key: `${agentId}_thinking`,
        frames: this.buildFrameKeys(agentId, "idle", "north", IDLE_FRAME_COUNT),
        frameRate: 3,
        repeat: -1,
      });

      // Building = idle east (focused sideways)
      this.anims.create({
        key: `${agentId}_building`,
        frames: this.buildFrameKeys(agentId, "idle", "east", IDLE_FRAME_COUNT),
        frameRate: 5,
        repeat: -1,
      });
    }
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

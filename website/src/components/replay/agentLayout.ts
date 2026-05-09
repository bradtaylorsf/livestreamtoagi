/**
 * Static desk positions and helpers for the replay scene.
 *
 * Ported from frontend/src/world/workspaces.ts and the workspace_* areas
 * embedded in frontend/assets/tilesets/office/tilemap_office.json.
 *
 * The full WorkspaceManager + pathfinding stack from the live frontend is
 * intentionally NOT pulled in — the replay only needs static lookups and a
 * tiny bit of jitter for visual variety. Bundle stays small.
 */

export interface DeskPosition {
  /** Pixel x in tilemap coordinates (0–1280). */
  x: number;
  /** Pixel y in tilemap coordinates (0–704). */
  y: number;
  /**
   * Default facing direction. Used to pick the right idle/walk animation
   * if the agent never speaks (so they aren't all facing south).
   */
  facing: "south" | "north" | "east" | "west";
}

const STAGE_W = 1280;
const STAGE_H = 720;
const SPRITE_HALF = 24;
const BUBBLE_PAD = 8;

/**
 * Per-agent desk anchor. Coordinates point at where the agent sprite sits;
 * roughly the centre of each workspace area in the tilemap.
 *
 * Tilemap ground is 1280×704 (40×22 tiles at 32px). The replay canvas is
 * 1280×720, so positions y=0..704 are visible with 16px of black at the
 * bottom — same letterbox the live show uses.
 */
const DESK_POSITIONS: Record<string, DeskPosition> = {
  // Top row — north-facing rooms
  vera:     { x: 160, y: 176, facing: "south" }, // workspace_vera     (32,32 256x288)
  sentinel: { x: 816, y: 176, facing: "south" }, // workspace_sentinel (736,64 160x224)
  fork:     { x: 1008, y: 176, facing: "south" }, // workspace_fork    (928,64 160x224)
  pixel:    { x: 1152, y: 176, facing: "south" }, // workspace_pixel   (1088,64 128x224)
  // Bottom row — south-facing rooms
  rex:      { x: 160, y: 528, facing: "north" }, // workspace_rex     (32,384 256x288)
  aurora:   { x: 496, y: 528, facing: "north" }, // workspace_aurora  (352,384 288x288)
  grok:     { x: 832, y: 528, facing: "north" }, // workspace_grok    (704,384 256x288)
  // Bottom right — meeting / management / alpha
  alpha:    { x: 1136, y: 608, facing: "north" }, // workspace_alpha  (1056,576 160x64)
  management: { x: 1136, y: 608, facing: "south" }, // overlaps alpha — visible in meeting area
};

/** Fallback used when an unknown agent_id appears in cues. */
const FALLBACK: DeskPosition = { x: 1136, y: 448, facing: "north" }; // meeting area

export function getKnownAgents(): string[] {
  return Object.keys(DESK_POSITIONS);
}

export function hasAgentLayout(agentId: string): boolean {
  return Object.prototype.hasOwnProperty.call(DESK_POSITIONS, agentId);
}

export function getDeskPosition(agentId: string): DeskPosition {
  return DESK_POSITIONS[agentId] ?? FALLBACK;
}

/**
 * Slight per-cue offset so multiple speakers in the same room don't sit on
 * top of each other. Deterministic given (agentId, cueIndex) — this matters
 * for diff-stable Playwright snapshots.
 */
export function getSpeakingPosition(
  agentId: string,
  cueIndex: number,
): { x: number; y: number; facing: DeskPosition["facing"] } {
  const desk = getDeskPosition(agentId);
  // Tiny radial jitter (-12..+12 px) keyed on cueIndex.
  const jitterX = ((cueIndex * 17) % 25) - 12;
  const jitterY = ((cueIndex * 31) % 25) - 12;
  return {
    x: clampX(desk.x + jitterX),
    y: clampY(desk.y + jitterY),
    facing: desk.facing,
  };
}

/**
 * Clamp a bubble position so the entire bubble stays inside the 1280×720
 * viewport. ``bubbleW``/``bubbleH`` are the rendered bubble dimensions.
 *
 * Anchor convention: the returned (x, y) is the top-left of the bubble.
 */
export function clampBubblePosition(
  speakerX: number,
  speakerY: number,
  bubbleW: number,
  bubbleH: number,
): { x: number; y: number } {
  // Centre the bubble horizontally above the speaker.
  let x = speakerX - bubbleW / 2;
  // Bubble sits above sprite head — sprite is 48 tall, anchor at centre.
  let y = speakerY - SPRITE_HALF - bubbleH - BUBBLE_PAD;

  // Clamp horizontally
  if (x < BUBBLE_PAD) x = BUBBLE_PAD;
  if (x + bubbleW > STAGE_W - BUBBLE_PAD) x = STAGE_W - BUBBLE_PAD - bubbleW;
  // Clamp vertically — if the bubble would clip off the top, place below.
  if (y < BUBBLE_PAD) {
    y = speakerY + SPRITE_HALF + BUBBLE_PAD;
  }
  if (y + bubbleH > STAGE_H - BUBBLE_PAD) {
    y = STAGE_H - BUBBLE_PAD - bubbleH;
  }
  return { x, y };
}

function clampX(x: number): number {
  return Math.max(SPRITE_HALF, Math.min(STAGE_W - SPRITE_HALF, x));
}
function clampY(y: number): number {
  return Math.max(SPRITE_HALF, Math.min(STAGE_H - SPRITE_HALF, y));
}

export const __LAYOUT_INTERNALS = { STAGE_W, STAGE_H, SPRITE_HALF, BUBBLE_PAD };

import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

const STAGE_SOURCE = readFileSync(
  resolve(__dirname, "../ReplayStage.tsx"),
  "utf8",
);
const SCENE_SOURCE = readFileSync(
  resolve(__dirname, "../OfficeReplayScene.ts"),
  "utf8",
);
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../../../app/simulations/[id]/replay/page.tsx"),
  "utf8",
);
const LAYOUT_SOURCE = readFileSync(
  resolve(__dirname, "../../../app/simulations/[id]/replay/layout.tsx"),
  "utf8",
);

describe("ReplayStage wiring", () => {
  it("uses the OfficeReplayScene (not the placeholder rectangle scene)", () => {
    expect(STAGE_SOURCE).toMatch(/OfficeReplayScene/);
    expect(STAGE_SOURCE).not.toMatch(/buildSlots\b/);
  });

  it("flips __replayReady and __replayDone via scene callbacks", () => {
    expect(STAGE_SOURCE).toMatch(/__replayReady/);
    expect(STAGE_SOURCE).toMatch(/__replayDone/);
  });

  it("clears stale replay debug state before mounting a new scene", () => {
    expect(STAGE_SOURCE).toMatch(/delete w\.__replayDebug/);
  });

  it("uses 1280x720 stage dimensions", () => {
    expect(STAGE_SOURCE).toMatch(/STAGE_W\s*=\s*1280/);
    expect(STAGE_SOURCE).toMatch(/STAGE_H\s*=\s*720/);
  });

  it("renderMode hides chrome via fixed/inset:0/zIndex:9999", () => {
    expect(STAGE_SOURCE).toMatch(/position:\s*"fixed"/);
    expect(STAGE_SOURCE).toMatch(/zIndex:\s*9999/);
  });
});

describe("OfficeReplayScene assets", () => {
  it("loads the office tilemap from public/replay-assets", () => {
    expect(SCENE_SOURCE).toMatch(/ASSET_BASE\s*=\s*"\/replay-assets"/);
    expect(SCENE_SOURCE).toMatch(/tilesets\/office\/tilemap_office\.json/);
  });

  it("loads all 8 tileset images that the tilemap references", () => {
    for (const key of [
      "tileset",
      "tileset_hardwood",
      "tileset_whitetile",
      "tileset_teal",
      "tileset_purple",
      "tileset_bluegrey",
      "tileset_concrete",
      "tileset_olive",
    ]) {
      expect(SCENE_SOURCE).toContain(`"${key}"`);
    }
  });

  it("registers each tileset by its Tiled name (not just the image key)", () => {
    // Phaser's addTilesetImage requires the JSON tileset name AND the image
    // key. Mismatching them silently produces a blank canvas.
    for (const tilesetName of [
      "office_tiles",
      "office_tiles_hardwood",
      "office_tiles_whitetile",
      "office_tiles_teal",
      "office_tiles_purple",
      "office_tiles_bluegrey",
      "office_tiles_concrete",
      "office_tiles_olive",
    ]) {
      expect(SCENE_SOURCE).toContain(`"${tilesetName}"`);
    }
  });

  it("loads cardinal-direction sprite frames per agent", () => {
    expect(SCENE_SOURCE).toMatch(/breathing-idle/);
    expect(SCENE_SOURCE).toMatch(/walking/);
  });

  it("creates idle/walk animations and tweens between desk and speaking position", () => {
    expect(SCENE_SOURCE).toMatch(/this\.tweens\.add/);
    expect(SCENE_SOURCE).toMatch(/getSpeakingPosition/);
  });

  it("exposes tilemap and sprite evidence through the replay debug hook", () => {
    expect(SCENE_SOURCE).toMatch(/OfficeReplayDebugState/);
    expect(SCENE_SOURCE).toMatch(/__replayDebug/);
    expect(SCENE_SOURCE).toMatch(/fallbackFloorUsed/);
    expect(SCENE_SOURCE).toMatch(/renderedLayerCount/);
    expect(SCENE_SOURCE).toMatch(/renderedLayerNames/);
    expect(SCENE_SOURCE).toMatch(/tilesetCount/);
    expect(SCENE_SOURCE).toMatch(/usedFallbackRectangle/);
    expect(SCENE_SOURCE).toMatch(/textureKey/);
  });

  it("updates replay debug metadata when a speech bubble renders", () => {
    expect(SCENE_SOURCE).toMatch(/latestBubble/);
    expect(SCENE_SOURCE).toMatch(/hadBubble/);
    expect(SCENE_SOURCE).toMatch(/agentId/);
    expect(SCENE_SOURCE).toMatch(/startMs/);
    expect(SCENE_SOURCE).toMatch(/endMs/);
  });
});

describe("replay route wiring", () => {
  it("page dynamically imports ReplayStage with ssr:false", () => {
    expect(PAGE_SOURCE).toMatch(/ssr:\s*false/);
    expect(PAGE_SOURCE).toMatch(/ReplayStage/);
  });

  it("page reads renderMode=1 from search params", () => {
    expect(PAGE_SOURCE).toMatch(/renderMode/);
    expect(PAGE_SOURCE).toMatch(/getReplayCues/);
  });

  it("page passes the backend replay roster into ReplayStage", () => {
    expect(PAGE_SOURCE).toMatch(/agent_roster/);
    expect(PAGE_SOURCE).toMatch(/agentRoster/);
    expect(STAGE_SOURCE).toMatch(/agentRoster/);
  });

  it("renderMode cue-load failures expose __replayError without empty-stage fallback", () => {
    expect(PAGE_SOURCE).toMatch(/__replayError/);
    expect(PAGE_SOURCE).toMatch(/data-testid="replay-error"/);
    expect(PAGE_SOURCE).not.toMatch(/setCues\(\[\]\)/);
  });

  it("layout marks the page non-indexable", () => {
    expect(LAYOUT_SOURCE).toMatch(/robots/);
    expect(LAYOUT_SOURCE).toMatch(/index:\s*false/);
  });
});

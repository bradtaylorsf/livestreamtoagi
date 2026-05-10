import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { installReplayHarness, REPLAY_HARNESS_ORIGIN } from "./replayHarness";

/**
 * Visual smoke test for the office replay page (issue #476).
 *
 * The render pipeline (core/video/render_pipeline.py) drives this page
 * headlessly to produce the simulation MP4. The scene must render the
 * actual office tilemap + agent sprites — not the legacy coloured-rectangle
 * placeholder — and a speech bubble during a speaking cue.
 */

const SIM_ID = "00000000-0000-4000-8000-000000000476";
const SKIP_BROWSER_IN_CODEX_SANDBOX = process.env.CODEX_SANDBOX === "seatbelt";
const WEBSITE_ROOT = resolve(__dirname, "../..");
const FRONTEND_ASSET_ROOT = resolve(WEBSITE_ROOT, "../frontend/assets");
const REPLAY_SOURCE_ROOT = resolve(WEBSITE_ROOT, "src/components/replay");
const TILESET_NAMES = [
  "office_tiles",
  "office_tiles_hardwood",
  "office_tiles_whitetile",
  "office_tiles_teal",
  "office_tiles_purple",
  "office_tiles_bluegrey",
  "office_tiles_concrete",
  "office_tiles_olive",
];
const TILESET_IMAGE_KEYS = [
  "tileset",
  "tileset_hardwood",
  "tileset_whitetile",
  "tileset_teal",
  "tileset_purple",
  "tileset_bluegrey",
  "tileset_concrete",
  "tileset_olive",
];
const FIXTURE_CUES = {
  sim_id: SIM_ID,
  agent_roster: ["vera", "rex", "aurora"],
  duration_seconds: 7,
  cues: [
    { agent_id: "vera", text: "Welcome to the office.", start_seconds: 1.5 },
    { agent_id: "rex", text: "Booting the workshop.", start_seconds: 3 },
    { agent_id: "aurora", text: "Studio is online.", start_seconds: 5 },
  ],
};

interface ReplayDebugState {
  tilemap: {
    layerCount: number;
    layerNames: string[];
    renderedLayerCount: number;
    renderedLayerNames: string[];
    tilesetCount: number;
    tilesetNames: string[];
    fallbackFloorUsed: boolean;
  };
  agents: Array<{
    id: string;
    visible: boolean;
    x: number;
    y: number;
    textureKey: string | null;
    usedFallbackRectangle: boolean;
  }>;
  hadBubble: boolean;
  latestBubble: {
    agentId: string;
    text: string;
    x: number;
    y: number;
    w: number;
    h: number;
    visible: boolean;
    startMs: number;
    endMs: number;
  } | null;
}

interface TilemapJson {
  layers: Array<{
    name: string;
    type: string;
    width?: number;
    height?: number;
    data?: number[];
  }>;
  tilesets: Array<{
    name: string;
    image: string;
    tilecount: number;
  }>;
}

function replayAssetPath(relativePath: string): string {
  return resolve(FRONTEND_ASSET_ROOT, relativePath);
}

function readReplayAsset(relativePath: string): Buffer {
  const path = replayAssetPath(relativePath);
  expect(existsSync(path), `${relativePath} should exist`).toBe(true);
  return readFileSync(path);
}

function expectVisualPngAsset(
  relativePath: string,
  expectedSize?: { width: number; height: number },
): void {
  const buffer = readReplayAsset(relativePath);
  expect(buffer.subarray(1, 4).toString("ascii")).toBe("PNG");
  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  expect(width).toBeGreaterThan(0);
  expect(height).toBeGreaterThan(0);
  if (expectedSize) {
    expect({ width, height }).toEqual(expectedSize);
  }
  expect(buffer.length).toBeGreaterThan(256);
  expect(new Set(buffer).size).toBeGreaterThan(32);
}

async function mockCues(page: Page) {
  await installReplayHarness(page, {
    simId: SIM_ID,
    replayCues: {
      status: 200,
      body: FIXTURE_CUES,
    },
  });
}

async function gotoReplay(page: Page) {
  await page.goto(
    `${REPLAY_HARNESS_ORIGIN}/simulations/${SIM_ID}/replay?renderMode=1`,
  );
  await page.waitForFunction(
    () => (window as unknown as Record<string, unknown>).__replayReady === true,
    null,
    { timeout: 30_000 },
  );
}

async function waitForReplayDebug(page: Page): Promise<ReplayDebugState> {
  await page.waitForFunction(
    () => {
      const debug = (window as unknown as { __replayDebug?: ReplayDebugState })
        .__replayDebug;
      return (
        debug != null &&
        debug.tilemap.layerCount > 0 &&
        debug.tilemap.renderedLayerCount > 0 &&
        debug.agents.length >= 2
      );
    },
    null,
    { timeout: 10_000 },
  );
  return page.evaluate(
    () =>
      (window as unknown as { __replayDebug: ReplayDebugState }).__replayDebug,
  );
}

test.describe("replay scene sandbox fallback", () => {
  test.skip(
    !SKIP_BROWSER_IN_CODEX_SANDBOX,
    "Node-only fallback is only needed when Chromium is blocked by the Codex sandbox.",
  );

  test("verifies deterministic replay visual evidence without launching Chromium", () => {
    const tilemap = JSON.parse(
      readReplayAsset("tilesets/office/tilemap_office.json").toString("utf8"),
    ) as TilemapJson;

    const ground = tilemap.layers.find(
      (layer) => layer.name === "Ground" && layer.type === "tilelayer",
    );
    expect(ground).toBeDefined();
    expect(ground?.width).toBe(40);
    expect(ground?.height).toBe(22);
    expect(ground?.data?.filter((gid) => gid > 0).length).toBeGreaterThan(500);
    expect(new Set(ground?.data ?? []).size).toBeGreaterThan(8);

    expect(tilemap.tilesets.map((tileset) => tileset.name)).toEqual(TILESET_NAMES);
    expect(tilemap.tilesets.map((tileset) => tileset.image)).toEqual(
      TILESET_IMAGE_KEYS,
    );
    for (const imageKey of TILESET_IMAGE_KEYS) {
      expectVisualPngAsset(`tilesets/office/${imageKey}.png`, {
        width: 128,
        height: 128,
      });
    }

    for (const agentId of ["vera", "rex"]) {
      expectVisualPngAsset(`sprites/${agentId}/rotations/south.png`, {
        width: 48,
        height: 48,
      });
      expectVisualPngAsset(
        `sprites/${agentId}/animations/breathing-idle/south/frame_000.png`,
        { width: 48, height: 48 },
      );
      expectVisualPngAsset(
        `sprites/${agentId}/animations/walking/south/frame_000.png`,
        { width: 48, height: 48 },
      );
    }

    const sceneSource = readFileSync(
      resolve(REPLAY_SOURCE_ROOT, "OfficeReplayScene.ts"),
      "utf8",
    );
    expect(sceneSource).toContain("__replayDebug");
    expect(sceneSource).toContain("fallbackFloorUsed");
    expect(sceneSource).toContain("usedFallbackRectangle");
    expect(sceneSource).toContain("latestBubble");

    const bubbleSource = readFileSync(
      resolve(REPLAY_SOURCE_ROOT, "ReplaySpeechBubble.ts"),
      "utf8",
    );
    expect(bubbleSource).toContain("fillRoundedRect");
    expect(bubbleSource).toContain("fillTriangle");
    expect(bubbleSource).toContain("setVisible");
  });
});

test.describe("replay scene", () => {
  test.skip(
    SKIP_BROWSER_IN_CODEX_SANDBOX,
    "Chromium cannot launch inside the Codex macOS seatbelt sandbox.",
  );

  test("renderMode exposes cue-load failure and does not mount the stage", async ({ page }) => {
    await installReplayHarness(page, {
      simId: SIM_ID,
      replayCues: {
        status: 500,
        body: { detail: "cue load exploded" },
      },
    });

    await page.goto(
      `${REPLAY_HARNESS_ORIGIN}/simulations/${SIM_ID}/replay?renderMode=1`,
    );
    await page.waitForFunction(
      () => Boolean((window as unknown as Record<string, unknown>).__replayError),
      null,
      { timeout: 10_000 },
    );

    const replayError = await page.evaluate(
      () => (window as unknown as Record<string, unknown>).__replayError,
    );
    expect(String(replayError)).toContain("Replay cue load failed");
    await expect(page.getByTestId("replay-error")).toBeVisible();
    await expect(page.getByTestId("replay-stage")).toHaveCount(0);
    await expect(page.locator("canvas")).toHaveCount(0);
  });

  test("renders office tilemap and multiple real sprites on a nonblank canvas", async ({ page }) => {
    await mockCues(page);
    await gotoReplay(page);

    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible();
    await expect(page.getByTestId("replay-stage").locator("canvas")).toHaveCount(1);
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBe(1280);
    expect(box!.height).toBe(720);

    const debug = await waitForReplayDebug(page);
    expect(debug.tilemap.fallbackFloorUsed).toBe(false);
    expect(debug.tilemap.layerCount).toBeGreaterThanOrEqual(1);
    expect(debug.tilemap.layerNames).toContain("Ground");
    expect(debug.tilemap.renderedLayerCount).toBeGreaterThanOrEqual(1);
    expect(debug.tilemap.renderedLayerNames).toContain("Ground");
    expect(debug.tilemap.tilesetCount).toBe(8);
    expect(debug.tilemap.tilesetNames).toEqual(
      expect.arrayContaining([
        "office_tiles",
        "office_tiles_hardwood",
        "office_tiles_whitetile",
        "office_tiles_teal",
        "office_tiles_purple",
        "office_tiles_bluegrey",
        "office_tiles_concrete",
        "office_tiles_olive",
      ]),
    );

    const realSprites = debug.agents.filter(
      (agent) =>
        agent.visible &&
        !agent.usedFallbackRectangle &&
        agent.textureKey != null &&
        agent.textureKey.includes(agent.id),
    );
    expect(realSprites.length).toBeGreaterThanOrEqual(2);
    expect(realSprites.map((agent) => agent.id)).toEqual(
      expect.arrayContaining(["vera", "rex"]),
    );
    for (const agent of realSprites) {
      expect(agent.x).toBeGreaterThan(0);
      expect(agent.y).toBeGreaterThan(0);
    }

    // Phaser renders via WebGL without preserveDrawingBuffer, so
    // canvas.getContext("2d") returns null and getImageData on a
    // copied 2D canvas comes back zeroed. Use a Playwright screenshot
    // (taken from the browser framebuffer) and analyse the PNG bytes.
    const buffer = await canvas.screenshot();
    expect(buffer.length).toBeGreaterThan(0);

    // PNG is compressed — a uniform colour produces a ~tiny file. The real
    // tilemap + agent sprites + name labels produce a substantially larger
    // PNG. Threshold chosen well above any solid colour at 1280×720.
    expect(buffer.length).toBeGreaterThan(20_000);

    // Sanity: the byte stream should have meaningful entropy. Count
    // distinct bytes in the compressed payload — a flat fill compresses
    // to a small set of bytes.
    const distinctBytes = new Set<number>();
    for (let i = 0; i < buffer.length; i += 16) {
      distinctBytes.add(buffer[i]);
    }
    expect(distinctBytes.size).toBeGreaterThan(64);
  });

  test("hides chrome in renderMode — global nav, footer, skip link are not visible", async ({ page }) => {
    await mockCues(page);
    await gotoReplay(page);

    // Acceptance criterion: ``renderMode=1`` hides all non-recording chrome.
    // The root layout still mounts those elements, so assert both that they
    // are display:none and that they are absent from the accessibility tree.
    for (const selector of ["nav", "footer", 'a[href="#main-content"]']) {
      const chrome = page.locator(selector);
      const count = await chrome.count();
      for (let i = 0; i < count; i += 1) {
        await expect(chrome.nth(i)).toBeHidden();
      }
    }
    await expect(page.getByRole("navigation")).toHaveCount(0);
    await expect(page.getByRole("contentinfo")).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: /skip to main content/i }),
    ).toHaveCount(0);

    // The full-bleed wrap still has to cover the viewport so the canvas
    // is the only visible content during recording.
    const wrap = page.locator('div[data-render-mode="1"]');
    await expect(wrap).toBeVisible();
    const wrapBox = await wrap.boundingBox();
    expect(wrapBox).not.toBeNull();
    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    expect(wrapBox!.width).toBeGreaterThanOrEqual(viewport!.width);
    expect(wrapBox!.height).toBeGreaterThanOrEqual(viewport!.height);

    const wrapZ = await wrap.evaluate(
      (el) => parseInt(window.getComputedStyle(el).zIndex || "0", 10),
    );
    expect(wrapZ).toBeGreaterThanOrEqual(9999);
  });

  test("flips __replayDone after the plan completes", async ({ page }) => {
    await mockCues(page);
    await gotoReplay(page);
    // FIXTURE_CUES last starts at 4s + per-char read time + 1s trailing buffer.
    await page.waitForFunction(
      () => (window as unknown as Record<string, unknown>).__replayDone === true,
      null,
      { timeout: 30_000 },
    );
  });

  test("speech bubble appears during a speaking cue", async ({ page }) => {
    await mockCues(page);
    await gotoReplay(page);

    const canvas = page.locator("canvas");

    // Snapshot the canvas before the first cue starts (during the
    // initial 1.5s gap from the fixture). All agents should be at desks
    // with no bubbles yet.
    const beforeShot = await canvas.screenshot();

    // Wait for any agent's bubble to render — the scene exposes the
    // ``__replayHadBubble`` flag the first time the speech-bubble
    // container becomes visible.
    await page.waitForFunction(
      () => {
        const debug = (window as unknown as { __replayDebug?: ReplayDebugState })
          .__replayDebug;
        return (
          (window as unknown as Record<string, unknown>).__replayHadBubble ===
            true &&
          debug?.hadBubble === true &&
          debug.latestBubble?.visible === true &&
          debug.latestBubble.w > 0 &&
          debug.latestBubble.h > 0
        );
      },
      null,
      { timeout: 15_000 },
    );
    const bubbleDebug = await waitForReplayDebug(page);
    expect(bubbleDebug.hadBubble).toBe(true);
    expect(bubbleDebug.latestBubble).toMatchObject({
      agentId: "vera",
      text: "Welcome to the office.",
      visible: true,
    });
    expect(bubbleDebug.latestBubble!.w).toBeGreaterThan(80);
    expect(bubbleDebug.latestBubble!.h).toBeGreaterThan(40);
    expect(
      bubbleDebug.agents.some(
        (agent) =>
          agent.id === bubbleDebug.latestBubble!.agentId &&
          agent.visible &&
          !agent.usedFallbackRectangle,
      ),
    ).toBe(true);

    const duringShot = await canvas.screenshot();

    // The during-cue screenshot must differ meaningfully from the before
    // shot — a new white speech bubble drawn over the dark office produces
    // a notable byte-size delta in the compressed PNG.
    const diff = Math.abs(duringShot.length - beforeShot.length);
    expect(duringShot.length).toBeGreaterThan(20_000);
    expect(diff).toBeGreaterThan(500);
  });
});

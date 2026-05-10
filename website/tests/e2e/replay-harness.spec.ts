import { expect, test, type Page } from "@playwright/test";
import { installReplayHarness, REPLAY_HARNESS_ORIGIN } from "./replayHarness";
import {
  FIXTURE_CUES,
  SIM_ID,
  TILESET_IMAGE_KEYS,
  TILESET_NAMES,
  type ReplayDebugState,
  type TilemapJson,
  expectOfficeReplayDebug,
  expectRenderModeChromeHidden,
  expectReplayCanvas,
  expectVisualPngAsset,
  gotoReplay,
  readReplayAsset,
  readReplaySource,
  replayUrl,
  waitForReplayDebug,
  waitForReplayDone,
  waitForReplayError,
} from "./replayFixtures";

/**
 * Visual smoke test for the office replay page (issue #476).
 *
 * The render pipeline (core/video/render_pipeline.py) drives this page
 * headlessly to produce the simulation MP4. The scene must render the
 * actual office tilemap + agent sprites — not the legacy coloured-rectangle
 * placeholder — and a speech bubble during a speaking cue.
 */

const SKIP_BROWSER_IN_CODEX_SANDBOX = process.env.CODEX_SANDBOX === "seatbelt";

async function mockCues(page: Page) {
  await installReplayHarness(page, {
    simId: SIM_ID,
    replayCues: {
      status: 200,
      body: FIXTURE_CUES,
    },
  });
}

async function gotoHarnessReplay(page: Page) {
  await gotoReplay(page, replayUrl(REPLAY_HARNESS_ORIGIN));
}

test.describe("replay scene harness sandbox fallback", () => {
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

    const sceneSource = readReplaySource("OfficeReplayScene.ts");
    expect(sceneSource).toContain("__replayDebug");
    expect(sceneSource).toContain("fallbackFloorUsed");
    expect(sceneSource).toContain("usedFallbackRectangle");
    expect(sceneSource).toContain("latestBubble");

    const bubbleSource = readReplaySource("ReplaySpeechBubble.ts");
    expect(bubbleSource).toContain("fillRoundedRect");
    expect(bubbleSource).toContain("fillTriangle");
    expect(bubbleSource).toContain("setVisible");
  });
});

test.describe("replay scene harness", () => {
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

    await page.goto(replayUrl(REPLAY_HARNESS_ORIGIN));
    const replayError = await waitForReplayError(page);
    expect(String(replayError)).toContain("Replay cue load failed");
    await expect(page.getByTestId("replay-error")).toBeVisible();
    await expect(page.getByTestId("replay-stage")).toHaveCount(0);
    await expect(page.locator("canvas")).toHaveCount(0);
  });

  test("renders office tilemap and multiple real sprites on a nonblank canvas", async ({ page }) => {
    await mockCues(page);
    await gotoHarnessReplay(page);

    const canvas = await expectReplayCanvas(page);
    const debug = await waitForReplayDebug(page);
    expectOfficeReplayDebug(debug);

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
    await gotoHarnessReplay(page);

    await expectRenderModeChromeHidden(page);
  });

  test("flips __replayDone after the plan completes", async ({ page }) => {
    await mockCues(page);
    await gotoHarnessReplay(page);
    // FIXTURE_CUES last starts at 4s + per-char read time + 1s trailing buffer.
    await waitForReplayDone(page);
  });

  test("speech bubble appears during a speaking cue", async ({ page }) => {
    await mockCues(page);
    await gotoHarnessReplay(page);

    const canvas = await expectReplayCanvas(page);

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

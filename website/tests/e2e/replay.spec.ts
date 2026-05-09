import { expect, test, type Page } from "@playwright/test";

/**
 * Visual smoke test for the office replay page (issue #476).
 *
 * The render pipeline (core/video/render_pipeline.py) drives this page
 * headlessly to produce the simulation MP4. The scene must render the
 * actual office tilemap + agent sprites — not the legacy coloured-rectangle
 * placeholder — and a speech bubble during a speaking cue.
 */

const SIM_ID = "00000000-0000-4000-8000-000000000476";
const FIXTURE_CUES = {
  sim_id: SIM_ID,
  duration_seconds: 6,
  cues: [
    { agent_id: "vera", text: "Welcome to the office.", start_seconds: 0.5 },
    { agent_id: "rex", text: "Booting the workshop.", start_seconds: 2 },
    { agent_id: "aurora", text: "Studio is online.", start_seconds: 4 },
  ],
};

async function mockCues(page: Page) {
  await page.route(`**/api/simulations/${SIM_ID}/replay-cues`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(FIXTURE_CUES),
    });
  });
}

async function gotoReplay(page: Page) {
  await page.goto(`/simulations/${SIM_ID}/replay?renderMode=1`);
  await page.waitForFunction(
    () => (window as unknown as Record<string, unknown>).__replayReady === true,
    null,
    { timeout: 30_000 },
  );
}

test.describe("replay scene", () => {
  test("renders 1280x720 canvas with non-uniform pixels (not solid black)", async ({ page }) => {
    await mockCues(page);
    await gotoReplay(page);

    const canvas = page.locator("canvas");
    await expect(canvas).toBeVisible();
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBe(1280);
    expect(box!.height).toBe(720);

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

  test("hides chrome in renderMode — full-bleed wrap covers any global nav", async ({ page }) => {
    await mockCues(page);
    await gotoReplay(page);

    // Acceptance criterion: ``renderMode=1`` hides all non-recording chrome
    // but keeps the full world canvas visible. The replay route's wrap is
    // position:fixed, inset:0, zIndex:9999 — meaning even if the global
    // Navigation rendered, it would be visually occluded by the canvas.
    const wrap = page.locator('[data-render-mode="1"]');
    await expect(wrap).toBeVisible();
    const wrapBox = await wrap.boundingBox();
    expect(wrapBox).not.toBeNull();
    // Wrap must fill the viewport so the canvas is the only visible thing.
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
    // initial 500ms gap from the fixture). All agents should be at desks
    // with no bubbles yet.
    const beforeShot = await canvas.screenshot();

    // Wait for any agent's bubble to render — the scene exposes the
    // ``__replayHadBubble`` flag the first time the speech-bubble
    // container becomes visible.
    await page.waitForFunction(
      () => (window as unknown as Record<string, unknown>).__replayHadBubble === true,
      null,
      { timeout: 15_000 },
    );
    const duringShot = await canvas.screenshot();

    // The during-cue screenshot must differ meaningfully from the before
    // shot — a new white speech bubble drawn over the dark office produces
    // a notable byte-size delta in the compressed PNG.
    const diff = Math.abs(duringShot.length - beforeShot.length);
    expect(duringShot.length).toBeGreaterThan(20_000);
    expect(diff).toBeGreaterThan(500);
  });
});

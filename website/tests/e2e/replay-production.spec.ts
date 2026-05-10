import { expect, test, type Page } from "@playwright/test";
import {
  FIXTURE_CUES,
  SIM_ID,
  expectOfficeReplayDebug,
  expectRenderModeChromeHidden,
  expectReplayCanvas,
  gotoReplay,
  replayPath,
  waitForReplayDebug,
  waitForReplayDone,
  waitForReplayError,
} from "./replayFixtures";

const SKIP_BROWSER_IN_CODEX_SANDBOX = process.env.CODEX_SANDBOX === "seatbelt";
const REPLAY_CUES_PATH = `/api/simulations/${SIM_ID}/replay-cues`;

interface ReplayCuesMock {
  status: number;
  body: unknown;
}

async function mockReplayCues(
  page: Page,
  response: ReplayCuesMock = { status: 200, body: FIXTURE_CUES },
): Promise<void> {
  await page.route(`**${REPLAY_CUES_PATH}`, async (route) => {
    await route.fulfill({
      status: response.status,
      contentType: "application/json",
      body: JSON.stringify(response.body),
    });
  });
}

function collectApiRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/api/")) {
      requests.push(pathname);
    }
  });
  return requests;
}

function collectReplayAssetResponses(page: Page): Map<string, number> {
  const responses = new Map<string, number>();
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith("/replay-assets/")) {
      responses.set(pathname, response.status());
    }
  });
  return responses;
}

function expectReplayAssetsLoaded(assetResponses: Map<string, number>): void {
  const assetPaths = [...assetResponses.keys()];
  expect(assetPaths).toEqual(
    expect.arrayContaining([
      "/replay-assets/tilesets/office/tilemap_office.json",
      "/replay-assets/tilesets/office/tileset.png",
      "/replay-assets/sprites/vera/rotations/south.png",
      "/replay-assets/sprites/rex/rotations/south.png",
    ]),
  );
  expect(
    assetPaths.some((path) =>
      path.includes("/sprites/vera/animations/breathing-idle/south/"),
    ),
  ).toBe(true);
  expect(
    assetPaths.some((path) =>
      path.includes("/sprites/rex/animations/walking/south/"),
    ),
  ).toBe(true);

  const failedAssets = [...assetResponses.entries()].filter(
    ([, status]) => status >= 400,
  );
  expect(failedAssets).toEqual([]);
}

async function expectReplayGlobals(
  page: Page,
  expectedDone: boolean,
): Promise<void> {
  const globals = await page.evaluate(() => {
    const w = window as unknown as Record<string, unknown>;
    return {
      ready: w.__replayReady,
      done: w.__replayDone,
      error: w.__replayError ?? null,
      mountedAtIsNumber: typeof w.__replayMountedAt === "number",
    };
  });

  expect(globals.ready).toBe(true);
  expect(globals.done).toBe(expectedDone);
  expect(globals.error).toBeNull();
  expect(globals.mountedAtIsNumber).toBe(true);
}

test.describe("production replay route", () => {
  test.skip(
    SKIP_BROWSER_IN_CODEX_SANDBOX,
    "Chromium cannot launch inside the Codex macOS seatbelt sandbox.",
  );

  test("renderMode mounts the real replay canvas, hides chrome, loads assets, and signals ready/done", async ({
    page,
  }) => {
    const apiRequests = collectApiRequests(page);
    const assetResponses = collectReplayAssetResponses(page);
    await mockReplayCues(page);

    await gotoReplay(page, replayPath());

    await expectReplayGlobals(page, false);
    await expectReplayCanvas(page);
    await expectRenderModeChromeHidden(page);

    const debug = await waitForReplayDebug(page);
    expectOfficeReplayDebug(debug);
    expectReplayAssetsLoaded(assetResponses);
    expect(apiRequests.length).toBeGreaterThanOrEqual(1);
    expect(apiRequests.every((path) => path === REPLAY_CUES_PATH)).toBe(true);

    await waitForReplayDone(page);
    await expectReplayGlobals(page, true);
  });

  test("renderMode cue-load failures expose the render-pipeline error contract without mounting a stage", async ({
    page,
  }) => {
    await mockReplayCues(page, {
      status: 400,
      body: { message: "cue load exploded" },
    });

    await page.goto(replayPath());
    const replayError = await waitForReplayError(page);

    expect(String(replayError)).toContain(
      "Replay cue load failed: cue load exploded",
    );
    await expect(page.locator("html")).toHaveAttribute("data-render-mode", "1");
    await expect(page.getByTestId("replay-error")).toBeVisible();
    await expect(page.getByTestId("replay-error")).toContainText(
      "Replay failed to load",
    );
    await expect(page.getByTestId("replay-stage")).toHaveCount(0);
    await expect(page.locator("canvas")).toHaveCount(0);
  });
});

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";

export const SIM_ID = "00000000-0000-4000-8000-000000000495";

export const FIXTURE_CUES = {
  sim_id: SIM_ID,
  agent_roster: ["vera", "rex", "aurora"],
  duration_seconds: 7,
  cues: [
    { agent_id: "vera", text: "Welcome to the office.", start_seconds: 1.5 },
    { agent_id: "rex", text: "Booting the workshop.", start_seconds: 3 },
    { agent_id: "aurora", text: "Studio is online.", start_seconds: 5 },
  ],
};

export interface ReplayDebugState {
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

export interface TilemapJson {
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

const WEBSITE_ROOT = resolve(__dirname, "../..");
const FRONTEND_ASSET_ROOT = resolve(WEBSITE_ROOT, "../frontend/assets");
const REPLAY_SOURCE_ROOT = resolve(WEBSITE_ROOT, "src/components/replay");

export const TILESET_NAMES = [
  "office_tiles",
  "office_tiles_hardwood",
  "office_tiles_whitetile",
  "office_tiles_teal",
  "office_tiles_purple",
  "office_tiles_bluegrey",
  "office_tiles_concrete",
  "office_tiles_olive",
];

export const TILESET_IMAGE_KEYS = [
  "tileset",
  "tileset_hardwood",
  "tileset_whitetile",
  "tileset_teal",
  "tileset_purple",
  "tileset_bluegrey",
  "tileset_concrete",
  "tileset_olive",
];

export function replayPath(): string {
  return `/simulations/${SIM_ID}/replay?renderMode=1`;
}

export function replayUrl(origin: string): string {
  return `${origin}${replayPath()}`;
}

export function replayAssetPath(relativePath: string): string {
  return resolve(FRONTEND_ASSET_ROOT, relativePath);
}

export function readReplayAsset(relativePath: string): Buffer {
  const path = replayAssetPath(relativePath);
  expect(existsSync(path), `${relativePath} should exist`).toBe(true);
  return readFileSync(path);
}

export function readReplaySource(relativePath: string): string {
  return readFileSync(resolve(REPLAY_SOURCE_ROOT, relativePath), "utf8");
}

export function expectVisualPngAsset(
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

export async function waitForReplayReady(page: Page): Promise<void> {
  await page.waitForFunction(
    () => (window as unknown as Record<string, unknown>).__replayReady === true,
    null,
    { timeout: 30_000 },
  );
}

export async function waitForReplayDone(page: Page): Promise<void> {
  await page.waitForFunction(
    () => (window as unknown as Record<string, unknown>).__replayDone === true,
    null,
    { timeout: 30_000 },
  );
}

export async function waitForReplayError(page: Page): Promise<unknown> {
  await page.waitForFunction(
    () => Boolean((window as unknown as Record<string, unknown>).__replayError),
    null,
    { timeout: 10_000 },
  );

  return page.evaluate(
    () => (window as unknown as Record<string, unknown>).__replayError,
  );
}

export async function gotoReplay(page: Page, url = replayPath()): Promise<void> {
  await page.goto(url);
  await waitForReplayReady(page);
}

export async function waitForReplayDebug(
  page: Page,
): Promise<ReplayDebugState> {
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

export async function expectReplayCanvas(page: Page): Promise<Locator> {
  const canvas = page.locator("canvas");
  await expect(canvas).toBeVisible();
  await expect(page.getByTestId("replay-stage").locator("canvas")).toHaveCount(1);
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.width).toBe(1280);
  expect(box!.height).toBe(720);
  return canvas;
}

export function expectOfficeReplayDebug(debug: ReplayDebugState): void {
  expect(debug.tilemap.fallbackFloorUsed).toBe(false);
  expect(debug.tilemap.layerCount).toBeGreaterThanOrEqual(1);
  expect(debug.tilemap.layerNames).toContain("Ground");
  expect(debug.tilemap.renderedLayerCount).toBeGreaterThanOrEqual(1);
  expect(debug.tilemap.renderedLayerNames).toContain("Ground");
  expect(debug.tilemap.tilesetCount).toBe(8);
  expect(debug.tilemap.tilesetNames).toEqual(expect.arrayContaining(TILESET_NAMES));

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
}

export async function expectRenderModeChromeHidden(page: Page): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-render-mode", "1");

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
}

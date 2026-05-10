import { existsSync, readFileSync } from "fs";
import { extname, resolve } from "path";
import type { Page, Route } from "@playwright/test";
import ts from "typescript";

export const REPLAY_HARNESS_ORIGIN = "http://replay.local";

interface ReplayHarnessResponse {
  status: number;
  body: unknown;
}

interface ReplayHarnessOptions {
  simId: string;
  replayCues: ReplayHarnessResponse;
}

const WEBSITE_ROOT = resolve(__dirname, "../..");
const moduleCache = new Map<string, string>();

const REPLAY_MODULES: Record<string, string> = {
  "/src/components/replay/OfficeReplayScene.js":
    "src/components/replay/OfficeReplayScene.ts",
  "/src/components/replay/ReplaySpeechBubble.js":
    "src/components/replay/ReplaySpeechBubble.ts",
  "/src/components/replay/agentLayout.js":
    "src/components/replay/agentLayout.ts",
  "/src/components/replay/playback.js":
    "src/components/replay/playback.ts",
};

const CONTENT_TYPES: Record<string, string> = {
  ".css": "text/css",
  ".js": "application/javascript",
  ".json": "application/json",
  ".png": "image/png",
};

function contentTypeFor(pathname: string): string {
  return CONTENT_TYPES[extname(pathname)] ?? "application/octet-stream";
}

function transpileReplayModule(relativePath: string): string {
  const cached = moduleCache.get(relativePath);
  if (cached != null) return cached;

  const source = readFileSync(resolve(WEBSITE_ROOT, relativePath), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2020,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText;

  output = output
    .replaceAll('from "phaser"', 'from "/e2e/phaser.js"')
    .replaceAll(
      'from "./agentLayout"',
      'from "/src/components/replay/agentLayout.js"',
    )
    .replaceAll(
      'from "./ReplaySpeechBubble"',
      'from "/src/components/replay/ReplaySpeechBubble.js"',
    )
    .replaceAll('from "./playback"', 'from "/src/components/replay/playback.js"');

  moduleCache.set(relativePath, output);
  return output;
}

function replayDocumentHtml(): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Replay harness</title>
    <style>
      html,
      body {
        width: 100%;
        height: 100%;
        margin: 0;
        background: #000;
      }

      html[data-render-mode="1"] nav,
      html[data-render-mode="1"] footer,
      html[data-render-mode="1"] a[href="#main-content"] {
        display: none !important;
      }
    </style>
  </head>
  <body>
    <a href="#main-content">Skip to main content</a>
    <nav>Global navigation</nav>
    <main id="main-content"></main>
    <footer>Footer</footer>
    <script type="module" src="/e2e/replay-page.js"></script>
  </body>
</html>`;
}

function replayPageModule(): string {
  return `
import Phaser from "/e2e/phaser.js";
import { OfficeReplayScene } from "/src/components/replay/OfficeReplayScene.js";
import { pickVisibleAgents } from "/src/components/replay/agentLayout.js";
import { planReplay } from "/src/components/replay/playback.js";

const STAGE_W = 1280;
const STAGE_H = 720;

function exposeReplayError(message) {
  window.__replayReady = false;
  window.__replayDone = false;
  window.__replayError = "Replay cue load failed: " + message;
}

function errorMessage(err) {
  return err instanceof Error ? err.message : "failed to load cues";
}

function renderError(message, renderMode) {
  const error = document.createElement("div");
  error.dataset.testid = "replay-error";
  error.style.minHeight = renderMode ? "100vh" : "";
  error.style.padding = renderMode ? "24px" : "12px";
  error.style.background = renderMode ? "#020617" : "#7f1d1d";
  error.style.color = "#fee2e2";
  error.style.fontSize = "14px";
  error.textContent = "Replay failed to load: " + message;
  document.body.append(error);
}

async function loadReplay() {
  const url = new URL(window.location.href);
  const renderMode = url.searchParams.get("renderMode") === "1";
  if (renderMode) {
    document.documentElement.dataset.renderMode = "1";
  }
  delete window.__replayError;
  window.__replayReady = false;
  window.__replayDone = false;
  window.__replayHadBubble = false;
  window.__replayMountedAt = Date.now();

  try {
    const res = await fetch(url.pathname.replace(/\\/replay$/, "/replay-cues"));
    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = body?.detail ? ": " + body.detail : "";
      } catch {}
      throw new Error("HTTP " + res.status + detail);
    }
    const replay = await res.json();
    const cues = replay.cues ?? [];
    const plan = planReplay(cues);
    const visibleAgents = pickVisibleAgents(
      cues.map((cue) => cue.agent_id),
      replay.agent_roster ?? [],
    );

    const wrap = document.createElement("div");
    wrap.dataset.renderMode = renderMode ? "1" : "0";
    Object.assign(wrap.style, renderMode ? {
      position: "fixed",
      inset: "0",
      background: "#000",
      zIndex: "9999",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    } : {
      position: "relative",
      margin: "0 auto",
      background: "#000",
    });

    const stage = document.createElement("div");
    stage.dataset.testid = "replay-stage";
    stage.setAttribute("role", "img");
    stage.setAttribute("aria-label", "Simulation replay");
    stage.style.width = STAGE_W + "px";
    stage.style.height = STAGE_H + "px";
    wrap.append(stage);
    document.body.append(wrap);

    new Phaser.Game({
      type: Phaser.AUTO,
      parent: stage,
      width: STAGE_W,
      height: STAGE_H,
      backgroundColor: "#000",
      pixelArt: true,
      scene: new OfficeReplayScene({
        plan,
        visibleAgents,
        onReady: () => { window.__replayReady = true; },
        onDone: () => { window.__replayDone = true; },
      }),
    });
  } catch (err) {
    const message = errorMessage(err);
    exposeReplayError(message);
    renderError(message, renderMode);
  }
}

loadReplay();
`;
}

function phaserInteropModule(): string {
  return `
import * as Phaser from "/node_modules/phaser/dist/phaser.esm.js";
export * from "/node_modules/phaser/dist/phaser.esm.js";
export default Phaser;
`;
}

async function fulfillAsset(route: Route, pathname: string): Promise<void> {
  const assetRoot = resolve(WEBSITE_ROOT, "public/replay-assets");
  const filePath = resolve(WEBSITE_ROOT, "public", pathname.slice(1));
  if (!filePath.startsWith(assetRoot) || !existsSync(filePath)) {
    await route.abort();
    return;
  }
  await route.fulfill({
    path: filePath,
    contentType: contentTypeFor(pathname),
  });
}

export async function installReplayHarness(
  page: Page,
  options: ReplayHarnessOptions,
): Promise<void> {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== REPLAY_HARNESS_ORIGIN) {
      await route.fallback();
      return;
    }

    if (url.pathname === `/simulations/${options.simId}/replay`) {
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: replayDocumentHtml(),
      });
      return;
    }

    if (url.pathname === `/simulations/${options.simId}/replay-cues`) {
      await route.fulfill({
        status: options.replayCues.status,
        contentType: "application/json",
        body: JSON.stringify(options.replayCues.body),
      });
      return;
    }

    if (url.pathname === "/e2e/replay-page.js") {
      await route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: replayPageModule(),
      });
      return;
    }

    if (url.pathname === "/e2e/phaser.js") {
      await route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: phaserInteropModule(),
      });
      return;
    }

    if (url.pathname === "/node_modules/phaser/dist/phaser.esm.js") {
      await route.fulfill({
        path: resolve(WEBSITE_ROOT, "node_modules/phaser/dist/phaser.esm.js"),
        contentType: "application/javascript",
      });
      return;
    }

    const replayModule = REPLAY_MODULES[url.pathname];
    if (replayModule != null) {
      await route.fulfill({
        status: 200,
        contentType: "application/javascript",
        body: transpileReplayModule(replayModule),
      });
      return;
    }

    if (url.pathname.startsWith("/replay-assets/")) {
      await fulfillAsset(route, url.pathname);
      return;
    }

    await route.abort();
  });
}

#!/usr/bin/env node
/**
 * Sync the replay-required subset of frontend/assets into website/public/replay-assets.
 *
 * Why: the website is a separate Next.js bundle from the Phaser frontend, but
 * `OfficeReplayScene` needs the same tilemap + agent sprites the live show uses.
 * Copying only what the replay scene actually loads keeps the website bundle
 * small and avoids shipping every direction/animation frame.
 *
 * Wired as `predev` and `prebuild` in website/package.json so `next dev` and
 * Vercel builds always start with fresh assets.
 */

import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const SRC = path.join(REPO_ROOT, "frontend", "assets");
const DST = path.join(__dirname, "..", "public", "replay-assets");

const TILESET_FILES = [
  "tileset.png",
  "tileset_hardwood.png",
  "tileset_whitetile.png",
  "tileset_teal.png",
  "tileset_purple.png",
  "tileset_bluegrey.png",
  "tileset_concrete.png",
  "tileset_olive.png",
  "tilemap_office.json",
];

const AGENT_IDS = [
  "vera",
  "rex",
  "aurora",
  "pixel",
  "fork",
  "sentinel",
  "grok",
  "alpha",
];

const IDLE_FRAMES = 4;
const WALK_FRAMES = 6;
const DIRECTIONS = ["south", "north", "east", "west"];

async function copyFile(src, dst) {
  await fs.mkdir(path.dirname(dst), { recursive: true });
  await fs.copyFile(src, dst);
}

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function syncTileset() {
  for (const name of TILESET_FILES) {
    const from = path.join(SRC, "tilesets", "office", name);
    const to = path.join(DST, "tilesets", "office", name);
    if (await exists(from)) {
      await copyFile(from, to);
    } else {
      console.warn(`[sync-replay-assets] missing tileset asset: ${from}`);
    }
  }
}

async function syncAgent(agentId) {
  const baseFrom = path.join(SRC, "sprites", agentId);
  const baseTo = path.join(DST, "sprites", agentId);

  // metadata.json (non-essential but tiny — keeps assets self-describing)
  const metaFrom = path.join(baseFrom, "metadata.json");
  if (await exists(metaFrom)) {
    await copyFile(metaFrom, path.join(baseTo, "metadata.json"));
  }

  // South-facing rotation as the static fallback texture
  const rotFrom = path.join(baseFrom, "rotations", "south.png");
  if (await exists(rotFrom)) {
    await copyFile(rotFrom, path.join(baseTo, "rotations", "south.png"));
  }

  // Idle + walking frames for cardinal directions only — keeps the bundle small.
  for (const dir of DIRECTIONS) {
    for (let i = 0; i < IDLE_FRAMES; i++) {
      const frame = String(i).padStart(3, "0");
      const from = path.join(
        baseFrom,
        "animations",
        "breathing-idle",
        dir,
        `frame_${frame}.png`,
      );
      if (await exists(from)) {
        await copyFile(
          from,
          path.join(
            baseTo,
            "animations",
            "breathing-idle",
            dir,
            `frame_${frame}.png`,
          ),
        );
      }
    }
    for (let i = 0; i < WALK_FRAMES; i++) {
      const frame = String(i).padStart(3, "0");
      const from = path.join(
        baseFrom,
        "animations",
        "walking",
        dir,
        `frame_${frame}.png`,
      );
      if (await exists(from)) {
        await copyFile(
          from,
          path.join(
            baseTo,
            "animations",
            "walking",
            dir,
            `frame_${frame}.png`,
          ),
        );
      }
    }
  }
}

async function main() {
  if (!(await exists(SRC))) {
    console.warn(
      `[sync-replay-assets] source directory missing: ${SRC} — skipping`,
    );
    return;
  }
  await fs.mkdir(DST, { recursive: true });
  await syncTileset();
  for (const agent of AGENT_IDS) {
    await syncAgent(agent);
  }
  console.log(`[sync-replay-assets] synced into ${path.relative(REPO_ROOT, DST)}`);
}

main().catch((err) => {
  console.error("[sync-replay-assets] failed:", err);
  process.exit(1);
});

import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";
import {
  planReplay,
  __PLAYBACK_TUNABLES,
} from "@/components/replay/playback";
import { buildSlots } from "@/components/replay/ReplayStage";
import type { ReplayCue } from "@/lib/api";

const STAGE_SOURCE = readFileSync(
  resolve(__dirname, "../ReplayStage.tsx"),
  "utf8",
);
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../../../app/simulations/[id]/replay/page.tsx"),
  "utf8",
);

describe("planReplay", () => {
  it("returns minimum 1s done_at_ms for empty cue list", () => {
    const plan = planReplay([]);
    expect(plan.bubbles).toEqual([]);
    expect(plan.done_at_ms).toBe(__PLAYBACK_TUNABLES.MIN_PLAYBACK_MS);
  });

  it("each cue gets a bubble bounded by the next cue's start", () => {
    const cues: ReplayCue[] = [
      { agent_id: "vera", text: "hi", start_seconds: 0 },
      { agent_id: "rex", text: "yo", start_seconds: 1.0 },
    ];
    const plan = planReplay(cues);
    expect(plan.bubbles).toHaveLength(2);
    // First bubble cannot extend past the second's start.
    expect(plan.bubbles[0].end_ms).toBeLessThanOrEqual(1000);
    expect(plan.bubbles[1].start_ms).toBe(1000);
  });

  it("last bubble end + 1s trailing buffer drives done_at_ms", () => {
    const cues: ReplayCue[] = [
      { agent_id: "vera", text: "hi", start_seconds: 0 },
      { agent_id: "rex", text: "long enough text to estimate duration", start_seconds: 5 },
    ];
    const plan = planReplay(cues);
    const last = plan.bubbles[plan.bubbles.length - 1];
    expect(plan.done_at_ms).toBe(
      last.end_ms + __PLAYBACK_TUNABLES.TRAILING_BUFFER_MS,
    );
  });

  it("clamps done_at_ms to MIN_PLAYBACK_MS even for tiny cue", () => {
    const cues: ReplayCue[] = [
      { agent_id: "vera", text: "x", start_seconds: 0 },
    ];
    const plan = planReplay(cues);
    expect(plan.done_at_ms).toBeGreaterThanOrEqual(
      __PLAYBACK_TUNABLES.MIN_PLAYBACK_MS,
    );
  });

  it("re-sorts cues so out-of-order input is normalized", () => {
    const cues: ReplayCue[] = [
      { agent_id: "rex", text: "second", start_seconds: 5 },
      { agent_id: "vera", text: "first", start_seconds: 0 },
    ];
    const plan = planReplay(cues);
    expect(plan.bubbles[0].agent_id).toBe("vera");
    expect(plan.bubbles[1].agent_id).toBe("rex");
  });

  it("estimates per-cue duration from char count", () => {
    const longText = "x".repeat(100);
    const cues: ReplayCue[] = [
      { agent_id: "vera", text: longText, start_seconds: 0 },
    ];
    const plan = planReplay(cues);
    const expected_ms =
      100 * __PLAYBACK_TUNABLES.PER_CHAR_MS +
      __PLAYBACK_TUNABLES.PER_CUE_BUFFER_MS;
    expect(plan.bubbles[0].end_ms).toBe(expected_ms);
  });
});

describe("buildSlots", () => {
  it("places each unique speaker on the stage", () => {
    const cues: ReplayCue[] = [
      { agent_id: "vera", text: "a", start_seconds: 0 },
      { agent_id: "rex", text: "b", start_seconds: 1 },
      { agent_id: "vera", text: "c", start_seconds: 2 },
    ];
    const slots = buildSlots(cues);
    expect(slots.map((s) => s.id).sort()).toEqual(["rex", "vera"]);
  });

  it("preserves canonical agent ordering for known agents", () => {
    const cues: ReplayCue[] = [
      { agent_id: "rex", text: "a", start_seconds: 0 },
      { agent_id: "vera", text: "b", start_seconds: 1 },
    ];
    const slots = buildSlots(cues);
    // vera is canonical agent #1, rex is #2 → vera should sort first
    expect(slots[0].id).toBe("vera");
    expect(slots[1].id).toBe("rex");
  });

  it("appends unknown agents after canonical ones", () => {
    const cues: ReplayCue[] = [
      { agent_id: "wolf", text: "?", start_seconds: 0 },
      { agent_id: "vera", text: "hi", start_seconds: 1 },
    ];
    const slots = buildSlots(cues);
    expect(slots[0].id).toBe("vera");
    expect(slots[1].id).toBe("wolf");
  });

  it("returns empty array when no cues", () => {
    expect(buildSlots([])).toEqual([]);
  });

  it("places slots within the 1280x720 stage bounds", () => {
    const cues: ReplayCue[] = [
      "vera",
      "rex",
      "aurora",
      "pixel",
      "fork",
      "sentinel",
    ].map((id, i) => ({
      agent_id: id,
      text: "x",
      start_seconds: i,
    }));
    const slots = buildSlots(cues);
    for (const s of slots) {
      expect(s.x).toBeGreaterThan(0);
      expect(s.x).toBeLessThan(1280);
      expect(s.y).toBeGreaterThan(0);
      expect(s.y).toBeLessThan(720);
    }
  });
});

describe("ReplayStage source structure", () => {
  it("flips __replayReady on Phaser scene POST_UPDATE", () => {
    expect(STAGE_SOURCE).toContain("__replayReady");
    expect(STAGE_SOURCE).toContain("POST_UPDATE");
  });

  it("flips __replayDone once playback elapsed exceeds plan.done_at_ms", () => {
    expect(STAGE_SOURCE).toContain("__replayDone");
    expect(STAGE_SOURCE).toContain("plan.done_at_ms");
  });

  it("destroys the Phaser game on unmount", () => {
    expect(STAGE_SOURCE).toContain("destroy(true)");
  });

  it("loads phaser via dynamic import so SSR is bypassed", () => {
    expect(STAGE_SOURCE).toContain('await import("phaser")');
  });
});

describe("Replay page route", () => {
  it("dynamically imports ReplayStage with ssr disabled", () => {
    expect(PAGE_SOURCE).toContain("ssr: false");
    expect(PAGE_SOURCE).toContain("@/components/replay/ReplayStage");
  });

  it("reads renderMode from search params", () => {
    expect(PAGE_SOURCE).toContain('search?.get("renderMode")');
  });

  it("fetches cues via getReplayCues helper", () => {
    expect(PAGE_SOURCE).toContain("getReplayCues");
  });

  it("hides chrome (error banner) when renderMode=1", () => {
    // The error banner must be gated on !renderMode so it doesn't show
    // up in the captured MP4.
    expect(PAGE_SOURCE).toMatch(/error\s*&&\s*!renderMode/);
  });
});

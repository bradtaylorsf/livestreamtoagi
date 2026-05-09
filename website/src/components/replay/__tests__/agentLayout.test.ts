import { describe, expect, it } from "vitest";
import {
  clampBubblePosition,
  getDeskPosition,
  getKnownAgents,
  getSpeakingPosition,
  hasAgentLayout,
  __LAYOUT_INTERNALS,
} from "../agentLayout";

const { STAGE_W, STAGE_H } = __LAYOUT_INTERNALS;

describe("agentLayout", () => {
  it("returns desk positions for every known agent", () => {
    const agents = getKnownAgents();
    expect(agents).toContain("vera");
    expect(agents).toContain("rex");
    expect(agents).toContain("aurora");
    expect(agents.length).toBeGreaterThanOrEqual(8);
    for (const agent of agents) {
      expect(hasAgentLayout(agent)).toBe(true);
      const pos = getDeskPosition(agent);
      expect(pos.x).toBeGreaterThanOrEqual(0);
      expect(pos.x).toBeLessThanOrEqual(STAGE_W);
      expect(pos.y).toBeGreaterThanOrEqual(0);
      expect(pos.y).toBeLessThanOrEqual(STAGE_H);
    }
  });

  it("falls back gracefully for unknown agents", () => {
    expect(hasAgentLayout("not-a-real-agent")).toBe(false);
    const pos = getDeskPosition("not-a-real-agent");
    expect(pos.x).toBeGreaterThanOrEqual(0);
    expect(pos.y).toBeGreaterThanOrEqual(0);
  });

  it("places agents in distinct rooms (no two share the same coordinates)", () => {
    const seen = new Set<string>();
    for (const agent of getKnownAgents()) {
      if (agent === "management") continue; // intentionally overlaps alpha
      const p = getDeskPosition(agent);
      const key = `${p.x},${p.y}`;
      expect(seen.has(key), `${agent} duplicates ${key}`).toBe(false);
      seen.add(key);
    }
  });

  it("getSpeakingPosition is deterministic and stays inside the canvas", () => {
    const a = getSpeakingPosition("vera", 3);
    const b = getSpeakingPosition("vera", 3);
    expect(a).toEqual(b);
    for (let i = 0; i < 20; i++) {
      const p = getSpeakingPosition("rex", i);
      expect(p.x).toBeGreaterThan(0);
      expect(p.x).toBeLessThan(STAGE_W);
      expect(p.y).toBeGreaterThan(0);
      expect(p.y).toBeLessThan(STAGE_H);
    }
  });

  it("clampBubblePosition keeps the entire bubble inside the viewport", () => {
    // Way to the right — should pull back inside
    const right = clampBubblePosition(1280, 360, 320, 80);
    expect(right.x + 320).toBeLessThanOrEqual(STAGE_W);
    expect(right.x).toBeGreaterThanOrEqual(0);

    // Way to the left
    const left = clampBubblePosition(0, 360, 320, 80);
    expect(left.x).toBeGreaterThanOrEqual(0);

    // High up — bubble would clip top, so it should drop below the speaker
    const top = clampBubblePosition(640, 0, 320, 80);
    expect(top.y).toBeGreaterThanOrEqual(0);

    // Bottom — should not clip below
    const bot = clampBubblePosition(640, 720, 320, 80);
    expect(bot.y + 80).toBeLessThanOrEqual(STAGE_H);
  });

  it("clampBubblePosition centers the bubble horizontally on the speaker when there's room", () => {
    const pos = clampBubblePosition(640, 360, 200, 80);
    // 640 - 200/2 = 540
    expect(pos.x).toBe(540);
  });
});

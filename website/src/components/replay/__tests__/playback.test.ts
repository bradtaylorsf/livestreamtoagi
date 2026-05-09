import { describe, expect, it } from "vitest";
import { planReplay, __PLAYBACK_TUNABLES } from "../playback";

const { MIN_PLAYBACK_MS, TRAILING_BUFFER_MS } = __PLAYBACK_TUNABLES;

describe("planReplay", () => {
  it("returns the minimum playback window for an empty cue list", () => {
    const plan = planReplay([]);
    expect(plan.bubbles).toEqual([]);
    expect(plan.done_at_ms).toBe(MIN_PLAYBACK_MS);
  });

  it("converts cues into bubbles preserving start order", () => {
    const plan = planReplay([
      { agent_id: "vera", text: "Hello", start_seconds: 0 },
      { agent_id: "rex", text: "Hi", start_seconds: 1.5 },
      { agent_id: "aurora", text: "Hey", start_seconds: 3 },
    ]);
    expect(plan.bubbles).toHaveLength(3);
    expect(plan.bubbles[0].agent_id).toBe("vera");
    expect(plan.bubbles[0].start_ms).toBe(0);
    expect(plan.bubbles[1].start_ms).toBe(1500);
    expect(plan.bubbles[2].start_ms).toBe(3000);
  });

  it("allows cross-agent bubbles to overlap (same agent does not)", () => {
    const plan = planReplay([
      { agent_id: "vera", text: "long line that takes ages to say", start_seconds: 0 },
      { agent_id: "rex", text: "interjection", start_seconds: 0.5 },
      { agent_id: "vera", text: "more vera", start_seconds: 4 },
    ]);
    const veraBubbles = plan.bubbles.filter((b) => b.agent_id === "vera");
    const rexBubbles = plan.bubbles.filter((b) => b.agent_id === "rex");
    // First vera bubble must end by the time her second one starts
    expect(veraBubbles[0].end_ms).toBeLessThanOrEqual(veraBubbles[1].start_ms);
    // Rex's bubble may overlap vera's first bubble
    expect(rexBubbles[0].start_ms).toBeLessThan(veraBubbles[0].end_ms);
  });

  it("done_at_ms is at least MIN_PLAYBACK_MS even for short cues", () => {
    const plan = planReplay([
      { agent_id: "vera", text: "hi", start_seconds: 0 },
    ]);
    expect(plan.done_at_ms).toBeGreaterThanOrEqual(MIN_PLAYBACK_MS);
    // And should always trail past the last bubble end
    const lastEnd = plan.bubbles[0].end_ms;
    expect(plan.done_at_ms).toBeGreaterThanOrEqual(lastEnd + TRAILING_BUFFER_MS);
  });

  it("sorts unsorted input cues", () => {
    const plan = planReplay([
      { agent_id: "rex", text: "second", start_seconds: 2 },
      { agent_id: "vera", text: "first", start_seconds: 0 },
    ]);
    expect(plan.bubbles[0].agent_id).toBe("vera");
    expect(plan.bubbles[1].agent_id).toBe("rex");
  });
});

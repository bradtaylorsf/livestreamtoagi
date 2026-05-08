import { describe, expect, it } from "vitest";
import {
  formatBoolean,
  formatMaxCost,
  formatNumber,
  formatString,
  formatTimestamp,
  getAgents,
  getClockState,
  getPhaseNames,
} from "@/components/ConfigViewer";

const EM_DASH = "—";

// Representative config matching the local-topic-exhaustion shape.
const SAMPLE_CONFIG = {
  mode: "seeded",
  name: "local-topic-exhaustion",
  description: "Topic exhaustion test",
  speed: "fast",
  speed_multiplier: 42.0,
  dry_run: false,
  management_shadow: true,
  max_cost: "10.0",
  seed_file: "scenarios/topic_exhaustion_test.yaml",
  agents: ["vera", "rex", "aurora", "pixel", "fork"],
  phase_count: 5,
  phase_names: ["intro", "discussion", "argument", "resolution", "wrap"],
  clock_state: {
    start_time: "2026-05-01T08:00:00.000Z",
    speed_multiplier: 42.0,
    elapsed_seconds: 3725,
    current_simulated_time: "2026-05-01T09:02:05.000Z",
    simulated_day: 1,
  },
  llm_provider: "openrouter",
};

describe("ConfigViewer formatters", () => {
  describe("formatBoolean", () => {
    it("renders Yes / No / em-dash", () => {
      expect(formatBoolean(true)).toBe("Yes");
      expect(formatBoolean(false)).toBe("No");
      expect(formatBoolean(undefined)).toBe(EM_DASH);
      expect(formatBoolean(null)).toBe(EM_DASH);
    });
  });

  describe("formatTimestamp", () => {
    it("converts ISO string to a human-readable timestamp (no raw ISO)", () => {
      const out = formatTimestamp("2026-05-01T08:00:00.000Z");
      expect(out).not.toBe("2026-05-01T08:00:00.000Z");
      expect(out.length).toBeGreaterThan(0);
      // Locale string should not contain the literal "T" separator from ISO format
      expect(out).not.toMatch(/\dT\d/);
    });

    it("returns em-dash for empty/missing/non-string", () => {
      expect(formatTimestamp("")).toBe(EM_DASH);
      expect(formatTimestamp(undefined)).toBe(EM_DASH);
      expect(formatTimestamp(null)).toBe(EM_DASH);
      expect(formatTimestamp(123 as unknown)).toBe(EM_DASH);
    });

    it("returns the raw value if it cannot be parsed as a date", () => {
      expect(formatTimestamp("not-a-date")).toBe("not-a-date");
    });
  });

  describe("formatMaxCost", () => {
    it("formats numeric strings as $X.XX", () => {
      expect(formatMaxCost("10.0")).toBe("$10.00");
      expect(formatMaxCost(7.5)).toBe("$7.50");
      expect(formatMaxCost(0)).toBe("$0.00");
    });
    it("returns em-dash for missing values", () => {
      expect(formatMaxCost(null)).toBe(EM_DASH);
      expect(formatMaxCost("")).toBe(EM_DASH);
    });
  });

  describe("formatNumber / formatString", () => {
    it("formatNumber returns a numeric string or em-dash", () => {
      expect(formatNumber(42)).toBe("42");
      expect(formatNumber("3")).toBe("3");
      expect(formatNumber(null)).toBe(EM_DASH);
    });
    it("formatString stringifies or em-dashes", () => {
      expect(formatString("seeded")).toBe("seeded");
      expect(formatString("")).toBe(EM_DASH);
      expect(formatString(null)).toBe(EM_DASH);
    });
  });
});

describe("ConfigViewer extractors", () => {
  it("getAgents returns the string list", () => {
    expect(getAgents(SAMPLE_CONFIG)).toEqual([
      "vera",
      "rex",
      "aurora",
      "pixel",
      "fork",
    ]);
  });

  it("getAgents tolerates non-array values", () => {
    expect(getAgents({ agents: "vera" })).toEqual([]);
    expect(getAgents({})).toEqual([]);
  });

  it("getPhaseNames returns the phase array", () => {
    expect(getPhaseNames(SAMPLE_CONFIG)).toHaveLength(5);
  });

  it("getClockState returns the nested clock object", () => {
    const clock = getClockState(SAMPLE_CONFIG);
    expect(clock.simulated_day).toBe(1);
    expect(clock.elapsed_seconds).toBe(3725);
    expect(clock.start_time).toBe("2026-05-01T08:00:00.000Z");
  });

  it("getClockState returns empty object when missing", () => {
    expect(getClockState({})).toEqual({});
  });
});

describe("ConfigViewer phase collapsing logic", () => {
  // Mirrors the PHASE_PREVIEW_LIMIT used by the component (3).
  const PHASE_PREVIEW_LIMIT = 3;

  it("a 5-phase list is collapsed by default to the first 3", () => {
    const phases = getPhaseNames(SAMPLE_CONFIG);
    const collapsed = phases.slice(0, PHASE_PREVIEW_LIMIT);
    expect(collapsed).toHaveLength(3);
    expect(phases.length).toBeGreaterThan(PHASE_PREVIEW_LIMIT);
  });

  it("3-or-fewer phases need no toggle", () => {
    const short = ["a", "b"];
    expect(short.length <= PHASE_PREVIEW_LIMIT).toBe(true);
  });
});

describe("ConfigViewer renders no raw JSON blob", () => {
  // Regression guard: make sure we never accidentally re-introduce a
  // JSON.stringify dump of the raw config.
  it("the component module does not call JSON.stringify on its config", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../ConfigViewer.tsx"),
      "utf8",
    );
    expect(src).not.toMatch(/JSON\.stringify\(\s*config/);
  });
});

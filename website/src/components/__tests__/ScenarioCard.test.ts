import { describe, expect, it } from "vitest";
import {
  buildRunHref,
  formatScenarioEstimate,
} from "@/components/ScenarioCard";
import type { PublicScenarioMeta } from "@/lib/api";

function makeScenario(
  overrides: Partial<PublicScenarioMeta> = {},
): PublicScenarioMeta {
  return {
    filename: "awakening.yaml",
    name: "Awakening (Day 1)",
    description: "Day 1 blank-slate simulation.",
    agents: ["vera", "rex", "aurora"],
    phase_count: 9,
    expected_max_cost: 10,
    expected_runtime_minutes: 25,
    ...overrides,
  };
}

describe("ScenarioCard.formatScenarioEstimate", () => {
  it("renders integer dollars when cost is at least $1", () => {
    expect(
      formatScenarioEstimate({
        expected_max_cost: 10,
        expected_runtime_minutes: 25,
      }),
    ).toBe("≈ 25 min / $10");
  });

  it("renders cents for sub-dollar costs (local LLM)", () => {
    expect(
      formatScenarioEstimate({
        expected_max_cost: 0.01,
        expected_runtime_minutes: 15,
      }),
    ).toBe("≈ 15 min / $0.01");
  });

  it("falls back to em-dashes when values are zero", () => {
    expect(
      formatScenarioEstimate({
        expected_max_cost: 0,
        expected_runtime_minutes: 0,
      }),
    ).toBe("≈ — min / $—");
  });
});

describe("ScenarioCard.buildRunHref", () => {
  it("links to /simulations/new with the scenario filename query param", () => {
    expect(buildRunHref(makeScenario())).toBe(
      "/simulations/new?scenario=awakening.yaml",
    );
  });

  it("encodes filenames with special characters", () => {
    expect(buildRunHref({ filename: "scenario with spaces.yaml" })).toBe(
      "/simulations/new?scenario=scenario%20with%20spaces.yaml",
    );
  });
});

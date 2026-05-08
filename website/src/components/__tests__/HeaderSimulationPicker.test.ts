import { describe, expect, it } from "vitest";
import {
  buildPickerLabel,
  filterSimulations,
} from "@/components/HeaderSimulationPicker";
import type { PublicSimulation } from "@/lib/api";

function makeSim(
  id: string,
  status: string,
  name = id,
  startedAt: string | null = null,
): PublicSimulation {
  return {
    id,
    name,
    description: null,
    status,
    started_at: startedAt,
    completed_at: null,
    real_duration: null,
    total_conversations: 0,
    total_turns: 0,
    total_cost: "0",
    total_artifacts: 0,
    agents_participated: [],
    is_featured: false,
    video_url: null,
  };
}

describe("HeaderSimulationPicker.buildPickerLabel", () => {
  it("shows aggregate label when no simulation is active", () => {
    expect(buildPickerLabel(null, null)).toBe(
      "Aggregate (no simulation selected)",
    );
  });

  it("renders 'name · status' when active sim detail is known", () => {
    const sim = makeSim("abc", "completed", "local-topic-exhaustion");
    expect(buildPickerLabel("abc", sim)).toBe(
      "local-topic-exhaustion · completed",
    );
  });

  it("falls back to the bare id when active id has no detail loaded yet", () => {
    expect(buildPickerLabel("abc", null)).toBe("abc");
  });
});

describe("HeaderSimulationPicker.filterSimulations", () => {
  const sims = [
    makeSim("1", "running", "local-topic-exhaustion"),
    makeSim("2", "completed", "budget-crisis"),
    makeSim("3", "completed", "first-48h"),
  ];

  it("returns the input unchanged for empty query", () => {
    expect(filterSimulations(sims, "")).toEqual(sims);
    expect(filterSimulations(sims, "   ")).toEqual(sims);
  });

  it("matches case-insensitively on the name substring", () => {
    expect(
      filterSimulations(sims, "BUDGET").map((s) => s.id),
    ).toEqual(["2"]);
    expect(
      filterSimulations(sims, "topic").map((s) => s.id),
    ).toEqual(["1"]);
  });

  it("returns an empty array when nothing matches", () => {
    expect(filterSimulations(sims, "doesnotexist")).toEqual([]);
  });
});

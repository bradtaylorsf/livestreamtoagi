import { describe, expect, it } from "vitest";
import { sortSimulations } from "@/components/SimulationPicker";
import type { PublicSimulation } from "@/lib/api";

function makeSim(
  id: string,
  status: string,
  startedAt: string | null,
  name = id,
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

describe("SimulationPicker sortSimulations", () => {
  it("ranks running before completed", () => {
    const sims = [
      makeSim("a", "completed", "2025-01-01T00:00:00Z"),
      makeSim("b", "running", "2024-01-01T00:00:00Z"),
    ];
    const sorted = sortSimulations(sims);
    expect(sorted.map((s) => s.id)).toEqual(["b", "a"]);
  });

  it("sorts simulations of equal status by started_at desc", () => {
    const sims = [
      makeSim("old", "completed", "2024-01-01T00:00:00Z"),
      makeSim("new", "completed", "2025-01-01T00:00:00Z"),
      makeSim("mid", "completed", "2024-06-01T00:00:00Z"),
    ];
    const sorted = sortSimulations(sims);
    expect(sorted.map((s) => s.id)).toEqual(["new", "mid", "old"]);
  });

  it("places unknown statuses last", () => {
    const sims = [
      makeSim("weird", "archived", "2025-01-01T00:00:00Z"),
      makeSim("done", "completed", "2024-01-01T00:00:00Z"),
    ];
    const sorted = sortSimulations(sims);
    expect(sorted.map((s) => s.id)).toEqual(["done", "weird"]);
  });

  it("treats null started_at as oldest", () => {
    const sims = [
      makeSim("nostart", "completed", null),
      makeSim("withstart", "completed", "2025-01-01T00:00:00Z"),
    ];
    const sorted = sortSimulations(sims);
    expect(sorted.map((s) => s.id)).toEqual(["withstart", "nostart"]);
  });

  it("returns a new array (does not mutate input)", () => {
    const sims = [
      makeSim("a", "completed", "2024-01-01T00:00:00Z"),
      makeSim("b", "running", "2025-01-01T00:00:00Z"),
    ];
    const original = [...sims];
    sortSimulations(sims);
    expect(sims).toEqual(original);
  });
});

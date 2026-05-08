import { describe, expect, it } from "vitest";
import { summarizeSimulation } from "@/components/FeaturedSimulations";
import { formatSimulationStats } from "@/components/RecentSimulations";
import type { PublicSimulation } from "@/lib/api";

function makeSim(overrides: Partial<PublicSimulation> = {}): PublicSimulation {
  return {
    id: "sim-1",
    name: "Test sim",
    description: null,
    status: "completed",
    started_at: "2026-04-01T00:00:00Z",
    completed_at: "2026-04-01T01:00:00Z",
    real_duration: "1h",
    total_conversations: 5,
    total_turns: 42,
    total_cost: "1.2345",
    total_artifacts: 3,
    agents_participated: ["vera", "rex"],
    is_featured: false,
    video_url: null,
    ...overrides,
  };
}

describe("FeaturedSimulations.summarizeSimulation", () => {
  it("uses description when available", () => {
    const sim = makeSim({ description: "A custom hand-curated summary." });
    expect(summarizeSimulation(sim)).toBe("A custom hand-curated summary.");
  });

  it("falls back to compact stats when description is empty", () => {
    const sim = makeSim({ description: "  " });
    expect(summarizeSimulation(sim)).toMatch(/2 agents · 42 turns · \$1\.23/);
  });

  it("handles single-agent / single-turn pluralization", () => {
    const sim = makeSim({
      description: null,
      agents_participated: ["vera"],
      total_turns: 1,
      total_cost: "0",
    });
    expect(summarizeSimulation(sim)).toBe("1 agent · 1 turn · $0.00");
  });
});

describe("RecentSimulations.formatSimulationStats", () => {
  it("renders agents/turns/cost summary", () => {
    const sim = makeSim();
    expect(formatSimulationStats(sim)).toBe("2 agents · 42 turns · $1.23");
  });

  it("treats blank cost as zero", () => {
    const sim = makeSim({ total_cost: "" });
    expect(formatSimulationStats(sim)).toBe("2 agents · 42 turns · $0.00");
  });
});

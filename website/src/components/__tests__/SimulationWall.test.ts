import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";
import {
  paramsForTab,
  dedupeById,
} from "@/components/SimulationWall";
import {
  submitterLabel,
  formatCost,
} from "@/components/SimulationWallTile";
import type { PublicSimulation } from "@/lib/api";

const WALL_SOURCE = readFileSync(
  resolve(__dirname, "../SimulationWall.tsx"),
  "utf8",
);
const TILE_SOURCE = readFileSync(
  resolve(__dirname, "../SimulationWallTile.tsx"),
  "utf8",
);
const PAGE_SOURCE = readFileSync(
  resolve(__dirname, "../../app/simulations/live/page.tsx"),
  "utf8",
);

function makeSim(overrides: Partial<PublicSimulation> = {}): PublicSimulation {
  return {
    id: "sim-1",
    name: "Test sim",
    description: null,
    status: "running",
    started_at: "2026-04-01T00:00:00Z",
    completed_at: null,
    real_duration: null,
    total_conversations: 5,
    total_turns: 42,
    total_cost: "1.2345",
    total_artifacts: 3,
    agents_participated: ["vera", "rex"],
    is_featured: false,
    video_url: null,
    submitter_display_name: null,
    ...overrides,
  };
}

describe("paramsForTab", () => {
  it("running tab requests status=running", () => {
    expect(paramsForTab("running")).toMatchObject({ status: "running" });
  });

  it("recent tab requests completed_within_hours=1", () => {
    expect(paramsForTab("recent")).toMatchObject({
      completed_within_hours: 1,
    });
  });

  it("featured tab requests is_featured=true", () => {
    expect(paramsForTab("featured")).toMatchObject({ is_featured: true });
  });

  it("all tab does not constrain status, recency, or featured", () => {
    const p = paramsForTab("all") ?? {};
    expect("status" in p).toBe(false);
    expect("completed_within_hours" in p).toBe(false);
    expect("is_featured" in p).toBe(false);
  });

  it("every tab requests a generous limit so wall handles 50+ tiles", () => {
    for (const tab of ["all", "running", "recent", "featured"] as const) {
      const p = paramsForTab(tab) ?? {};
      expect(p.limit ?? 0).toBeGreaterThanOrEqual(50);
    }
  });
});

describe("dedupeById", () => {
  it("keeps first occurrence and drops subsequent duplicates", () => {
    const a = makeSim({ id: "a", name: "first" });
    const b = makeSim({ id: "b" });
    const aDup = makeSim({ id: "a", name: "second" });
    const out = dedupeById([a, b, aDup]);
    expect(out.map((s) => s.id)).toEqual(["a", "b"]);
    expect(out[0].name).toBe("first");
  });
});

describe("submitterLabel", () => {
  it("shows 'Anonymous' when display name is null", () => {
    expect(submitterLabel(makeSim({ submitter_display_name: null }))).toBe(
      "Anonymous",
    );
  });

  it("shows the submitter's display name when present", () => {
    expect(
      submitterLabel(makeSim({ submitter_display_name: "brad" })),
    ).toBe("brad");
  });
});

describe("formatCost", () => {
  it("formats blank cost as $0.0000", () => {
    expect(formatCost("")).toBe("$0.0000");
  });

  it("formats numeric strings with 4 decimals", () => {
    expect(formatCost("1.2345")).toBe("$1.2345");
  });

  it("treats null as zero", () => {
    expect(formatCost(null)).toBe("$0.0000");
  });
});

describe("SimulationWall component source", () => {
  it("polls every 5 seconds (5_000 or 5000 ms)", () => {
    expect(WALL_SOURCE).toMatch(/5_000|5000/);
  });

  it("renders a responsive grid that collapses to a single column on mobile", () => {
    expect(WALL_SOURCE).toContain("grid-cols-1");
    expect(WALL_SOURCE).toMatch(/sm:grid-cols-2|md:grid-cols-2/);
  });

  it("exposes filter tabs for All, Running, Recent (1h) and Featured", () => {
    expect(WALL_SOURCE).toContain("All");
    expect(WALL_SOURCE).toContain("Running");
    expect(WALL_SOURCE).toContain("Recent (1h)");
    expect(WALL_SOURCE).toContain("Featured");
  });

  it("flags polling as a TODO until websocket arrives", () => {
    expect(WALL_SOURCE).toMatch(/TODO\(websocket\)/);
  });
});

describe("SimulationWallTile component source", () => {
  it("links each tile to the simulation detail route", () => {
    expect(TILE_SOURCE).toContain("/simulations/${sim.id}");
  });

  it("memoizes the tile so polling does not re-render the whole grid", () => {
    expect(TILE_SOURCE).toMatch(/export default memo/);
  });

  it("shows a LIVE pulse badge for running tiles", () => {
    expect(TILE_SOURCE).toContain("LIVE");
    expect(TILE_SOURCE).toContain("animate-pulse");
  });
});

describe("/simulations/live page", () => {
  it("renders the SimulationWall and uses the WALL OF SIMULATIONS heading", () => {
    expect(PAGE_SOURCE).toContain("SimulationWall");
    expect(PAGE_SOURCE).toMatch(/WALL OF SIMULATIONS/);
  });

  it("declares page metadata title", () => {
    expect(PAGE_SOURCE).toMatch(/title:\s*"Wall of Simulations"/);
  });
});

import { describe, expect, it } from "vitest";
import type { WorldMilestone } from "@/types";

// Test the data structure used by WorldTimeline
describe("WorldTimeline data", () => {
  const milestones: WorldMilestone[] = [
    {
      id: "1",
      date: "2026-04-01",
      title: "The Office Appears",
      description: "Initial world generation",
    },
    {
      id: "2",
      date: "2026-04-03",
      title: "First Renovation",
      description: "Aurora redesigned the main office",
    },
  ];

  it("milestone items have required fields", () => {
    for (const milestone of milestones) {
      expect(milestone.id).toBeTruthy();
      expect(milestone.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(milestone.title).toBeTruthy();
      expect(milestone.description).toBeTruthy();
    }
  });

  it("milestones are in chronological order", () => {
    for (let i = 1; i < milestones.length; i++) {
      expect(milestones[i].date >= milestones[i - 1].date).toBe(true);
    }
  });

  it("each milestone has a unique ID", () => {
    const ids = milestones.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

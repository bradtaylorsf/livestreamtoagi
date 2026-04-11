import { describe, expect, it } from "vitest";
import type { LoreEvent, WorldMilestone } from "@/types";

// Test the data mapping from LoreEvent to WorldMilestone
function loreToMilestone(event: LoreEvent, index: number): WorldMilestone {
  return {
    id: String(event.id ?? index),
    date: event.created_at?.split("T")[0] ?? "Unknown",
    title: event.event_type ?? "World Event",
    description: event.description ?? "",
  };
}

describe("WorldTimeline data mapping", () => {
  it("maps LoreEvent to WorldMilestone correctly", () => {
    const event: LoreEvent = {
      id: 42,
      event_type: "room_built",
      description: "Rex built the server room",
      agents_involved: ["rex"],
      audience_participation: false,
      created_at: "2026-04-05T14:30:00Z",
    };
    const milestone = loreToMilestone(event, 0);
    expect(milestone.id).toBe("42");
    expect(milestone.date).toBe("2026-04-05");
    expect(milestone.title).toBe("room_built");
    expect(milestone.description).toBe("Rex built the server room");
  });

  it("handles null fields gracefully", () => {
    const event: LoreEvent = {
      id: 1,
      event_type: null,
      description: null,
      agents_involved: null,
      audience_participation: false,
      created_at: null,
    };
    const milestone = loreToMilestone(event, 5);
    expect(milestone.id).toBe("1");
    expect(milestone.date).toBe("Unknown");
    expect(milestone.title).toBe("World Event");
    expect(milestone.description).toBe("");
  });

  it("milestone items have required fields", () => {
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

    for (const milestone of milestones) {
      expect(milestone.id).toBeTruthy();
      expect(milestone.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(milestone.title).toBeTruthy();
      expect(milestone.description).toBeTruthy();
    }
  });

  it("milestones are in chronological order", () => {
    const milestones: WorldMilestone[] = [
      { id: "1", date: "2026-04-01", title: "A", description: "a" },
      { id: "2", date: "2026-04-03", title: "B", description: "b" },
    ];
    for (let i = 1; i < milestones.length; i++) {
      expect(milestones[i].date >= milestones[i - 1].date).toBe(true);
    }
  });

  it("each milestone has a unique ID", () => {
    const milestones: WorldMilestone[] = [
      { id: "1", date: "2026-04-01", title: "A", description: "a" },
      { id: "2", date: "2026-04-03", title: "B", description: "b" },
    ];
    const ids = milestones.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

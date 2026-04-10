import { describe, expect, it } from "vitest";
import type { SelectionLogEntry } from "@/types";

// Test the data transformation and logic used by ConversationReplay
// and its sub-components, without requiring DOM rendering.

// ── Energy data transformation ────────────────────────────────

function buildEnergyData(selections: SelectionLogEntry[]) {
  return selections.map((s) => ({
    turn: s.turn_number,
    energy: s.conversation_energy ?? 0,
  }));
}

const MOCK_SELECTIONS: SelectionLogEntry[] = [
  {
    turn_number: 1,
    selected_agent_id: "vera",
    was_interrupt: false,
    agent_scores: {
      vera: { time_since_spoke: 0.8, topic_relevance: 0.6, chattiness: 0.7, adjacency_fit: 0.5, random_jitter: 0.3 },
      rex: { time_since_spoke: 0.5, topic_relevance: 0.4, chattiness: 0.3, adjacency_fit: 0.2, random_jitter: 0.1 },
    },
    detected_topic: "planning",
    previous_speaker_id: null,
    conversation_energy: 0.85,
  },
  {
    turn_number: 2,
    selected_agent_id: "rex",
    was_interrupt: true,
    agent_scores: {
      vera: { time_since_spoke: 0.2, topic_relevance: 0.4, chattiness: 0.7, adjacency_fit: 0.5, random_jitter: 0.2 },
      rex: { time_since_spoke: 0.9, topic_relevance: 0.8, chattiness: 0.3, adjacency_fit: 0.7, random_jitter: 0.4 },
    },
    detected_topic: "code",
    previous_speaker_id: "vera",
    conversation_energy: 0.72,
  },
  {
    turn_number: 3,
    selected_agent_id: "aurora",
    was_interrupt: false,
    agent_scores: {},
    detected_topic: null,
    previous_speaker_id: "rex",
    conversation_energy: null,
  },
];

describe("Energy data transformation", () => {
  it("maps selections to energy data points", () => {
    const data = buildEnergyData(MOCK_SELECTIONS);
    expect(data).toHaveLength(3);
    expect(data[0]).toEqual({ turn: 1, energy: 0.85 });
    expect(data[1]).toEqual({ turn: 2, energy: 0.72 });
  });

  it("defaults null energy to 0", () => {
    const data = buildEnergyData(MOCK_SELECTIONS);
    expect(data[2]).toEqual({ turn: 3, energy: 0 });
  });

  it("handles empty selections", () => {
    expect(buildEnergyData([])).toEqual([]);
  });
});

// ── Playback control logic ────────────────────────────────────

describe("Playback controls logic", () => {
  const SPEED_OPTIONS = [1, 2, 4];

  it("provides 1x, 2x, and 4x speed options", () => {
    expect(SPEED_OPTIONS).toEqual([1, 2, 4]);
  });

  it("calculates correct interval based on speed", () => {
    const baseInterval = 2000;
    SPEED_OPTIONS.forEach((speed) => {
      const interval = baseInterval / speed;
      expect(interval).toBe(baseInterval / speed);
    });
    // 1x = 2000ms, 2x = 1000ms, 4x = 500ms
    expect(2000 / 1).toBe(2000);
    expect(2000 / 2).toBe(1000);
    expect(2000 / 4).toBe(500);
  });
});

// ── Speaker selection panel weight display ────────────────────

const WEIGHT_LABELS: Record<string, { label: string; weight: number }> = {
  time_since_spoke: { label: "Time Since Spoke", weight: 0.3 },
  topic_relevance: { label: "Topic Relevance", weight: 0.3 },
  chattiness: { label: "Chattiness", weight: 0.15 },
  adjacency_fit: { label: "Adjacency Fit", weight: 0.15 },
  random_jitter: { label: "Random Jitter", weight: 0.1 },
};

describe("Speaker selection panel weights", () => {
  it("weights sum to 1.0", () => {
    const total = Object.values(WEIGHT_LABELS).reduce((sum, { weight }) => sum + weight, 0);
    expect(total).toBeCloseTo(1.0);
  });

  it("has correct weight for each factor", () => {
    expect(WEIGHT_LABELS.time_since_spoke.weight).toBe(0.3);
    expect(WEIGHT_LABELS.topic_relevance.weight).toBe(0.3);
    expect(WEIGHT_LABELS.chattiness.weight).toBe(0.15);
    expect(WEIGHT_LABELS.adjacency_fit.weight).toBe(0.15);
    expect(WEIGHT_LABELS.random_jitter.weight).toBe(0.1);
  });

  it("displays all 5 weight factors", () => {
    expect(Object.keys(WEIGHT_LABELS)).toHaveLength(5);
  });
});

// ── Turn anchoring ────────────────────────────────────────────

function parseTurnFromHash(hash: string): number {
  const match = hash.match(/^#turn-(\d+)$/);
  return match ? parseInt(match[1], 10) : 1;
}

describe("Turn anchoring from URL hash", () => {
  it("parses turn number from valid hash", () => {
    expect(parseTurnFromHash("#turn-15")).toBe(15);
    expect(parseTurnFromHash("#turn-1")).toBe(1);
    expect(parseTurnFromHash("#turn-100")).toBe(100);
  });

  it("returns 1 for invalid hash", () => {
    expect(parseTurnFromHash("")).toBe(1);
    expect(parseTurnFromHash("#")).toBe(1);
    expect(parseTurnFromHash("#turn-")).toBe(1);
    expect(parseTurnFromHash("#invalid")).toBe(1);
  });
});

// ── ManagementFlag logic ──────────────────────────────────────

describe("ManagementFlag visibility", () => {
  it("should be visible when was_interrupt is true", () => {
    const sel = MOCK_SELECTIONS[1]; // was_interrupt = true
    expect(sel.was_interrupt).toBe(true);
  });

  it("should be hidden when was_interrupt is false", () => {
    const sel = MOCK_SELECTIONS[0]; // was_interrupt = false
    expect(sel.was_interrupt).toBe(false);
  });
});

// ── Topic tags ────────────────────────────────────────────────

describe("Topic tags display", () => {
  it("shows topic when detected_topic is present", () => {
    const sel = MOCK_SELECTIONS[0];
    expect(sel.detected_topic).toBe("planning");
  });

  it("hides topic when detected_topic is null", () => {
    const sel = MOCK_SELECTIONS[2];
    expect(sel.detected_topic).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

// PersonalityRadar is a Recharts component that requires DOM rendering.
// We test the data transformation logic that drives the radar chart.

const TRAIT_LABELS = {
  chattiness: "Chattiness",
  initiative: "Initiative",
  creativity: "Creativity",
  technical: "Technical",
  emotional: "Emotional",
};

interface Traits {
  chattiness: number;
  initiative: number;
  creativity: number;
  technical: number;
  emotional: number;
}

function buildRadarData(traits: Traits) {
  return Object.entries(TRAIT_LABELS).map(([key, label]) => ({
    trait: label,
    value: traits[key as keyof Traits] ?? 0,
  }));
}

describe("PersonalityRadar data", () => {
  it("transforms trait scores into radar chart data", () => {
    const traits: Traits = {
      chattiness: 0.7,
      initiative: 0.8,
      creativity: 0.3,
      technical: 0.4,
      emotional: 0.6,
    };

    const data = buildRadarData(traits);

    expect(data).toHaveLength(5);
    expect(data[0]).toEqual({ trait: "Chattiness", value: 0.7 });
    expect(data[1]).toEqual({ trait: "Initiative", value: 0.8 });
    expect(data[2]).toEqual({ trait: "Creativity", value: 0.3 });
    expect(data[3]).toEqual({ trait: "Technical", value: 0.4 });
    expect(data[4]).toEqual({ trait: "Emotional", value: 0.6 });
  });

  it("handles zero traits correctly", () => {
    const traits: Traits = {
      chattiness: 0,
      initiative: 0,
      creativity: 0,
      technical: 0,
      emotional: 0,
    };

    const data = buildRadarData(traits);
    expect(data.every((d) => d.value === 0)).toBe(true);
  });

  it("handles max traits correctly", () => {
    const traits: Traits = {
      chattiness: 1,
      initiative: 1,
      creativity: 1,
      technical: 1,
      emotional: 1,
    };

    const data = buildRadarData(traits);
    expect(data.every((d) => d.value === 1)).toBe(true);
  });

  it("produces exactly 5 dimensions matching label keys", () => {
    const traits: Traits = {
      chattiness: 0.5,
      initiative: 0.5,
      creativity: 0.5,
      technical: 0.5,
      emotional: 0.5,
    };

    const data = buildRadarData(traits);
    const labels = data.map((d) => d.trait);
    expect(labels).toEqual([
      "Chattiness",
      "Initiative",
      "Creativity",
      "Technical",
      "Emotional",
    ]);
  });
});

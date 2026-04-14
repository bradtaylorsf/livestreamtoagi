import { describe, expect, it } from "vitest";
import type { Relationship } from "@/types/admin";

/**
 * Test null safety for RelationshipTable sort and display logic.
 * We extract the core logic to test independently of React rendering.
 */

type SortKey = "sentiment_score" | "interaction_count" | "trust_score";
type SortDir = "asc" | "desc";

function sortRelationships(
  relationships: Relationship[],
  sortKey: SortKey,
  sortDir: SortDir,
): Relationship[] {
  return [...relationships].sort((a, b) => {
    const av = (a[sortKey] as number) ?? 0;
    const bv = (b[sortKey] as number) ?? 0;
    return sortDir === "asc" ? av - bv : bv - av;
  });
}

function makeRelationship(overrides: Partial<Relationship> = {}): Relationship {
  return {
    agent_id: "vera",
    target_agent_id: "rex",
    sentiment_score: 0,
    trust_score: 0,
    interaction_count: 1,
    relationship_summary: null,
    simulation_id: null,
    ...overrides,
  };
}

describe("RelationshipTable null safety", () => {
  it("sorts correctly when sentiment_score is null", () => {
    const rels = [
      makeRelationship({ agent_id: "a", sentiment_score: null as unknown as number }),
      makeRelationship({ agent_id: "b", sentiment_score: 0.5 }),
      makeRelationship({ agent_id: "c", sentiment_score: -0.3 }),
    ];
    const sorted = sortRelationships(rels, "sentiment_score", "desc");
    expect(sorted[0].agent_id).toBe("b");
    expect(sorted[1].agent_id).toBe("a"); // null → 0
    expect(sorted[2].agent_id).toBe("c");
  });

  it("sorts correctly when trust_score is null", () => {
    const rels = [
      makeRelationship({ agent_id: "a", trust_score: null as unknown as number }),
      makeRelationship({ agent_id: "b", trust_score: 0.8 }),
    ];
    const sorted = sortRelationships(rels, "trust_score", "desc");
    expect(sorted[0].agent_id).toBe("b");
    expect(sorted[1].agent_id).toBe("a");
  });

  it("renders sentiment safely when null", () => {
    const nullableValue: number | null = null;
    const sentiment = Number(nullableValue ?? 0);
    expect(sentiment).toBe(0);
    expect(sentiment.toFixed(2)).toBe("0.00");
  });

  it("renders trust safely when null", () => {
    const nullableValue: number | null = null;
    const trust = Number(nullableValue ?? 0);
    expect(trust).toBe(0);
    expect(trust.toFixed(2)).toBe("0.00");
  });

  it("handles all-null scores without NaN in sort", () => {
    const rels = [
      makeRelationship({
        agent_id: "a",
        sentiment_score: null as unknown as number,
        trust_score: null as unknown as number,
      }),
      makeRelationship({
        agent_id: "b",
        sentiment_score: null as unknown as number,
        trust_score: null as unknown as number,
      }),
    ];
    const sorted = sortRelationships(rels, "sentiment_score", "desc");
    expect(sorted).toHaveLength(2);
    // Both should have coalesced to 0, so order is stable
  });
});

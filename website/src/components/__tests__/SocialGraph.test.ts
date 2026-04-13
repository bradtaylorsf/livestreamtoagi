import { describe, expect, it } from "vitest";
import type { Relationship } from "@/types/admin";

/**
 * Test the edge filtering logic used in SocialGraph.
 * We extract the core filtering logic to test independently of React rendering.
 */

const MIN_INTERACTION_THRESHOLD = 2;

function filterEdges(relationships: Relationship[]): {
  edges: Relationship[];
  filteredCount: number;
} {
  // De-duplicate edges
  const edgeMap = new Map<string, Relationship>();
  for (const r of relationships) {
    const key = [r.agent_id, r.target_agent_id].sort().join("|");
    const existing = edgeMap.get(key);
    if (!existing || r.interaction_count > existing.interaction_count) {
      edgeMap.set(key, r);
    }
  }
  const allEdges = Array.from(edgeMap.values());

  const edges = allEdges.filter(
    (r) =>
      r.interaction_count >= MIN_INTERACTION_THRESHOLD ||
      Math.abs(Number(r.sentiment_score ?? 0)) > 0,
  );
  return { edges, filteredCount: allEdges.length - edges.length };
}

function makeRelationship(
  agentA: string,
  agentB: string,
  overrides: Partial<Relationship> = {},
): Relationship {
  return {
    agent_id: agentA,
    target_agent_id: agentB,
    sentiment_score: 0,
    trust_score: 0,
    interaction_count: 1,
    relationship_summary: null,
    simulation_id: null,
    ...overrides,
  };
}

describe("SocialGraph edge filtering", () => {
  it("filters out edges with single interaction and zero sentiment", () => {
    const rels = [
      makeRelationship("vera", "rex", { interaction_count: 1, sentiment_score: 0 }),
      makeRelationship("vera", "fork", { interaction_count: 5, sentiment_score: 0 }),
    ];
    const { edges, filteredCount } = filterEdges(rels);
    expect(edges).toHaveLength(1);
    expect(edges[0].agent_id).toBe("vera");
    expect(edges[0].target_agent_id).toBe("fork");
    expect(filteredCount).toBe(1);
  });

  it("keeps edges with non-zero sentiment even if low interaction", () => {
    const rels = [
      makeRelationship("vera", "rex", { interaction_count: 1, sentiment_score: 0.5 }),
    ];
    const { edges } = filterEdges(rels);
    expect(edges).toHaveLength(1);
  });

  it("keeps edges with sufficient interaction even if zero sentiment", () => {
    const rels = [
      makeRelationship("vera", "rex", { interaction_count: 3, sentiment_score: 0 }),
    ];
    const { edges } = filterEdges(rels);
    expect(edges).toHaveLength(1);
  });

  it("deduplicates bidirectional edges keeping higher interaction count", () => {
    const rels = [
      makeRelationship("vera", "rex", { interaction_count: 2, sentiment_score: 0.3 }),
      makeRelationship("rex", "vera", { interaction_count: 5, sentiment_score: 0.1 }),
    ];
    const { edges } = filterEdges(rels);
    expect(edges).toHaveLength(1);
    expect(edges[0].interaction_count).toBe(5);
  });

  it("handles negative sentiment keeping the edge visible", () => {
    const rels = [
      makeRelationship("fork", "grok", { interaction_count: 1, sentiment_score: -0.8 }),
    ];
    const { edges } = filterEdges(rels);
    expect(edges).toHaveLength(1);
  });

  it("returns empty when all edges are low-signal", () => {
    const rels = [
      makeRelationship("a", "b", { interaction_count: 1, sentiment_score: 0 }),
      makeRelationship("c", "d", { interaction_count: 1, sentiment_score: 0 }),
    ];
    const { edges, filteredCount } = filterEdges(rels);
    expect(edges).toHaveLength(0);
    expect(filteredCount).toBe(2);
  });
});

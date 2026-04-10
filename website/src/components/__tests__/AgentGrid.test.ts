import { describe, expect, it } from "vitest";
import { getAllAgents, getAgentData, getAllAgentIds } from "@/lib/agent-data";

describe("AgentGrid data", () => {
  it("provides all 9 agents", () => {
    const agents = getAllAgents();
    expect(agents).toHaveLength(9);
  });

  it("includes all expected agent IDs", () => {
    const ids = getAllAgentIds();
    expect(ids).toEqual(
      expect.arrayContaining([
        "vera",
        "rex",
        "aurora",
        "pixel",
        "fork",
        "sentinel",
        "grok",
        "management",
        "alpha",
      ]),
    );
  });

  it("each agent has required fields for card rendering", () => {
    const agents = getAllAgents();
    for (const agent of agents) {
      expect(agent.id).toBeTruthy();
      expect(agent.name).toBeTruthy();
      expect(agent.role).toBeTruthy();
      expect(agent.tagline).toBeTruthy();
      expect(agent.hook).toBeTruthy();
      expect(agent.color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("each agent has personality traits with valid values", () => {
    const agents = getAllAgents();
    for (const agent of agents) {
      const { traits } = agent;
      expect(traits.chattiness).toBeGreaterThanOrEqual(0);
      expect(traits.chattiness).toBeLessThanOrEqual(1);
      expect(traits.initiative).toBeGreaterThanOrEqual(0);
      expect(traits.initiative).toBeLessThanOrEqual(1);
      expect(traits.creativity).toBeGreaterThanOrEqual(0);
      expect(traits.creativity).toBeLessThanOrEqual(1);
      expect(traits.technical).toBeGreaterThanOrEqual(0);
      expect(traits.technical).toBeLessThanOrEqual(1);
      expect(traits.emotional).toBeGreaterThanOrEqual(0);
      expect(traits.emotional).toBeLessThanOrEqual(1);
    }
  });

  it("getAgentData returns correct agent by ID", () => {
    const vera = getAgentData("vera");
    expect(vera).toBeDefined();
    expect(vera!.name).toBe("Vera");
    expect(vera!.role).toBe("Showrunner/Coordinator");
  });

  it("getAgentData returns undefined for unknown ID", () => {
    expect(getAgentData("nonexistent")).toBeUndefined();
  });

  it("each agent links to /agents/{id}", () => {
    const agents = getAllAgents();
    for (const agent of agents) {
      expect(`/agents/${agent.id}`).toMatch(/^\/agents\/[a-z]+$/);
    }
  });
});

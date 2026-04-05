import { describe, it, expect } from "vitest";
import { AGENTS, getAgentById, getAgentIds } from "./agents";

describe("AGENTS", () => {
  it("has 9 agents", () => {
    expect(AGENTS).toHaveLength(9);
  });

  it("all agents have unique ids", () => {
    const ids = AGENTS.map((a) => a.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("all personality values are between 0 and 1", () => {
    for (const agent of AGENTS) {
      expect(agent.chattiness).toBeGreaterThanOrEqual(0);
      expect(agent.chattiness).toBeLessThanOrEqual(1);
      expect(agent.initiative).toBeGreaterThanOrEqual(0);
      expect(agent.initiative).toBeLessThanOrEqual(1);
      expect(agent.interruptTendency).toBeGreaterThanOrEqual(0);
      expect(agent.interruptTendency).toBeLessThanOrEqual(1);
    }
  });

  it("all agents have valid sprite sizes", () => {
    for (const agent of AGENTS) {
      expect([0, 24, 32]).toContain(agent.spriteSize);
    }
  });

  it("alpha has 24x24 sprite size", () => {
    const alpha = AGENTS.find((a) => a.id === "alpha");
    expect(alpha?.spriteSize).toBe(24);
  });

  it("main agents have 32x32 sprite size", () => {
    const mainAgents = AGENTS.filter(
      (a) => a.id !== "alpha" && a.id !== "management",
    );
    for (const agent of mainAgents) {
      expect(agent.spriteSize).toBe(32);
    }
  });
});

describe("getAgentById", () => {
  it("returns the correct agent", () => {
    const rex = getAgentById("rex");
    expect(rex).toBeDefined();
    expect(rex!.name).toBe("Rex");
  });

  it("returns undefined for unknown id", () => {
    expect(getAgentById("nobody")).toBeUndefined();
  });
});

describe("getAgentIds", () => {
  it("returns all 9 ids", () => {
    const ids = getAgentIds();
    expect(ids).toHaveLength(9);
    expect(ids).toContain("vera");
    expect(ids).toContain("alpha");
  });
});

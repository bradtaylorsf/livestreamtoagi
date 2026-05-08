import { readFileSync } from "fs";
import { resolve } from "path";
import { describe, expect, it } from "vitest";

function read(rel: string): string {
  return readFileSync(resolve(__dirname, "..", rel), "utf8");
}

describe("scoped simulation routes", () => {
  it("layout wraps children in SimulationProvider seeded from route id", () => {
    const src = read("simulations/[id]/layout.tsx");
    expect(src).toMatch(/SimulationProvider/);
    expect(src).toMatch(/routeSimulationId={id}/);
  });

  it("scoped agent detail route reuses the existing AgentDetailClient", () => {
    const src = read("simulations/[id]/agents/[agentId]/page.tsx");
    expect(src).toMatch(/AgentDetailClient/);
  });

  it("scoped agents list links into the scoped agent detail route", () => {
    const src = read("simulations/[id]/agents/page.tsx");
    expect(src).toMatch(/\/simulations\/\$\{id\}\/agents\/\$\{agent\.id\}/);
  });

  it("scoped conversations list passes simulation_id to getConversations", () => {
    const src = read("simulations/[id]/conversations/page.tsx");
    expect(src).toMatch(/simulation_id: sim\.simulationId/);
    // The picker is hidden — selectedSim is fixed by the route.
    expect(src).not.toMatch(/<SimulationPicker/);
  });

  it("scoped conversation detail validates simulation_id and notFound()s on mismatch", () => {
    const src = read("simulations/[id]/conversations/[convId]/page.tsx");
    expect(src).toMatch(/data\.simulation_id !== simId/);
    expect(src).toMatch(/notFound\(\)/);
  });

  it("scoped evals page calls getSimulationEvals(id)", () => {
    const src = read("simulations/[id]/evals/page.tsx");
    expect(src).toMatch(/getSimulationEvals\(simId\)/);
  });
});

describe("aggregate views show cross-sim indicator when no sim is selected", () => {
  it("/conversations shows '(across all simulations)' label when no sim is filtered", () => {
    const src = read("conversations/page.tsx");
    expect(src).toMatch(/across all simulations/);
  });

  it("/evals shows '(across all simulations)' label when no sim is filtered", () => {
    const src = read("evals/page.tsx");
    expect(src).toMatch(/across all simulations/);
  });

  it("/agents/[id] shows '(across all simulations)' indicator when no sim is in context", () => {
    const src = read("agents/[id]/AgentDetailClient.tsx");
    expect(src).toMatch(/across all simulations/);
  });
});

describe("/agents/[id] aggregate view wires SimulationProvider but not a route id", () => {
  it("agents/[id]/page.tsx wraps in <SimulationProvider> without routeSimulationId", () => {
    const src = read("agents/[id]/page.tsx");
    expect(src).toMatch(/<SimulationProvider>/);
    expect(src).not.toMatch(/routeSimulationId/);
  });
});

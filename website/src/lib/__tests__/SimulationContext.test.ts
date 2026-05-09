import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("resolveSimulationId precedence", () => {
  let storage: Record<string, string>;

  beforeEach(() => {
    storage = {};
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (k: string) => (k in storage ? storage[k] : null),
        setItem: (k: string, v: string) => {
          storage[k] = v;
        },
        removeItem: (k: string) => {
          delete storage[k];
        },
        clear: () => {
          storage = {};
        },
      },
    });
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("prefers route id over URL query and session", async () => {
    storage.currentSimulationId = "session-sim";
    const { resolveSimulationId } = await import("../SimulationContext");
    const result = resolveSimulationId({
      routeSimulationId: "route-sim",
      urlSim: "url-sim",
    });
    expect(result.simulationId).toBe("route-sim");
    expect(result.source).toBe("route");
  });

  it("falls back to URL query when route id is absent", async () => {
    storage.currentSimulationId = "session-sim";
    const { resolveSimulationId } = await import("../SimulationContext");
    const result = resolveSimulationId({
      routeSimulationId: null,
      urlSim: "url-sim",
    });
    expect(result.simulationId).toBe("url-sim");
    expect(result.source).toBe("url");
  });

  it("falls back to session-store when route+URL are absent", async () => {
    storage.currentSimulationId = "session-sim";
    const { resolveSimulationId } = await import("../SimulationContext");
    const result = resolveSimulationId({
      routeSimulationId: null,
      urlSim: null,
    });
    expect(result.simulationId).toBe("session-sim");
    expect(result.source).toBe("session");
  });

  it("returns null/none when no source has a value", async () => {
    const { resolveSimulationId } = await import("../SimulationContext");
    const result = resolveSimulationId({});
    expect(result.simulationId).toBeNull();
    expect(result.source).toBe("none");
  });

  it("treats empty-string route id as absent (falls back)", async () => {
    storage.currentSimulationId = "session-sim";
    const { resolveSimulationId } = await import("../SimulationContext");
    const result = resolveSimulationId({
      routeSimulationId: "",
      urlSim: null,
    });
    expect(result.simulationId).toBe("session-sim");
    expect(result.source).toBe("session");
  });
});

describe("parseSimIdFromPath", () => {
  it("returns the id for /simulations/<id>", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath("/simulations/abc")).toBe("abc");
  });

  it("returns the id for nested simulation routes", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath("/simulations/abc/agents/rex")).toBe("abc");
    expect(parseSimIdFromPath("/simulations/abc/replay")).toBe("abc");
  });

  it("returns null for the simulations index", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath("/simulations")).toBeNull();
    expect(parseSimIdFromPath("/simulations/")).toBeNull();
  });

  it("returns null for the root path", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath("/")).toBeNull();
  });

  it("returns null for a null pathname", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath(null)).toBeNull();
  });

  it("returns null for unrelated paths", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath("/other/path")).toBeNull();
    expect(parseSimIdFromPath("/agents/rex")).toBeNull();
  });

  it("returns null for known list-page sentinels", async () => {
    const { parseSimIdFromPath } = await import("../SimulationContext");
    expect(parseSimIdFromPath("/simulations/live")).toBeNull();
    expect(parseSimIdFromPath("/simulations/new")).toBeNull();
    expect(parseSimIdFromPath("/simulations/scenarios")).toBeNull();
  });
});

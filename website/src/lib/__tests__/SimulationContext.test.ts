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

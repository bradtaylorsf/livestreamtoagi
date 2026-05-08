import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("simulation-store", () => {
  let storage: Record<string, string>;

  beforeEach(() => {
    storage = {};
    const sessionStorageStub = {
      getItem: (key: string) => (key in storage ? storage[key] : null),
      setItem: (key: string, value: string) => {
        storage[key] = value;
      },
      removeItem: (key: string) => {
        delete storage[key];
      },
      clear: () => {
        storage = {};
      },
    };
    vi.stubGlobal("window", {
      sessionStorage: sessionStorageStub,
    });
    // Reset module state between tests so the in-memory cached value is fresh.
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns null when no simulation is set", async () => {
    const { getCurrentSimulationId } = await import("../simulation-store");
    expect(getCurrentSimulationId()).toBeNull();
  });

  it("persists set values to sessionStorage", async () => {
    const { setCurrentSimulationId, getCurrentSimulationId } = await import(
      "../simulation-store"
    );
    setCurrentSimulationId("sim-123");
    expect(getCurrentSimulationId()).toBe("sim-123");
    expect(storage.currentSimulationId).toBe("sim-123");
  });

  it("hydrates from sessionStorage on first read", async () => {
    storage.currentSimulationId = "preexisting-sim";
    const { getCurrentSimulationId } = await import("../simulation-store");
    expect(getCurrentSimulationId()).toBe("preexisting-sim");
  });

  it("clears sessionStorage when set to null", async () => {
    storage.currentSimulationId = "sim-abc";
    const { setCurrentSimulationId } = await import("../simulation-store");
    setCurrentSimulationId(null);
    expect("currentSimulationId" in storage).toBe(false);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AdminApiError,
  fetchDashboardStats,
  fetchSimulation,
  fetchSimulations,
  fetchSimulationTimeline,
  fetchSimulationCosts,
} from "../admin-api";

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  });
}

const SIM_FIXTURE = {
  id: "abc-123",
  name: "Test Run",
  status: "completed",
  started_at: "2026-04-01T00:00:00Z",
  completed_at: "2026-04-01T01:00:00Z",
  total_conversations: 5,
  total_turns: 42,
  total_tokens: 10000,
  total_cost: "0.1234",
  total_artifacts: 3,
  total_overseer_flags: 1,
  agents_participated: ["vera", "rex"],
  config: {},
};

describe("fetchSimulations", () => {
  it("sends GET to /api/admin/simulations", async () => {
    const paginated = { items: [SIM_FIXTURE], total: 1, limit: 500, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    const result = await fetchSimulations();

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations?limit=500",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(result.items).toHaveLength(1);
    expect(result.items[0].name).toBe("Test Run");
  });

  it("passes status filter as query param", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({ items: [], total: 0, limit: 500, offset: 0 }),
    );

    await fetchSimulations("completed");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations?status=completed&limit=500",
      expect.anything(),
    );
  });
});

describe("fetchSimulation", () => {
  it("sends GET to /api/admin/simulations/:id", async () => {
    mockFetch.mockReturnValue(jsonResponse(SIM_FIXTURE));

    const result = await fetchSimulation("abc-123");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/abc-123",
      expect.anything(),
    );
    expect(result.name).toBe("Test Run");
  });
});

describe("fetchSimulationTimeline", () => {
  it("sends GET to /api/admin/simulations/:id/timeline", async () => {
    const events = [
      { timestamp: "2026-04-01T00:05:00Z", event_type: "phase_transition", details: {} },
    ];
    mockFetch.mockReturnValue(jsonResponse(events));

    const result = await fetchSimulationTimeline("abc-123");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/abc-123/timeline",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
  });

  it("passes agent and event type filters", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));

    await fetchSimulationTimeline("abc-123", "vera", "tool_invocation");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/abc-123/timeline?agent_id=vera&event_type=tool_invocation",
      expect.anything(),
    );
  });
});

describe("fetchSimulationCosts", () => {
  it("sends GET to /api/admin/simulations/:id/costs", async () => {
    const costs = { by_agent: [{ agent_id: "vera", total: "0.05" }], total: "0.05" };
    mockFetch.mockReturnValue(jsonResponse(costs));

    const result = await fetchSimulationCosts("abc-123");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/abc-123/costs",
      expect.anything(),
    );
    expect(result.total).toBe("0.05");
  });
});

describe("fetchDashboardStats", () => {
  it("derives stats from simulations list", async () => {
    const paginated = {
      items: [
        { ...SIM_FIXTURE, total_cost: "0.1000", total_conversations: 3 },
        { ...SIM_FIXTURE, id: "def-456", total_cost: "0.2000", total_conversations: 7 },
      ],
      total: 2,
      limit: 500,
      offset: 0,
    };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    const stats = await fetchDashboardStats();

    expect(stats.total_simulations).toBe(2);
    expect(stats.average_cost).toBe("0.1500");
    expect(stats.total_conversations).toBe(10);
    expect(stats.last_run_date).toBe("2026-04-01T00:00:00Z");
  });
});

describe("error handling", () => {
  it("throws AdminApiError on non-2xx response", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({ detail: "Not Found" }, 404),
    );

    await expect(fetchSimulation("missing")).rejects.toThrow(AdminApiError);
    await expect(fetchSimulation("missing")).rejects.toMatchObject({
      status: 404,
      message: "Not Found",
    });
  });

  it("uses statusText when body parsing fails", async () => {
    mockFetch.mockReturnValue(
      Promise.resolve({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.reject(new Error("no json")),
      }),
    );

    await expect(fetchSimulation("bad")).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });
});

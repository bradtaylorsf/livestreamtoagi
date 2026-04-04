import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AdminApiError,
  fetchDashboardStats,
  fetchSimulation,
  fetchSimulations,
  fetchSimulationTimeline,
  fetchSimulationCosts,
  fetchAgents,
  fetchAgent,
  fetchAgentSystemPrompt,
  fetchAgentCoreMemory,
  fetchAgentRecallMemories,
  fetchAgentConversations,
  fetchAgentArtifacts,
  fetchAgentJournal,
  fetchAgentCosts,
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

// ── Agent API tests ─────────────────────────────────────────────

describe("fetchAgents", () => {
  it("sends GET to /api/admin/agents", async () => {
    const agents = [{ id: "vera", display_name: "Vera" }];
    mockFetch.mockReturnValue(jsonResponse(agents));

    const result = await fetchAgents();

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].display_name).toBe("Vera");
  });
});

describe("fetchAgent", () => {
  it("sends GET to /api/admin/agents/:id", async () => {
    const agent = { id: "vera", display_name: "Vera", role: "Showrunner" };
    mockFetch.mockReturnValue(jsonResponse(agent));

    const result = await fetchAgent("vera");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/vera",
      expect.anything(),
    );
    expect(result.role).toBe("Showrunner");
  });
});

describe("fetchAgentSystemPrompt", () => {
  it("sends GET to /api/admin/agents/:id/system-prompt", async () => {
    const prompt = { assembled_prompt: "test", layers: [], total_tokens: 100 };
    mockFetch.mockReturnValue(jsonResponse(prompt));

    const result = await fetchAgentSystemPrompt("vera");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/vera/system-prompt",
      expect.anything(),
    );
    expect(result.total_tokens).toBe(100);
  });
});

describe("fetchAgentCoreMemory", () => {
  it("sends GET to /api/admin/agents/:id/core-memory", async () => {
    const memory = {
      current_content: "test",
      current_version: 1,
      token_count: 50,
      last_updated: null,
      version_history: [],
    };
    mockFetch.mockReturnValue(jsonResponse(memory));

    const result = await fetchAgentCoreMemory("vera");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/vera/core-memory",
      expect.anything(),
    );
    expect(result.current_version).toBe(1);
  });
});

describe("fetchAgentRecallMemories", () => {
  it("sends GET with search and pagination params", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchAgentRecallMemories("vera", {
      search: "hello",
      offset: 10,
      limit: 20,
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/vera/recall-memories?search=hello&offset=10&limit=20",
      expect.anything(),
    );
  });

  it("sends GET without params when none provided", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchAgentRecallMemories("vera");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/vera/recall-memories",
      expect.anything(),
    );
  });
});

describe("fetchAgentConversations", () => {
  it("sends GET with simulation_id filter", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchAgentConversations("rex", { simulation_id: "sim-1" });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/rex/conversations?simulation_id=sim-1",
      expect.anything(),
    );
  });
});

describe("fetchAgentArtifacts", () => {
  it("sends GET with type and simulation filters", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchAgentArtifacts("aurora", {
      type: "code",
      simulation_id: "sim-1",
      offset: 0,
      limit: 20,
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/aurora/artifacts?type=code&simulation_id=sim-1&offset=0&limit=20",
      expect.anything(),
    );
  });
});

describe("fetchAgentJournal", () => {
  it("sends GET with simulation filter", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchAgentJournal("fork", { simulation_id: "sim-2" });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/fork/journal?simulation_id=sim-2",
      expect.anything(),
    );
  });
});

describe("fetchAgentCosts", () => {
  it("sends GET to /api/admin/agents/:id/costs", async () => {
    const costs = {
      by_day: [],
      by_type: [],
      total: "0.50",
      total_input_tokens: 1000,
      total_output_tokens: 500,
    };
    mockFetch.mockReturnValue(jsonResponse(costs));

    const result = await fetchAgentCosts("sentinel");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/sentinel/costs",
      expect.anything(),
    );
    expect(result.total).toBe("0.50");
  });

  it("passes from/to date filters", async () => {
    const costs = {
      by_day: [],
      by_type: [],
      total: "0",
      total_input_tokens: 0,
      total_output_tokens: 0,
    };
    mockFetch.mockReturnValue(jsonResponse(costs));

    await fetchAgentCosts("sentinel", "2026-04-01", "2026-04-03");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/agents/sentinel/costs?from=2026-04-01&to=2026-04-03",
      expect.anything(),
    );
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

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AdminApiError,
  fetchArtifacts,
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
  fetchConversation,
  fetchConversationTurns,
  fetchConversationSelectionLog,
  fetchConversationManagementFlags,
  fetchConversationInterrupts,
  fetchConversationArtifacts,
  fetchSimulationEvals,
  triggerEvalRun,
  fetchEvalRun,
  fetchAllEvalRuns,
  fetchEvalHistory,
  compareEvals,
  exportEval,
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

// ── Conversation Detail API Tests ──────────────────────────────

describe("fetchConversation", () => {
  it("sends GET to /api/admin/conversations/:id", async () => {
    const conv = {
      id: "conv-123",
      simulation_id: "sim-1",
      started_at: "2026-04-01T12:00:00Z",
      ended_at: "2026-04-01T12:05:00Z",
      trigger_type: "idle",
      trigger_details: null,
      initial_energy: 0.8,
      final_energy: 0.5,
      turn_count: 10,
      participating_agents: ["vera", "rex"],
      topics_discussed: ["architecture"],
      closed_by: "energy_depleted",
      location: "main_hall",
      energy_history: [],
      transcript: "[vera]: Hello",
      total_tokens: 250,
      total_cost: "0",
    };
    mockFetch.mockReturnValue(jsonResponse(conv));

    const result = await fetchConversation("conv-123");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/conversations/conv-123",
      expect.anything(),
    );
    expect(result.id).toBe("conv-123");
    expect(result.turn_count).toBe(10);
    expect(result.participating_agents).toEqual(["vera", "rex"]);
  });
});

describe("fetchConversationTurns", () => {
  it("sends GET to /api/admin/conversations/:id/turns", async () => {
    const turns = [
      {
        turn_number: 1,
        selected_agent_id: "vera",
        was_interrupt: false,
        agent_scores: {},
        detected_topic: null,
        previous_speaker_id: null,
        conversation_energy: 0.8,
        timestamp: null,
      },
    ];
    mockFetch.mockReturnValue(jsonResponse(turns));

    const result = await fetchConversationTurns("conv-123");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/conversations/conv-123/turns",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
    expect(result[0].selected_agent_id).toBe("vera");
  });
});

describe("fetchConversationSelectionLog", () => {
  it("sends GET to /api/admin/conversations/:id/selection-log", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));

    const result = await fetchConversationSelectionLog("conv-456");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/conversations/conv-456/selection-log",
      expect.anything(),
    );
    expect(result).toEqual([]);
  });
});

describe("fetchConversationManagementFlags", () => {
  it("sends GET to /api/admin/conversations/:id/management-flags", async () => {
    const flags = [
      {
        id: "flag-1",
        agent_id: "grok",
        original_content: "bad content",
        filter_layer: 1,
        severity: 3,
        action_would_take: "block",
        reason: "harmful",
        flagged_keywords: ["bad"],
        created_at: "2026-04-01T12:00:00Z",
      },
    ];
    mockFetch.mockReturnValue(jsonResponse(flags));

    const result = await fetchConversationManagementFlags("conv-789");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/conversations/conv-789/management-flags",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
    expect(result[0].severity).toBe(3);
  });
});

describe("fetchConversationInterrupts", () => {
  it("sends GET to /api/admin/conversations/:id/interrupts", async () => {
    const interrupts = [
      {
        id: 1,
        attempting_agent_id: "fork",
        would_have_spoken_id: "vera",
        interrupt_score: 0.85,
        threshold_at_time: 0.7,
        succeeded: true,
        reason: "urgent",
        timestamp: "2026-04-01T12:01:00Z",
      },
    ];
    mockFetch.mockReturnValue(jsonResponse(interrupts));

    const result = await fetchConversationInterrupts("conv-abc");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/conversations/conv-abc/interrupts",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
    expect(result[0].attempting_agent_id).toBe("fork");
    expect(result[0].succeeded).toBe(true);
  });
});

// ── Global Artifact API Tests ────────────────────────────────────

describe("fetchArtifacts", () => {
  it("sends GET to /api/admin/artifacts with no filters", async () => {
    const paginated = { items: [], total: 0, limit: 50, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    const result = await fetchArtifacts();

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/artifacts",
      expect.anything(),
    );
    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
  });

  it("serializes all filter params to query string", async () => {
    const paginated = { items: [], total: 0, limit: 10, offset: 5 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchArtifacts({
      simulation_id: "sim-1",
      agent_ids: ["rex", "fork"],
      types: ["social_post", "email"],
      statuses: ["executed"],
      since: "2026-04-01T00:00:00.000Z",
      until: "2026-04-03T00:00:00.000Z",
      search: "hello",
      sort: "oldest",
      limit: 10,
      offset: 5,
    });

    const calledUrl = mockFetch.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/api/admin/artifacts?");
    expect(calledUrl).toContain("simulation_id=sim-1");
    expect(calledUrl).toContain("agent_id=rex%2Cfork");
    expect(calledUrl).toContain("type=social_post%2Cemail");
    expect(calledUrl).toContain("status=executed");
    expect(calledUrl).toContain("search=hello");
    expect(calledUrl).toContain("sort=oldest");
    expect(calledUrl).toContain("limit=10");
    expect(calledUrl).toContain("offset=5");
  });

  it("omits empty filter params", async () => {
    const paginated = { items: [], total: 0, limit: 50, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await fetchArtifacts({ sort: "newest" });

    const calledUrl = mockFetch.mock.calls[0][0] as string;
    expect(calledUrl).toBe("/api/admin/artifacts?sort=newest");
  });
});

describe("fetchConversationArtifacts", () => {
  it("sends GET to /api/admin/conversations/:id/artifacts", async () => {
    const artifacts = [
      {
        id: "art-1",
        simulation_id: null,
        artifact_type: "code",
        tool_name: "write_file",
        tool_input: { path: "test.py" },
        tool_output: { success: true },
        status: "executed",
        metadata: null,
        created_at: "2026-04-01T12:02:00Z",
      },
    ];
    mockFetch.mockReturnValue(jsonResponse(artifacts));

    const result = await fetchConversationArtifacts("conv-xyz");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/conversations/conv-xyz/artifacts",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
    expect(result[0].tool_name).toBe("write_file");
  });
});


// ── Eval API Tests ──────────────────────────────────────────────

const EVAL_RUN_FIXTURE = {
  id: "eval-001",
  simulation_id: "sim-1",
  eval_suite: "full",
  status: "completed",
  started_at: "2026-04-01T00:00:00Z",
  completed_at: "2026-04-01T00:05:00Z",
  overall_score: 72.5,
  cost: 0.0432,
  created_at: "2026-04-01T00:00:00Z",
  results: [
    {
      id: "res-1",
      eval_run_id: "eval-001",
      category: "entertainment",
      score: 75,
      reasoning: "Good show",
      evidence: { best_moments: ["joke"] },
      sub_scores: { humor: 80, personality: 70 },
      tokens_used: 500,
      cost: "0.01",
      created_at: "2026-04-01T00:01:00Z",
    },
  ],
};

describe("fetchSimulationEvals", () => {
  it("sends GET to /api/admin/simulations/:id/evals", async () => {
    mockFetch.mockReturnValue(jsonResponse([EVAL_RUN_FIXTURE]));

    const result = await fetchSimulationEvals("sim-1");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-1/evals",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
    expect(result[0].overall_score).toBe(72.5);
  });
});

describe("triggerEvalRun", () => {
  it("sends POST with eval_suite in body", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({ eval_run_id: "eval-002", status: "running" }),
    );

    const result = await triggerEvalRun("sim-1", "full");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-1/evals/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ eval_suite: "full" }),
      }),
    );
    expect(result.eval_run_id).toBe("eval-002");
    expect(result.status).toBe("running");
  });

  it("includes categories when provided", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({ eval_run_id: "eval-003", status: "running" }),
    );

    await triggerEvalRun("sim-1", "custom", ["entertainment", "safety"]);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-1/evals/run",
      expect.objectContaining({
        body: JSON.stringify({
          eval_suite: "custom",
          categories: ["entertainment", "safety"],
        }),
      }),
    );
  });
});

describe("fetchEvalRun", () => {
  it("sends GET to /api/admin/evals/:id", async () => {
    mockFetch.mockReturnValue(jsonResponse(EVAL_RUN_FIXTURE));

    const result = await fetchEvalRun("eval-001");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/evals/eval-001",
      expect.anything(),
    );
    expect(result.eval_suite).toBe("full");
  });
});

describe("fetchAllEvalRuns", () => {
  it("sends GET to /api/admin/evals with pagination", async () => {
    mockFetch.mockReturnValue(jsonResponse([EVAL_RUN_FIXTURE]));

    const result = await fetchAllEvalRuns(10, 5);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/evals?limit=10&offset=5",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
  });

  it("uses default pagination when no args", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));

    await fetchAllEvalRuns();

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/evals?limit=50&offset=0",
      expect.anything(),
    );
  });
});

describe("fetchEvalHistory", () => {
  it("sends GET to /api/admin/evals/history with category", async () => {
    const points = [
      { score: 75, created_at: "2026-04-01T00:00:00Z", simulation_id: "sim-1", eval_run_id: "eval-001" },
    ];
    mockFetch.mockReturnValue(jsonResponse(points));

    const result = await fetchEvalHistory("entertainment");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/evals/history?category=entertainment",
      expect.anything(),
    );
    expect(result).toHaveLength(1);
    expect(result[0].score).toBe(75);
  });
});

describe("compareEvals", () => {
  it("sends GET to /api/admin/evals/compare with two run IDs", async () => {
    const comparison = {
      run_a: { ...EVAL_RUN_FIXTURE, id: "eval-001" },
      run_b: { ...EVAL_RUN_FIXTURE, id: "eval-002", overall_score: 80 },
    };
    mockFetch.mockReturnValue(jsonResponse(comparison));

    const result = await compareEvals("eval-001", "eval-002");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/evals/compare?run_a=eval-001&run_b=eval-002",
      expect.anything(),
    );
    expect(result.run_a.id).toBe("eval-001");
    expect(result.run_b.overall_score).toBe(80);
  });
});

describe("exportEval", () => {
  it("sends GET to /api/admin/evals/:id/export", async () => {
    const exported = { eval_run: EVAL_RUN_FIXTURE, exported_at: "2026-04-01T00:10:00Z" };
    mockFetch.mockReturnValue(jsonResponse(exported));

    const result = await exportEval("eval-001");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/evals/eval-001/export",
      expect.anything(),
    );
    expect(result).toHaveProperty("eval_run");
    expect(result).toHaveProperty("exported_at");
  });
});

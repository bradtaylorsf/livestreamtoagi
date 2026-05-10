import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  chatWithAgent,
  cloneSimulationFromSnapshot,
  createSimulation,
  getAgents,
  getAgentArtifacts,
  getAgentConversations,
  getAgentEvolution,
  getAgentJournal,
  getAgentRelationships,
  getChallenges,
  getClips,
  getConversation,
  getConversations,
  getConversationSelections,
  getLore,
  getPublicScenarios,
  getScenarios,
  getSimulationSnapshot,
  getStats,
  getWorldChunks,
  requestMagicLink,
  runSimulationEval,
  shareSimulationAsChallenge,
  submitPublicSimulation,
  upvoteChallenge,
} from "../api";

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

describe("getAgents", () => {
  it("sends GET request to /api/agents", async () => {
    const agents = [{ id: "vera", name: "Vera" }];
    mockFetch.mockReturnValue(jsonResponse(agents));

    const result = await getAgents();

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
    expect(result).toEqual(agents);
  });
});

describe("getAgentJournal", () => {
  it("sends GET request to /api/agents/:id/journal", async () => {
    const entries = [{ id: "1", content: "Day 1" }];
    mockFetch.mockReturnValue(jsonResponse(entries));

    const result = await getAgentJournal("vera");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/vera/journal",
      expect.anything(),
    );
    expect(result).toEqual(entries);
  });
});

describe("chatWithAgent", () => {
  it("sends POST request with message body", async () => {
    const response = { agent_id: "rex", message: "Hello!", timestamp: "now" };
    mockFetch.mockReturnValue(jsonResponse(response));

    const result = await chatWithAgent("rex", "Hi Rex");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/rex/chat",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ message: "Hi Rex" }),
      }),
    );
    expect(result).toEqual(response);
  });
});

describe("getWorldChunks", () => {
  it("sends GET to /api/world/chunks", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getWorldChunks();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/world/chunks",
      expect.anything(),
    );
  });
});

describe("getChallenges", () => {
  it("sends GET to /api/challenges", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getChallenges();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/challenges",
      expect.anything(),
    );
  });
});

describe("shareSimulationAsChallenge", () => {
  it("sends POST to /api/simulations/:id/share-as-challenge with body", async () => {
    const body = { description: "Try a garden", tags: ["creative"] };
    mockFetch.mockReturnValue(jsonResponse({ id: 1, ...body }));

    await shareSimulationAsChallenge("sim-123", body);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/simulations/sim-123/share-as-challenge",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
  });
});

describe("upvoteChallenge", () => {
  it("sends POST to /api/challenges/:id/upvote", async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1, votes: 1 }));
    await upvoteChallenge(1);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/challenges/1/upvote",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("getChallenges with filters", () => {
  it("appends query params for tag and sort", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getChallenges({ tag: "creative", sort: "most_upvoted" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/challenges?tag=creative&sort=most_upvoted",
      expect.anything(),
    );
  });
});

describe("getStats", () => {
  it("sends GET to /api/stats", async () => {
    const statsData = { total_simulations: 10, total_agents: 9, total_cost: "1.23", total_conversations: 42 };
    mockFetch.mockReturnValue(jsonResponse(statsData));
    const result = await getStats();
    expect(result).toEqual(statsData);
  });
});

describe("getLore", () => {
  it("sends GET to /api/lore", async () => {
    mockFetch.mockReturnValue(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
    await getLore();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/lore",
      expect.anything(),
    );
  });

  it("passes filter params", async () => {
    mockFetch.mockReturnValue(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
    await getLore({ agent: "vera", event_type: "discovery" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/lore?agent=vera&event_type=discovery",
      expect.anything(),
    );
  });

  it("forwards simulation_id when provided", async () => {
    mockFetch.mockReturnValue(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));
    await getLore({ simulation_id: "sim-abc" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/lore?simulation_id=sim-abc",
      expect.anything(),
    );
  });
});

describe("getConversations", () => {
  it("sends GET to /api/conversations", async () => {
    mockFetch.mockReturnValue(jsonResponse({ items: [], total: 0, limit: 20, offset: 0 }));
    await getConversations();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/conversations",
      expect.anything(),
    );
  });

  it("forwards simulation_id query param when provided", async () => {
    mockFetch.mockReturnValue(jsonResponse({ items: [], total: 0, limit: 20, offset: 0 }));
    await getConversations({ simulation_id: "sim-123", limit: 10 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/conversations?simulation_id=sim-123&limit=10",
      expect.anything(),
    );
  });
});

describe("getConversation", () => {
  it("sends GET to /api/conversations/:id", async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: "abc", trigger_type: "idle" }));
    await getConversation("abc");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/conversations/abc",
      expect.anything(),
    );
  });
});

describe("getConversationSelections", () => {
  it("sends GET to /api/conversations/:id/selections", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getConversationSelections("abc");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/conversations/abc/selections",
      expect.anything(),
    );
  });
});

describe("getAgentRelationships", () => {
  it("sends GET to /api/agents/:id/relationships", async () => {
    const rels = [{ id: "1", target_agent_id: "rex", sentiment_score: 0.7 }];
    mockFetch.mockReturnValue(jsonResponse(rels));

    const result = await getAgentRelationships("vera");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/vera/relationships",
      expect.anything(),
    );
    expect(result).toEqual(rels);
  });
});

describe("getAgentConversations", () => {
  it("sends GET to /api/agents/:id/conversations with pagination", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await getAgentConversations("vera", { limit: 10, offset: 5 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/vera/conversations?limit=10&offset=5",
      expect.anything(),
    );
  });

  it("sends GET without params when none provided", async () => {
    mockFetch.mockReturnValue(jsonResponse({ items: [], total: 0, limit: 20, offset: 0 }));

    await getAgentConversations("vera");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/vera/conversations",
      expect.anything(),
    );
  });
});


describe("getClips", () => {
  it("sends GET request to /api/clips", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getClips();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/clips",
      expect.anything(),
    );
  });

  it("sends agent and category query params", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getClips({ agent: "vera", category: "funny" });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/clips?agent=vera&category=funny",
      expect.anything(),
    );
  });
});

describe("getAgentArtifacts", () => {
  it("sends GET to /api/agents/:id/artifacts with pagination", async () => {
    const paginated = { items: [], total: 0, limit: 20, offset: 0 };
    mockFetch.mockReturnValue(jsonResponse(paginated));

    await getAgentArtifacts("rex", { limit: 5, offset: 10 });
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/rex/artifacts?limit=5&offset=10",
      expect.anything(),
    );
  });
});

describe("getAgentEvolution", () => {
  it("sends GET to /api/agents/:id/evolution", async () => {
    const events = [{ id: "1", version: 1, source: "system" }];
    mockFetch.mockReturnValue(jsonResponse(events));

    const result = await getAgentEvolution("fork");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/fork/evolution",
      expect.anything(),
    );
    expect(result).toEqual(events);
  });
});

describe("getScenarios", () => {
  it("sends GET to /api/admin/scenarios and returns the list", async () => {
    const scenarios = [
      { filename: "smoke.yaml", name: "smoke", description: "Smoke test" },
    ];
    mockFetch.mockReturnValue(jsonResponse(scenarios));

    const result = await getScenarios();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/scenarios",
      expect.anything(),
    );
    expect(result).toEqual(scenarios);
  });
});

describe("getPublicScenarios", () => {
  it("sends GET to /api/scenarios and returns the structured meta list", async () => {
    const scenarios = [
      {
        filename: "awakening.yaml",
        name: "Awakening (Day 1)",
        description: "Day 1 blank-slate.",
        agents: ["vera", "rex"],
        phase_count: 9,
        expected_max_cost: 10,
        expected_runtime_minutes: 25,
      },
    ];
    mockFetch.mockReturnValue(jsonResponse(scenarios));

    const result = await getPublicScenarios();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/scenarios",
      expect.anything(),
    );
    expect(result).toEqual(scenarios);
  });
});

describe("requestMagicLink", () => {
  it("sends a safe same-site return path with the magic-link request", async () => {
    mockFetch.mockReturnValue(jsonResponse({ status: "ok" }));

    await requestMagicLink(
      "alice@example.com",
      "/simulations/new?scenario=lab_rivals.yaml",
    );

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/auth/magic-link",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          email: "alice@example.com",
          next: "/simulations/new?scenario=lab_rivals.yaml",
        }),
      }),
    );
  });

  it("omits unsafe return paths from the magic-link request", async () => {
    mockFetch.mockReturnValue(jsonResponse({ status: "ok" }));

    await requestMagicLink("alice@example.com", "https://evil.test/phish");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/auth/magic-link",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "alice@example.com" }),
      }),
    );
  });
});

describe("createSimulation", () => {
  it("POSTs the seed_file + max_cost body to /api/admin/simulations", async () => {
    const response = {
      simulation_id: "sim-123",
      name: "dashboard-smoke-x",
      status: "running",
    };
    mockFetch.mockReturnValue(jsonResponse(response));

    const result = await createSimulation({
      seed_file: "smoke.yaml",
      max_cost: 1.5,
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ seed_file: "smoke.yaml", max_cost: 1.5 }),
      }),
    );
    expect(result).toEqual(response);
  });
});


describe("runSimulationEval", () => {
  it("POSTs categories body to /api/admin/simulations/:id/evals/run", async () => {
    const response = { eval_run_id: "eval-123", status: "running" };
    mockFetch.mockReturnValue(jsonResponse(response));

    const result = await runSimulationEval("sim-abc", {
      categories: ["creativity"],
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-abc/evals/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ categories: ["creativity"] }),
      }),
    );
    expect(result).toEqual(response);
  });

  it("POSTs an empty body when no options provided", async () => {
    mockFetch.mockReturnValue(jsonResponse({ eval_run_id: "x", status: "running" }));
    await runSimulationEval("sim-abc");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-abc/evals/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
  });
});

describe("getSimulationSnapshot", () => {
  it("sends GET to /api/admin/simulations/:id/snapshots/:filename", async () => {
    const data = { snapshot_at: "2026-05-07", agents: {} };
    mockFetch.mockReturnValue(jsonResponse(data));

    const result = await getSimulationSnapshot("sim-123", "mature.json");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-123/snapshots/mature.json",
      expect.anything(),
    );
    expect(result).toEqual(data);
  });

  it("URL-encodes the filename component", async () => {
    mockFetch.mockReturnValue(jsonResponse({}));
    await getSimulationSnapshot("sim-123", "snap with spaces.json");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-123/snapshots/snap%20with%20spaces.json",
      expect.anything(),
    );
  });
});

describe("submitPublicSimulation", () => {
  it("sends the selected scenario payload to /api/simulations/submit", async () => {
    const response = {
      simulation_id: "sim-123",
      status_url: "/api/simulations/sim-123",
      estimated_completion_time: "2026-05-10T00:00:00Z",
    };
    const body = {
      scenario_id: "awakening.yaml",
      name: "small cast",
      params: {
        agents: ["vera", "rex", "aurora", "pixel"],
        excluded_agents: ["grok"],
        factions: [
          {
            name: "artists",
            members: ["aurora", "pixel"],
            goal: "make the show vivid",
          },
        ],
        memory_seed: { mode: "none" as const },
        energy: { vera: 80, rex: 60, aurora: 90, pixel: 75 },
        conversation_cadence: 1.25,
        max_cost: 0.5,
      },
    };
    mockFetch.mockReturnValue(jsonResponse(response));

    const result = await submitPublicSimulation(body);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/simulations/submit",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(body),
      }),
    );
    expect(result).toEqual(response);
  });
});

describe("cloneSimulationFromSnapshot", () => {
  it("POSTs to /api/admin/simulations/:id/clone with body", async () => {
    const response = {
      simulation_id: "sim-new",
      name: "clone-x",
      source_simulation_id: "sim-123",
      restore_result: {},
    };
    mockFetch.mockReturnValue(jsonResponse(response));

    const result = await cloneSimulationFromSnapshot("sim-123");

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-123/clone",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({}),
      }),
    );
    expect(result).toEqual(response);
  });

  it("forwards optional name + agents in body", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({
        simulation_id: "sim-new",
        name: "my-clone",
        source_simulation_id: "sim-123",
        restore_result: {},
      }),
    );

    await cloneSimulationFromSnapshot("sim-123", {
      name: "my-clone",
      agents: ["vera"],
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/admin/simulations/sim-123/clone",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "my-clone", agents: ["vera"] }),
      }),
    );
  });
});

describe("error handling", () => {
  it("throws ApiRequestError on non-2xx response", async () => {
    mockFetch.mockReturnValue(
      jsonResponse({ message: "Not Found" }, 404),
    );

    await expect(getAgents()).rejects.toThrow(ApiRequestError);
    await expect(getAgents()).rejects.toMatchObject({
      status: 404,
      message: "Not Found",
    });
  });

  it("uses statusText when body has no message", async () => {
    mockFetch.mockReturnValue(
      Promise.resolve({
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        json: () => Promise.reject(new Error("no json")),
      }),
    );

    await expect(getAgents()).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });
});

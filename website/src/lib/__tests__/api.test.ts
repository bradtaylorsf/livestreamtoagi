import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  BASE_URL,
  chatWithAgent,
  getAgents,
  getAgentJournal,
  getChallenges,
  getLore,
  getStats,
  getWorldChunks,
  submitChallenge,
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

describe("BASE_URL", () => {
  it("defaults to localhost:8000", () => {
    expect(BASE_URL).toBe("http://localhost:8000");
  });
});

describe("getAgents", () => {
  it("sends GET request to /api/agents", async () => {
    const agents = [{ id: "vera", name: "Vera" }];
    mockFetch.mockReturnValue(jsonResponse(agents));

    const result = await getAgents();

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/agents",
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
      "http://localhost:8000/api/agents/vera/journal",
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
      "http://localhost:8000/api/agents/rex/chat",
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
      "http://localhost:8000/api/world/chunks",
      expect.anything(),
    );
  });
});

describe("getChallenges", () => {
  it("sends GET to /api/challenges", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getChallenges();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/challenges",
      expect.anything(),
    );
  });
});

describe("submitChallenge", () => {
  it("sends POST to /api/challenges with body", async () => {
    const challenge = { title: "Test", description: "A test challenge" };
    mockFetch.mockReturnValue(jsonResponse({ ...challenge, id: "1" }));

    await submitChallenge(challenge);

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/challenges",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(challenge),
      }),
    );
  });
});

describe("getStats", () => {
  it("sends GET to /api/stats", async () => {
    mockFetch.mockReturnValue(jsonResponse({ viewers: 42 }));
    const result = await getStats();
    expect(result).toEqual({ viewers: 42 });
  });
});

describe("getLore", () => {
  it("sends GET to /api/lore", async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await getLore();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/lore",
      expect.anything(),
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

import type {
  Agent,
  AgentArtifactResponse,
  AgentConversation,
  AgentEvolutionResponse,
  AgentRelationshipResponse,
  ApiError,
  Challenge,
  ChallengeSubmission,
  ChatResponse,
  Clip,
  ConversationDetail,
  ConversationSummary,
  JournalEntry,
  LoreEvent,
  PaginatedResponse,
  SelectionLogEntry,
  Stats,
  WorldChunk,
} from "@/types";

const DEFAULT_TIMEOUT_MS = 10_000;
const MAX_RETRIES = 2;

class ApiRequestError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

function isRetryable(error: unknown): boolean {
  if (error instanceof ApiRequestError) {
    return error.status >= 500;
  }
  // Retry on network errors (TypeError from fetch) and abort timeouts
  return error instanceof TypeError || (error instanceof DOMException && error.name === "AbortError");
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      // Exponential backoff: 1s, 2s
      await sleep(1000 * attempt);
    }

    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      DEFAULT_TIMEOUT_MS,
    );

    try {
      const response = await fetch(path, {
        ...options,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...options.headers,
        },
      });

      if (!response.ok) {
        let message = response.statusText;
        try {
          const body = (await response.json()) as ApiError;
          message = body.message || message;
        } catch {
          // Use statusText as fallback
        }
        throw new ApiRequestError(response.status, message);
      }

      return (await response.json()) as T;
    } catch (error) {
      lastError = error;
      if (!isRetryable(error) || attempt === MAX_RETRIES) {
        throw error;
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError;
}

// Agents
export async function getAgents(): Promise<Agent[]> {
  return request<Agent[]>("/api/agents");
}

export async function getAgentJournal(
  id: string,
): Promise<JournalEntry[]> {
  return request<JournalEntry[]>(`/api/agents/${id}/journal`);
}

export async function getAgentRelationships(
  id: string,
): Promise<AgentRelationshipResponse[]> {
  return request<AgentRelationshipResponse[]>(
    `/api/agents/${id}/relationships`,
  );
}

export async function getAgentConversations(
  id: string,
  params?: { limit?: number; offset?: number },
): Promise<PaginatedResponse<AgentConversation>> {
  const searchParams = new URLSearchParams();
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<AgentConversation>>(
    `/api/agents/${id}/conversations${qs ? `?${qs}` : ""}`,
  );
}

export async function getAgentArtifacts(
  id: string,
  params?: { limit?: number; offset?: number },
): Promise<PaginatedResponse<AgentArtifactResponse>> {
  const searchParams = new URLSearchParams();
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<AgentArtifactResponse>>(
    `/api/agents/${id}/artifacts${qs ? `?${qs}` : ""}`,
  );
}

export async function getAgentEvolution(
  id: string,
): Promise<AgentEvolutionResponse[]> {
  return request<AgentEvolutionResponse[]>(`/api/agents/${id}/evolution`);
}

export async function chatWithAgent(
  id: string,
  message: string,
): Promise<ChatResponse> {
  return request<ChatResponse>(`/api/agents/${id}/chat`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

// World
export async function getWorldChunks(): Promise<WorldChunk[]> {
  return request<WorldChunk[]>("/api/world/chunks");
}

// Challenges
export async function getChallenges(params?: {
  status?: string;
  category?: string;
  sort?: string;
}): Promise<Challenge[]> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  if (params?.category) searchParams.set("category", params.category);
  if (params?.sort) searchParams.set("sort", params.sort);
  const qs = searchParams.toString();
  return request<Challenge[]>(`/api/challenges${qs ? `?${qs}` : ""}`);
}

export async function submitChallenge(
  challenge: ChallengeSubmission,
): Promise<Challenge> {
  return request<Challenge>("/api/challenges", {
    method: "POST",
    body: JSON.stringify(challenge),
  });
}

export async function upvoteChallenge(id: number): Promise<Challenge> {
  return request<Challenge>(`/api/challenges/${id}/upvote`, {
    method: "POST",
  });
}

// Stats
export async function getStats(): Promise<Stats> {
  return request<Stats>("/api/stats");
}

// Lore
export async function getLore(params?: {
  limit?: number;
  offset?: number;
  agent?: string;
  event_type?: string;
}): Promise<PaginatedResponse<LoreEvent>> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  if (params?.agent) searchParams.set("agent", params.agent);
  if (params?.event_type) searchParams.set("event_type", params.event_type);
  const qs = searchParams.toString();
  return request<PaginatedResponse<LoreEvent>>(`/api/lore${qs ? `?${qs}` : ""}`);
}

// Conversations
export async function getConversations(params?: {
  limit?: number;
  offset?: number;
}): Promise<PaginatedResponse<ConversationSummary>> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<ConversationSummary>>(
    `/api/conversations${qs ? `?${qs}` : ""}`,
  );
}

export async function getConversation(
  id: string,
): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/conversations/${id}`);
}

export async function getConversationSelections(
  id: string,
): Promise<SelectionLogEntry[]> {
  return request<SelectionLogEntry[]>(`/api/conversations/${id}/selections`);
}

// Evals (public read-only)
export interface PublicEvalRun {
  id: string;
  simulation_id: string;
  date: string;
  overall_score: number | null;
  cost: number;
  model_versions: Record<string, string>;
  category_scores: Record<string, number | null>;
  results?: { category: string; score: number | null }[];
}

export interface EvalHistoryPoint {
  score: number | null;
  created_at: string | null;
}

export async function getEvalCategories(): Promise<string[]> {
  return request<string[]>("/api/evals/categories");
}

export async function getEvalHistory(
  category: string,
): Promise<EvalHistoryPoint[]> {
  return request<EvalHistoryPoint[]>(
    `/api/evals/history?category=${encodeURIComponent(category)}`,
  );
}

export async function getLatestEvalRun(): Promise<PublicEvalRun | null> {
  try {
    return await request<PublicEvalRun>("/api/evals/latest");
  } catch {
    return null;
  }
}

export async function getEvalRuns(
  limit = 20,
  offset = 0,
): Promise<PublicEvalRun[]> {
  return request<PublicEvalRun[]>(
    `/api/evals/runs?limit=${limit}&offset=${offset}`,
  );
}

export async function getEvalRunDetail(
  id: string,
): Promise<PublicEvalRun | null> {
  try {
    return await request<PublicEvalRun>(`/api/evals/runs/${id}`);
  } catch {
    return null;
  }
}

// Clips
export async function getClips(params?: {
  agent?: string;
  category?: string;
}): Promise<Clip[]> {
  const searchParams = new URLSearchParams();
  if (params?.agent) searchParams.set("agent", params.agent);
  if (params?.category) searchParams.set("category", params.category);
  const qs = searchParams.toString();
  return request<Clip[]>(`/api/clips${qs ? `?${qs}` : ""}`);
}

export { ApiRequestError };

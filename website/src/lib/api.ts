import type {
  Agent,
  ApiError,
  Challenge,
  ChallengeSubmission,
  ChatResponse,
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

class ApiRequestError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
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
  } finally {
    clearTimeout(timeout);
  }
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

export { ApiRequestError };

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
  CoreMemoryPublic,
  JournalEntry,
  LoreEvent,
  PaginatedResponse,
  RecallMemoryPublic,
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
  params?: { simulation_id?: string; limit?: number; offset?: number },
): Promise<JournalEntry[]> {
  const searchParams = new URLSearchParams();
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<JournalEntry[]>(`/api/agents/${id}/journal${qs ? `?${qs}` : ""}`);
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
  params?: { simulation_id?: string; limit?: number; offset?: number },
): Promise<PaginatedResponse<AgentConversation>> {
  const searchParams = new URLSearchParams();
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<AgentConversation>>(
    `/api/agents/${id}/conversations${qs ? `?${qs}` : ""}`,
  );
}

export async function getAgentArtifacts(
  id: string,
  params?: { type?: string; simulation_id?: string; limit?: number; offset?: number },
): Promise<PaginatedResponse<AgentArtifactResponse>> {
  const searchParams = new URLSearchParams();
  if (params?.type) searchParams.set("type", params.type);
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<AgentArtifactResponse>>(
    `/api/agents/${id}/artifacts${qs ? `?${qs}` : ""}`,
  );
}

export async function getAgentCoreMemory(
  id: string,
): Promise<CoreMemoryPublic> {
  return request<CoreMemoryPublic>(`/api/agents/${id}/core-memory`);
}

export async function getAgentRecallMemories(
  id: string,
  params?: { search?: string; simulation_id?: string; limit?: number; offset?: number },
): Promise<PaginatedResponse<RecallMemoryPublic>> {
  const searchParams = new URLSearchParams();
  if (params?.search) searchParams.set("search", params.search);
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<RecallMemoryPublic>>(
    `/api/agents/${id}/recall-memories${qs ? `?${qs}` : ""}`,
  );
}

export async function getAgentEvolution(
  id: string,
): Promise<AgentEvolutionResponse[]> {
  return request<AgentEvolutionResponse[]>(`/api/agents/${id}/evolution`);
}

// Agent system prompt
export interface SystemPromptLayer {
  name: string;
  content: string;
  token_count: number;
}

export interface SystemPromptResponse {
  assembled_prompt: string;
  layers: SystemPromptLayer[];
  total_tokens: number;
}

export async function getAgentSystemPrompt(
  id: string,
): Promise<SystemPromptResponse> {
  return request<SystemPromptResponse>(`/api/agents/${id}/system-prompt`);
}

// Agent costs
export interface CostByDay {
  date: string;
  cost: string;
}

export interface CostByType {
  type: string;
  cost: string;
  tokens: number;
}

export interface AgentCostBreakdown {
  by_day: CostByDay[];
  by_type: CostByType[];
  total: string;
  total_input_tokens: number;
  total_output_tokens: number;
}

export async function getAgentCosts(
  id: string,
  params?: { from?: string; to?: string },
): Promise<AgentCostBreakdown> {
  const searchParams = new URLSearchParams();
  if (params?.from) searchParams.set("from", params.from);
  if (params?.to) searchParams.set("to", params.to);
  const qs = searchParams.toString();
  return request<AgentCostBreakdown>(
    `/api/agents/${id}/costs${qs ? `?${qs}` : ""}`,
  );
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
  simulation_id?: string;
  limit?: number;
  offset?: number;
}): Promise<PaginatedResponse<ConversationSummary>> {
  const searchParams = new URLSearchParams();
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
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

export interface TurnDetail {
  turn_number: number;
  selected_agent_id: string;
  was_interrupt: boolean;
  agent_scores: Record<string, Record<string, number>>;
  detected_topic: string | null;
  previous_speaker_id: string | null;
  conversation_energy: number | null;
  timestamp: string | null;
}

export async function getConversationTurns(
  id: string,
): Promise<TurnDetail[]> {
  return request<TurnDetail[]>(`/api/conversations/${id}/turns`);
}

export async function getConversationManagementFlags(
  id: string,
): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>(`/api/conversations/${id}/management-flags`);
}

export async function getConversationArtifacts(
  id: string,
): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>(`/api/conversations/${id}/artifacts`);
}

export async function getConversationInterrupts(
  id: string,
): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>(`/api/conversations/${id}/interrupts`);
}

// Eval prompts
export interface EvalPrompt {
  name: string;
  description: string;
  system: string;
  rubric: Record<string, string>;
  sub_scores: (string | Record<string, string>)[];
  output_schema: Record<string, unknown>;
  model: string;
  temperature: number | null;
  max_tokens: number | null;
}

export async function getEvalPrompts(): Promise<EvalPrompt[]> {
  return request<EvalPrompt[]>("/api/evals/prompts");
}

// Evals (public read-only)
export interface PublicEvalRun {
  id: string;
  simulation_id: string;
  simulation_name: string | null;
  date: string;
  overall_score: number | null;
  cost: number;
  model_versions: Record<string, string>;
  category_scores: Record<string, number | null>;
  status?: string;
  results?: { category: string; score: number | null }[];
}

import type { EvalHistoryPoint } from "@/types";
export type { EvalHistoryPoint };

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

export async function getLatestEvalRun(
  params?: { simulation_id?: string },
): Promise<PublicEvalRun | null> {
  const searchParams = new URLSearchParams();
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
  const qs = searchParams.toString();
  try {
    return await request<PublicEvalRun>(
      `/api/evals/latest${qs ? `?${qs}` : ""}`,
    );
  } catch {
    return null;
  }
}

export async function getEvalRuns(
  params?: { limit?: number; offset?: number; simulation_id?: string },
): Promise<PublicEvalRun[]> {
  const searchParams = new URLSearchParams();
  searchParams.set("limit", String(params?.limit ?? 20));
  searchParams.set("offset", String(params?.offset ?? 0));
  if (params?.simulation_id) searchParams.set("simulation_id", params.simulation_id);
  return request<PublicEvalRun[]>(
    `/api/evals/runs?${searchParams.toString()}`,
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

// Admin: trigger an eval run for a simulation
export interface RunSimulationEvalBody {
  eval_suite?: string;
  categories?: string[];
}

export interface RunSimulationEvalResponse {
  eval_run_id: string;
  status: string;
}

export async function runSimulationEval(
  simId: string,
  body: RunSimulationEvalBody = {},
): Promise<RunSimulationEvalResponse> {
  return request<RunSimulationEvalResponse>(
    `/api/admin/simulations/${simId}/evals/run`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
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

// Simulations (public read-only)
export interface PublicSimulation {
  id: string;
  name: string;
  description: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  real_duration: string | null;
  total_conversations: number;
  total_turns: number;
  total_cost: string;
  total_artifacts: number;
  agents_participated: string[];
}

export interface PublicSimulationDetail extends PublicSimulation {
  config: Record<string, unknown>;
  simulated_duration: string | null;
  total_tokens: number;
  total_management_flags: number;
}

export async function getSimulations(
  params?: { status?: string; limit?: number; offset?: number },
): Promise<PaginatedResponse<PublicSimulation>> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set("status", params.status);
  searchParams.set("limit", String(params?.limit ?? 20));
  searchParams.set("offset", String(params?.offset ?? 0));
  return request<PaginatedResponse<PublicSimulation>>(
    `/api/simulations?${searchParams.toString()}`,
  );
}

export async function getSimulation(
  id: string,
): Promise<PublicSimulationDetail> {
  return request<PublicSimulationDetail>(`/api/simulations/${id}`);
}

// Scenarios + simulation launcher (admin)
export interface ScenarioInfo {
  filename: string;
  name: string;
  description: string | null;
}

export async function getScenarios(): Promise<ScenarioInfo[]> {
  return request<ScenarioInfo[]>("/api/admin/scenarios");
}

export interface CreateSimulationRequest {
  seed_file: string;
  max_cost?: number;
  name?: string;
}

export interface CreateSimulationResponse {
  simulation_id: string;
  name: string;
  status: string;
}

export async function createSimulation(
  body: CreateSimulationRequest,
): Promise<CreateSimulationResponse> {
  return request<CreateSimulationResponse>("/api/admin/simulations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getSimulationReport(
  id: string,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/simulations/${id}/report`);
}

export async function getSimulationAssertions(
  id: string,
): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>(
    `/api/simulations/${id}/assertions`,
  );
}

export async function getSimulationAssertionsSummary(
  id: string,
): Promise<{ passed: number; failed: number; warnings: number }> {
  return request<{ passed: number; failed: number; warnings: number }>(
    `/api/simulations/${id}/assertions/summary`,
  );
}

export interface SimulationEvalResult {
  category: string;
  score: number | null;
  reasoning: string | null;
}

export interface SimulationEvalRun {
  id: string;
  simulation_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  overall_score: number | null;
  cost: number;
  results: SimulationEvalResult[];
}

export async function getSimulationEvals(
  id: string,
): Promise<SimulationEvalRun[]> {
  return request<SimulationEvalRun[]>(
    `/api/simulations/${id}/evals`,
  );
}

export async function getSimulationSocialGraph(
  id: string,
): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>(
    `/api/simulations/${id}/social-graph`,
  );
}

export interface SnapshotSummary {
  filename: string;
  simulation_id: string;
  snapshot_at: string;
  agent_count: number;
}

export async function getSimulationSnapshots(
  id: string,
): Promise<SnapshotSummary[]> {
  return request<SnapshotSummary[]>(`/api/simulations/${id}/snapshots`);
}

export async function getSimulationSnapshot(
  simId: string,
  filename: string,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/api/admin/simulations/${simId}/snapshots/${encodeURIComponent(filename)}`,
  );
}

export interface CloneSimulationRequest {
  name?: string;
  agents?: string[];
}

export interface CloneSimulationResponse {
  simulation_id: string;
  name: string;
  source_simulation_id: string;
  restore_result: Record<string, unknown>;
}

export async function cloneSimulationFromSnapshot(
  simId: string,
  body: CloneSimulationRequest = {},
): Promise<CloneSimulationResponse> {
  return request<CloneSimulationResponse>(
    `/api/admin/simulations/${simId}/clone`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

// Simulation conversations
export async function getSimulationConversations(
  id: string,
  params?: { limit?: number; offset?: number },
): Promise<PaginatedResponse<ConversationSummary>> {
  const searchParams = new URLSearchParams();
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return request<PaginatedResponse<ConversationSummary>>(
    `/api/simulations/${id}/conversations${qs ? `?${qs}` : ""}`,
  );
}

// Simulation costs
export interface SimulationCostResponse {
  by_agent: { agent_id: string; total: string }[];
  total: string;
  total_input_tokens: number;
  total_output_tokens: number;
}

export async function getSimulationCosts(
  id: string,
): Promise<SimulationCostResponse> {
  return request<SimulationCostResponse>(`/api/simulations/${id}/costs`);
}

// Simulation timeline
export interface TimelineEvent {
  timestamp: string | null;
  event_type: string;
  agent_id: string | null;
  details: Record<string, unknown>;
}

export async function getSimulationTimeline(
  id: string,
  params?: { agent_id?: string; event_type?: string },
): Promise<TimelineEvent[]> {
  const searchParams = new URLSearchParams();
  if (params?.agent_id) searchParams.set("agent_id", params.agent_id);
  if (params?.event_type) searchParams.set("event_type", params.event_type);
  const qs = searchParams.toString();
  return request<TimelineEvent[]>(
    `/api/simulations/${id}/timeline${qs ? `?${qs}` : ""}`,
  );
}

export async function getArtifacts(params?: {
  limit?: number;
  offset?: number;
  agent_id?: string;
  type?: string;
}): Promise<PaginatedResponse<AgentArtifactResponse>> {
  const searchParams = new URLSearchParams();
  if (params?.limit != null) searchParams.set("limit", String(params.limit));
  if (params?.offset != null) searchParams.set("offset", String(params.offset));
  if (params?.agent_id) searchParams.set("agent_id", params.agent_id);
  if (params?.type) searchParams.set("type", params.type);
  const qs = searchParams.toString();
  return request<PaginatedResponse<AgentArtifactResponse>>(
    `/api/artifacts${qs ? `?${qs}` : ""}`,
  );
}

export { ApiRequestError };

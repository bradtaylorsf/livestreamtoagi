/**
 * Admin API client — fetches from /api/admin/* endpoints.
 * Follows same pattern as the existing api.ts client.
 */

import type {
  AgentArtifact,
  AgentConversation,
  AgentCostBreakdown,
  AgentDetail,
  AgentSummary,
  ArtifactFilters,
  ConversationDetail,
  CoreMemoryResponse,
  DashboardStats,
  EvalHistoryPoint,
  EvalRun,
  InterruptEvent,
  JournalEntry,
  OverseerFlag,
  PaginatedResponse,
  RecallMemory,
  SelectionLog,
  Simulation,
  SimulationCostResponse,
  SystemPromptResponse,
  TimelineEvent,
  TurnDetail,
} from "@/types/admin";

const DEFAULT_TIMEOUT_MS = 10_000;

function getAdminToken(): string {
  if (typeof window !== "undefined") {
    return localStorage.getItem("admin_password") ?? "";
  }
  return "";
}

export function setAdminToken(password: string): void {
  localStorage.setItem("admin_password", password);
}

export function clearAdminToken(): void {
  localStorage.removeItem("admin_password");
}

class AdminApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
  const token = getAdminToken();

  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });

    if (!response.ok) {
      let message = response.statusText;
      try {
        const body = await response.json();
        message = body.detail || body.message || message;
      } catch {
        // Use statusText as fallback
      }
      throw new AdminApiError(response.status, message);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeout);
  }
}

// ── Dashboard ────────────────────────────────────────────────────

export async function fetchDashboardStats(): Promise<DashboardStats> {
  // Derive stats from simulations list (no dedicated endpoint needed)
  const { items } = await fetchSimulations();
  const total = items.length;
  const lastRun = items.length > 0 ? items[0].started_at : null;
  const totalCost = items.reduce(
    (sum, s) => sum + parseFloat(s.total_cost || "0"),
    0,
  );
  const avgCost = total > 0 ? totalCost / total : 0;
  const totalConversations = items.reduce(
    (sum, s) => sum + s.total_conversations,
    0,
  );

  return {
    total_simulations: total,
    last_run_date: lastRun,
    average_cost: avgCost.toFixed(4),
    total_conversations: totalConversations,
  };
}

// ── Artifacts (global) ──────────────────────────────────────────

export async function fetchArtifacts(
  filters: ArtifactFilters = {},
): Promise<PaginatedResponse<AgentArtifact>> {
  const params = new URLSearchParams();
  if (filters.simulation_id) params.set("simulation_id", filters.simulation_id);
  if (filters.agent_ids?.length) params.set("agent_id", filters.agent_ids.join(","));
  if (filters.types?.length) params.set("type", filters.types.join(","));
  if (filters.statuses?.length) params.set("status", filters.statuses.join(","));
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.search) params.set("search", filters.search);
  if (filters.sort) params.set("sort", filters.sort);
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.offset != null) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return request<PaginatedResponse<AgentArtifact>>(
    `/api/admin/artifacts${qs ? `?${qs}` : ""}`,
  );
}

// ── Simulations ──────────────────────────────────────────────────

export interface CreateSimulationParams {
  name?: string;
  agents?: string[];
  convo_type?: string;
  topic?: string;
  turns?: number;
  overseer_shadow?: boolean;
}

export interface CreateSimulationResult {
  simulation_id: string;
  name: string;
  status: string;
}

export async function createSimulation(
  params: CreateSimulationParams,
): Promise<CreateSimulationResult> {
  return request<CreateSimulationResult>("/api/admin/simulations", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function fetchSimulations(
  status?: string,
): Promise<PaginatedResponse<Simulation>> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("limit", "500");
  const qs = params.toString();
  return request<PaginatedResponse<Simulation>>(
    `/api/admin/simulations${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchSimulation(id: string): Promise<Simulation> {
  return request<Simulation>(`/api/admin/simulations/${id}`);
}

export async function fetchSimulationTimeline(
  id: string,
  agentId?: string,
  eventType?: string,
): Promise<TimelineEvent[]> {
  const params = new URLSearchParams();
  if (agentId) params.set("agent_id", agentId);
  if (eventType) params.set("event_type", eventType);
  const qs = params.toString();
  return request<TimelineEvent[]>(
    `/api/admin/simulations/${id}/timeline${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchSimulationCosts(
  id: string,
): Promise<SimulationCostResponse> {
  return request<SimulationCostResponse>(
    `/api/admin/simulations/${id}/costs`,
  );
}

// ── Conversations ───────────────────────────────────────────────

export async function fetchConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/api/admin/conversations/${id}`);
}

export async function fetchConversationTurns(
  id: string,
): Promise<TurnDetail[]> {
  return request<TurnDetail[]>(`/api/admin/conversations/${id}/turns`);
}

export async function fetchConversationSelectionLog(
  id: string,
): Promise<SelectionLog[]> {
  return request<SelectionLog[]>(
    `/api/admin/conversations/${id}/selection-log`,
  );
}

export async function fetchConversationOverseerFlags(
  id: string,
): Promise<OverseerFlag[]> {
  return request<OverseerFlag[]>(
    `/api/admin/conversations/${id}/overseer-flags`,
  );
}

export async function fetchConversationInterrupts(
  id: string,
): Promise<InterruptEvent[]> {
  return request<InterruptEvent[]>(
    `/api/admin/conversations/${id}/interrupts`,
  );
}

export async function fetchConversationArtifacts(
  id: string,
): Promise<AgentArtifact[]> {
  return request<AgentArtifact[]>(
    `/api/admin/conversations/${id}/artifacts`,
  );
}

export async function fetchSimulationConversations(
  simId: string,
  opts?: { offset?: number; limit?: number },
): Promise<PaginatedResponse<AgentConversation>> {
  const params = new URLSearchParams();
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<PaginatedResponse<AgentConversation>>(
    `/api/admin/simulations/${simId}/conversations${qs ? `?${qs}` : ""}`,
  );
}

// ── Agents ──────────────────────────────────────────────────────

export async function fetchAgents(): Promise<AgentSummary[]> {
  return request<AgentSummary[]>("/api/admin/agents");
}

export async function fetchAgent(id: string): Promise<AgentDetail> {
  return request<AgentDetail>(`/api/admin/agents/${id}`);
}

export async function fetchAgentSystemPrompt(
  id: string,
): Promise<SystemPromptResponse> {
  return request<SystemPromptResponse>(`/api/admin/agents/${id}/system-prompt`);
}

export async function fetchAgentCoreMemory(
  id: string,
): Promise<CoreMemoryResponse> {
  return request<CoreMemoryResponse>(`/api/admin/agents/${id}/core-memory`);
}

export async function fetchAgentRecallMemories(
  id: string,
  opts?: { search?: string; simulation_id?: string; offset?: number; limit?: number },
): Promise<PaginatedResponse<RecallMemory>> {
  const params = new URLSearchParams();
  if (opts?.search) params.set("search", opts.search);
  if (opts?.simulation_id) params.set("simulation_id", opts.simulation_id);
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<PaginatedResponse<RecallMemory>>(
    `/api/admin/agents/${id}/recall-memories${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchAgentConversations(
  id: string,
  opts?: { simulation_id?: string; offset?: number; limit?: number },
): Promise<PaginatedResponse<AgentConversation>> {
  const params = new URLSearchParams();
  if (opts?.simulation_id) params.set("simulation_id", opts.simulation_id);
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<PaginatedResponse<AgentConversation>>(
    `/api/admin/agents/${id}/conversations${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchAgentArtifacts(
  id: string,
  opts?: { type?: string; simulation_id?: string; offset?: number; limit?: number },
): Promise<PaginatedResponse<AgentArtifact>> {
  const params = new URLSearchParams();
  if (opts?.type) params.set("type", opts.type);
  if (opts?.simulation_id) params.set("simulation_id", opts.simulation_id);
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<PaginatedResponse<AgentArtifact>>(
    `/api/admin/agents/${id}/artifacts${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchAgentJournal(
  id: string,
  opts?: { simulation_id?: string; offset?: number; limit?: number },
): Promise<PaginatedResponse<JournalEntry>> {
  const params = new URLSearchParams();
  if (opts?.simulation_id) params.set("simulation_id", opts.simulation_id);
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return request<PaginatedResponse<JournalEntry>>(
    `/api/admin/agents/${id}/journal${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchAgentCosts(
  id: string,
  from?: string,
  to?: string,
): Promise<AgentCostBreakdown> {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.toString();
  return request<AgentCostBreakdown>(
    `/api/admin/agents/${id}/costs${qs ? `?${qs}` : ""}`,
  );
}

// ── Evals ──────────────────────────────────────────────────────

export async function fetchSimulationEvals(
  simId: string,
): Promise<EvalRun[]> {
  return request<EvalRun[]>(`/api/admin/simulations/${simId}/evals`);
}

export async function triggerEvalRun(
  simId: string,
  suite: string = "full",
  categories?: string[],
): Promise<{ eval_run_id: string; status: string }> {
  return request<{ eval_run_id: string; status: string }>(
    `/api/admin/simulations/${simId}/evals/run`,
    {
      method: "POST",
      body: JSON.stringify({
        eval_suite: suite,
        ...(categories ? { categories } : {}),
      }),
    },
  );
}

export async function fetchEvalRun(evalId: string): Promise<EvalRun> {
  return request<EvalRun>(`/api/admin/evals/${evalId}`);
}

export async function fetchAllEvalRuns(
  limit: number = 50,
  offset: number = 0,
): Promise<EvalRun[]> {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return request<EvalRun[]>(`/api/admin/evals?${params.toString()}`);
}

export async function fetchEvalCategories(): Promise<string[]> {
  return request<string[]>("/api/admin/evals/categories");
}

export async function fetchEvalHistory(
  category: string,
): Promise<EvalHistoryPoint[]> {
  return request<EvalHistoryPoint[]>(
    `/api/admin/evals/history?category=${encodeURIComponent(category)}`,
  );
}

export async function compareEvals(
  runA: string,
  runB: string,
): Promise<{ run_a: EvalRun; run_b: EvalRun }> {
  return request<{ run_a: EvalRun; run_b: EvalRun }>(
    `/api/admin/evals/compare?run_a=${runA}&run_b=${runB}`,
  );
}

export async function exportEval(evalId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/evals/${evalId}/export`);
}

export { AdminApiError };

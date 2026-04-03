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
  CoreMemoryResponse,
  DashboardStats,
  JournalEntry,
  PaginatedResponse,
  RecallMemory,
  Simulation,
  SimulationCostResponse,
  SystemPromptResponse,
  TimelineEvent,
} from "@/types/admin";

const DEFAULT_TIMEOUT_MS = 10_000;

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

// ── Simulations ──────────────────────────────────────────────────

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

export { AdminApiError };

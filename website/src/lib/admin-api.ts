/**
 * Admin API client — fetches from /api/admin/* endpoints.
 * Follows same pattern as the existing api.ts client.
 */

import type {
  DashboardStats,
  PaginatedResponse,
  Simulation,
  SimulationCostResponse,
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

export { AdminApiError };

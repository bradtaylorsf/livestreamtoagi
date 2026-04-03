/** Admin dashboard types — mirrors backend Pydantic models from core/models.py */

export type SimulationStatus = "running" | "completed" | "failed" | "cancelled";

export interface Simulation {
  id: string;
  name: string;
  description: string | null;
  config: Record<string, unknown>;
  status: SimulationStatus;
  started_at: string | null;
  completed_at: string | null;
  simulated_duration: string | null;
  real_duration: string | null;
  total_conversations: number;
  total_turns: number;
  total_tokens: number;
  total_cost: string;
  total_artifacts: number;
  total_overseer_flags: number;
  agents_participated: string[];
  error_log: Record<string, unknown> | unknown[] | null;
  created_at: string | null;
}

export interface TimelineEvent {
  timestamp: string | null;
  event_type: string;
  agent_id: string | null;
  details: Record<string, unknown>;
}

export interface SimulationCostResponse {
  by_agent: { agent_id: string; total: string }[];
  total: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface DashboardStats {
  total_simulations: number;
  last_run_date: string | null;
  average_cost: string;
  total_conversations: number;
}

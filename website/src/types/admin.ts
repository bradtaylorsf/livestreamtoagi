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
  total_input_tokens: number;
  total_output_tokens: number;
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

// ── Agent types ─────────────────────────────────────────────────

export interface AgentSummary {
  id: string;
  display_name: string;
  role: string;
  color: string;
  status: string;
  conversation_model: string;
  building_model: string;
  total_cost: string;
  message_count: number;
  conversation_count: number;
  artifact_count: number;
  personality_traits: PersonalityTraits;
}

export interface PersonalityTraits {
  chattiness: number;
  initiative: number;
  interrupt_tendency: number;
  eavesdrop_tendency: number;
  closing_weight: number;
}

export interface AgentDetail extends AgentSummary {
  voice: string | null;
  behaviors: Record<string, unknown>;
}

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

export interface CoreMemoryVersion {
  version: number;
  content: string;
  changed_at: string;
  change_reason: string | null;
}

export interface CoreMemoryResponse {
  current_content: string;
  current_version: number;
  token_count: number;
  last_updated: string | null;
  version_history: CoreMemoryVersion[];
}

export interface RecallMemory {
  id: string;
  summary: string;
  event_type: string;
  importance_score: number;
  created_at: string;
  simulation_id: string | null;
}

export interface AgentConversation {
  id: string;
  simulation_id: string | null;
  trigger_type: string;
  participating_agents: string[];
  turn_count: number;
  started_at: string;
}

export interface ConversationDetail {
  id: string;
  simulation_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  trigger_type: string;
  trigger_details: Record<string, unknown> | null;
  initial_energy: number;
  final_energy: number | null;
  turn_count: number;
  participating_agents: string[];
  topics_discussed: string[] | null;
  closed_by: string | null;
  location: string | null;
  energy_history: Record<string, unknown>[];
  transcript: string | null;
  total_tokens: number;
  total_cost: string;
}

export interface TurnDetail {
  turn_number: number;
  selected_agent_id: string;
  was_interrupt: boolean;
  agent_scores: Record<string, AgentScoreBreakdown>;
  detected_topic: string | null;
  previous_speaker_id: string | null;
  conversation_energy: number | null;
  timestamp: string | null;
}

export interface AgentScoreBreakdown {
  time_since_spoke: number;
  topic_relevance: number;
  chattiness: number;
  adjacency_fit: number;
  random_jitter: number;
  total: number;
}

export interface SelectionLog {
  id: number;
  conversation_id: string;
  turn_number: number;
  timestamp: string | null;
  selected_agent_id: string;
  was_interrupt: boolean;
  agent_scores: Record<string, unknown>;
  detected_topic: string | null;
  previous_speaker_id: string | null;
  conversation_energy: number | null;
  active_agents: string[] | null;
}

export interface OverseerFlag {
  id: string;
  agent_id: string;
  original_content: string;
  filter_layer: number;
  severity: number;
  action_would_take: string;
  reason: string;
  flagged_keywords: string[];
  created_at: string | null;
}

export interface InterruptEvent {
  id: number;
  attempting_agent_id: string;
  would_have_spoken_id: string;
  interrupt_score: number;
  threshold_at_time: number;
  succeeded: boolean;
  reason: string | null;
  timestamp: string | null;
}

export type ArtifactType =
  | "social_post"
  | "email"
  | "code_execution"
  | "web_search"
  | "tilemap"
  | "poll"
  | "memory_operation"
  | "alpha_dispatch"
  | "self_modification"
  | "message";

export type ArtifactStatus = "draft" | "executed" | "failed" | "pending_approval";

export interface ArtifactFilters {
  simulation_id?: string;
  agent_ids?: string[];
  types?: ArtifactType[];
  statuses?: ArtifactStatus[];
  since?: string;
  until?: string;
  search?: string;
  sort?: "newest" | "oldest" | "agent" | "type";
  limit?: number;
  offset?: number;
}

export interface AgentArtifact {
  id: string;
  simulation_id: string | null;
  agent_id: string;
  artifact_type: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output: Record<string, unknown> | string | null;
  status: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface JournalEntry {
  id: string;
  simulation_id: string | null;
  content: string;
  reflection_type: string;
  created_at: string;
}

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

// ── Eval types ────────────────────────────────────────────────

export interface EvalResult {
  id: string;
  eval_run_id: string;
  category: string;
  score: number | null;
  reasoning: string | null;
  evidence: Record<string, unknown> | null;
  sub_scores: Record<string, number> | null;
  tokens_used: number;
  cost: string;
  created_at: string | null;
}

export interface EvalRun {
  id: string;
  simulation_id: string;
  eval_suite: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  overall_score: number | null;
  cost: number | string;
  created_at: string | null;
  results?: EvalResult[];
}

export interface EvalHistoryPoint {
  score: number | null;
  created_at: string | null;
  simulation_id: string;
  eval_run_id: string;
}

// ── Relationship types ────────────────────────────────────────

export interface Relationship {
  agent_id: string;
  target_agent_id: string;
  sentiment_score: number;
  trust_score: number;
  interaction_count: number;
  relationship_summary: string | null;
  simulation_id: string | null;
}

export interface RelationshipEvolution {
  timestamp: string;
  sentiment_score: number;
  event: string | null;
}

export interface RelationshipDetail extends Relationship {
  evolution: RelationshipEvolution[];
}

// ── Snapshot types ────────────────────────────────────────────

export interface SnapshotSummary {
  filename: string;
  simulation_id: string;
  snapshot_at: string;
  agent_count: number;
}

export interface SnapshotData {
  version: number;
  source_simulation_id: string | null;
  snapshot_at: string;
  agents: Record<string, AgentSnapshotData>;
  relationships: Record<string, unknown>[];
}

export interface AgentSnapshotData {
  core_memory: string;
  recall_memories: Record<string, unknown>[];
  journal_entries: Record<string, unknown>[];
}

export interface CurrentMemoryState {
  agents: Record<string, { core_memory: string; recall_count: number; journal_count: number }>;
}

// ── Assertion types ───────────────────────────────────────────

export interface AssertionResult {
  id: string;
  simulation_id: string;
  phase_name: string;
  assertion_name: string;
  status: "pass" | "fail" | "warning";
  severity: "error" | "warning";
  expected: string | null;
  actual: string | null;
  message: string | null;
  created_at: string | null;
}

export interface AssertionSummary {
  passed: number;
  failed: number;
  warnings: number;
}

// ── Report types ──────────────────────────────────────────────

export interface ReportSection {
  title: string;
  data: Record<string, unknown>;
}

export interface SimulationReport {
  simulation_id: string;
  simulation_name: string;
  sections: ReportSection[];
}

// ── Comparison types ──────────────────────────────────────────

export interface MetricComparison {
  metric: string;
  run_a: unknown;
  run_b: unknown;
  delta: unknown;
  better_run: "a" | "b" | null;
}

export interface ComparisonResult {
  run_a: Record<string, unknown>;
  run_b: Record<string, unknown>;
  metrics: MetricComparison[];
  daily_costs: {
    run_a: { day: string; cost: string }[];
    run_b: { day: string; cost: string }[];
  };
}

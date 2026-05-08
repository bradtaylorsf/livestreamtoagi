export interface Agent {
  id: string;
  name: string;
  role: string;
  personality: string;
  status: "active" | "idle" | "building" | "sleeping";
  energy: number;
  location: { x: number; y: number };
  color: string;
}

export interface JournalEntry {
  id: string;
  agent_id: string;
  timestamp: string;
  content: string;
  mood: string;
  image_url: string | null;
  reflection_type: string;
}

export interface ChatResponse {
  agent_id: string;
  message: string;
  timestamp: string;
}

export interface WorldChunk {
  id: string;
  name: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  tiles: number[][];
  objects: WorldObject[];
}

export interface WorldObject {
  id: string;
  type: string;
  x: number;
  y: number;
  properties: Record<string, unknown>;
}

export interface Challenge {
  id: number;
  description: string;
  submitted_by: string | null;
  status: "pending" | "in_progress" | "completed" | "failed";
  assigned_agents: string[] | null;
  result: string | null;
  cost_estimate: number | null;
  actual_cost: number | null;
  votes: number;
  category: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface ChallengeSubmission {
  description: string;
  category?: string;
  submitter_name?: string;
}

export interface Stats {
  total_simulations: number;
  total_agents: number;
  total_cost: string;
  total_conversations: number;
}

export interface LoreEvent {
  id: number;
  event_type: string | null;
  description: string | null;
  agents_involved: string[] | null;
  audience_participation: boolean;
  created_at: string | null;
}

export interface ConversationSummary {
  id: string;
  simulation_id: string | null;
  trigger_type: string;
  participating_agents: string[];
  topics_discussed: string[] | null;
  turn_count: number;
  location: string | null;
  started_at: string | null;
}

export interface ConversationDetail {
  id: string;
  simulation_id: string | null;
  trigger_type: string;
  trigger_details: Record<string, unknown> | null;
  participating_agents: string[];
  topics_discussed: string[] | null;
  turn_count: number;
  location: string | null;
  initial_energy: number;
  final_energy: number | null;
  started_at: string | null;
  ended_at: string | null;
  closed_by: string | null;
  transcript: string | null;
  energy_history: Record<string, unknown>[];
  total_tokens: number;
  total_cost: string;
}

export interface SelectionLogEntry {
  turn_number: number;
  selected_agent_id: string;
  was_interrupt: boolean;
  agent_scores: Record<string, Record<string, number>>;
  detected_topic: string | null;
  previous_speaker_id: string | null;
  conversation_energy: number | null;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ApiError {
  status: number;
  message: string;
}

export interface BlogPost {
  slug: string;
  title: string;
  date: string;
  excerpt: string;
}

export interface WorldMilestone {
  id: string;
  date: string;
  title: string;
  description: string;
}

export interface AgentEvolutionEvent {
  date: string;
  type: "config_change" | "personality_drift" | "self_modification";
  description: string;
}

export interface AgentArtifact {
  id: string;
  type: string;
  title: string;
  preview: string;
  createdAt: string;
}

export interface AgentConversation {
  id: string;
  trigger_type: string;
  participating_agents: string[];
  topics_discussed: string[] | null;
  turn_count: number;
  location: string | null;
  started_at: string | null;
}

export interface AgentArtifactResponse {
  id: string;
  agent_id: string;
  tool_name: string;
  artifact_type: string;
  status: string;
  summary: string | null;
  created_at: string | null;
}

// Decimal fields are serialized as strings by the backend (Pydantic Decimal → str).
// Coerce with Number() at call sites before numeric operations.
export interface AgentRelationshipResponse {
  id: string;
  target_agent_id: string;
  sentiment_score: number | string;
  trust_score: number | string;
  interaction_count: number;
  relationship_summary: string | null;
}

export interface AgentEvolutionResponse {
  id: string;
  version: number;
  change_reason: string | null;
  source: "manual" | "system" | "evolution";
  created_at: string | null;
}

export interface CoreMemoryVersion {
  version: number;
  content: string;
  changed_at: string | null;
  change_reason: string | null;
}

export interface CoreMemoryPublic {
  current_content: string;
  current_version: number;
  token_count: number;
  last_updated: string | null;
  version_history: CoreMemoryVersion[];
}

export interface RecallMemoryPublic {
  id: string;
  agent_id: string;
  summary: string;
  event_type: string | null;
  importance_score: number | null;
  created_at: string | null;
}

export interface EvalHistoryPoint {
  score: number | null;
  created_at: string | null;
  simulation_id: string;
  eval_run_id: string;
}

export type ClipCategory = "funny" | "dramatic" | "technical" | "philosophical";

export interface Clip {
  id: string;
  title: string;
  timestamp: string;
  transcript_excerpt: string;
  video_url?: string;
  category: ClipCategory;
  agent_ids: string[];
}

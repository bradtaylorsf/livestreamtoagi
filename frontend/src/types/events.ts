/**
 * Event types and interfaces matching the backend EventType enum
 * from core/event_bus.py.
 */

export enum EventType {
  AGENT_SPEAK = "agent_speak",
  AGENT_MOVE = "agent_move",
  AGENT_ACTION = "agent_action",
  ALPHA_DISPATCH = "alpha_dispatch",
  ALPHA_RETURN = "alpha_return",
  MANAGEMENT_WARNING = "management_warning",
  MANAGEMENT_INTERVENTION = "management_intervention",
  MANAGEMENT_SHADOW = "management_shadow",
  WORLD_EXPANSION = "world_expansion",
  POLL_CREATED = "poll_created",
  POLL_RESULT = "poll_result",
  BUDGET_UPDATE = "budget_update",
  VIEWER_COUNT = "viewer_count",
  TTS_PLAY = "tts_play",
  TOOL_EXECUTED = "tool_executed",
  CONFIG_RELOADED = "config_reloaded",
  AGI_PROGRESS = "agi_progress",
  ARTIFACT_CREATED = "artifact_created",
  AGENT_SPAWN = "agent_spawn",
  AGENT_DESPAWN = "agent_despawn",
  TASK_DELEGATED = "task_delegated",
  TASK_COMPLETED = "task_completed",
}

/** Base event envelope matching backend event_bus.py emit() format. */
export interface ServerEvent {
  event_id: string;
  event_type: EventType;
  timestamp: number;
  data: Record<string, unknown>;
}

// ── Typed payload interfaces ────────────────────────────────────

export interface AgentSpeakPayload {
  agent_id: string;
  text: string;
  conversation_id?: string;
}

/** Coordinates are in pixels (tile * 32). WorldManager.findPath() accepts pixels directly. */
export interface AgentMovePayload {
  agent_id: string;
  from: { x: number; y: number };
  to: { x: number; y: number };
}

export interface AgentActionPayload {
  agent_id: string;
  action: string;
  target?: string;
}

export interface AlphaDispatchPayload {
  task: string;
  dispatched_by: string;
}

export interface AlphaReturnPayload {
  task: string;
  result: string;
  success: boolean;
}

export interface ManagementWarningPayload {
  agent_id: string;
  reason: string;
  severity?: ManagementSeverity;
}

export type ManagementSeverity = 1 | 2 | 3 | 4 | 5;

export interface ManagementInterventionPayload {
  agent_id: string;
  action: string;
  original_text: string;
  filtered_text: string;
  severity?: ManagementSeverity;
  message?: string;
}

export interface ManagementShadowPayload {
  agent_id: string;
  flagged_content: string;
}

export interface WorldExpansionPayload {
  zone: string;
  description: string;
  chunk_id?: number;
  chunk_name?: string;
  tilemap_url?: string;
  tileset_url?: string;
  offset?: { x: number; y: number };
  agent_id?: string;
}

export interface PollCreatedPayload {
  poll_id: string;
  question: string;
  options: string[];
}

export interface PollResultPayload {
  poll_id: string;
  results: Record<string, number>;
  winner: string;
}

export interface BudgetUpdatePayload {
  total_spent: number;
  daily_limit: number;
  remaining: number;
}

export interface ViewerCountPayload {
  count: number;
  platform?: string;
}

export interface TtsPlayPayload {
  agent_id: string;
  audio_url: string;
  text: string;
}

export interface ToolExecutedPayload {
  agent_id: string;
  tool_name: string;
  success: boolean;
  result?: string;
  status?: "start" | "done";
}

export interface ConfigReloadedPayload {
  config_type: string;
  changes: string[];
}

export interface AgiProgressPayload {
  percent: number;
  categories: number;
}

export interface ArtifactCreatedPayload {
  agent_id: string;
  artifact_type: string;
  name: string;
  url?: string;
}

export interface AgentSpawnPayload {
  agent_id: string;
  reason: "start" | "reconnect";
}

export interface AgentDespawnPayload {
  agent_id: string;
  reason: "error" | "kill_switch" | "shutdown";
}

export interface TaskDelegatedPayload {
  from_agent: string;
  to_agent: string;
  task_description: string;
  task_id: string;
}

export interface TaskCompletedPayload {
  task_id: string;
  to_agent: string;
  success: boolean;
  result?: string;
}

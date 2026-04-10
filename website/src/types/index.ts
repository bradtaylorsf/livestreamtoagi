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
}

export interface ChatResponse {
  agent_id: string;
  message: string;
  timestamp: string;
}

export interface WorldChunk {
  id: string;
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
  agi_progress: number;
  total_cost: number;
  daily_cost: number;
  revenue: number;
  viewers: number;
  uptime_hours: number;
}

export interface LoreEvent {
  id: string;
  timestamp: string;
  title: string;
  description: string;
  agents_involved: string[];
  significance: "minor" | "major" | "legendary";
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

export interface AgentRelationship {
  targetId: string;
  targetName: string;
  sentiment: number;
  trust: number;
  interactionCount: number;
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

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
  id: string;
  title: string;
  description: string;
  status: "proposed" | "active" | "completed" | "failed";
  votes: number;
  submitted_by: string;
  created_at: string;
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

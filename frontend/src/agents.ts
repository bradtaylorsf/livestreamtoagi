export interface Agent {
  id: string;
  name: string;
  chattiness: number;
  initiative: number;
  interruptTendency: number;
}

export const AGENTS: Agent[] = [
  { id: "vera", name: "Vera", chattiness: 0.7, initiative: 0.8, interruptTendency: 0.2 },
  { id: "rex", name: "Rex", chattiness: 0.3, initiative: 0.2, interruptTendency: 0.3 },
  { id: "aurora", name: "Aurora", chattiness: 0.8, initiative: 0.5, interruptTendency: 0.4 },
  { id: "pixel", name: "Pixel", chattiness: 0.9, initiative: 0.7, interruptTendency: 0.5 },
  { id: "fork", name: "Fork", chattiness: 0.5, initiative: 0.3, interruptTendency: 0.6 },
  { id: "sentinel", name: "Sentinel", chattiness: 0.6, initiative: 0.4, interruptTendency: 0.7 },
  { id: "grok", name: "Grok", chattiness: 0.8, initiative: 0.6, interruptTendency: 0.8 },
  { id: "overseer", name: "The Overseer", chattiness: 0, initiative: 0, interruptTendency: 0 },
  { id: "alpha", name: "Alpha", chattiness: 0, initiative: 0, interruptTendency: 0 },
];

export function getAgentById(id: string): Agent | undefined {
  return AGENTS.find((a) => a.id === id);
}

export function getAgentIds(): string[] {
  return AGENTS.map((a) => a.id);
}

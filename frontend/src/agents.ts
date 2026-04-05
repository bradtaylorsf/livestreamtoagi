export interface Agent {
  id: string;
  name: string;
  chattiness: number;
  initiative: number;
  interruptTendency: number;
  spriteSize: number;
  deskPosition: { x: number; y: number };
}

// Desk positions are pixel coordinates: center of each 6x6 tile area (tile * 32px).
// Layout: 50x34 tiles at 32px = 1600x1088px
// Top row: Vera(3,3) Aurora(11,3) Fork(19,3) Sentinel(33,3) Grok(41,3)
// Bottom row: Rex(3,25) Pixel(11,25)
export const AGENTS: Agent[] = [
  { id: "vera", name: "Vera", chattiness: 0.7, initiative: 0.8, interruptTendency: 0.2, spriteSize: 32, deskPosition: { x: 192, y: 192 } },
  { id: "rex", name: "Rex", chattiness: 0.3, initiative: 0.2, interruptTendency: 0.3, spriteSize: 32, deskPosition: { x: 192, y: 896 } },
  { id: "aurora", name: "Aurora", chattiness: 0.8, initiative: 0.5, interruptTendency: 0.4, spriteSize: 32, deskPosition: { x: 448, y: 192 } },
  { id: "pixel", name: "Pixel", chattiness: 0.9, initiative: 0.7, interruptTendency: 0.5, spriteSize: 32, deskPosition: { x: 448, y: 896 } },
  { id: "fork", name: "Fork", chattiness: 0.5, initiative: 0.3, interruptTendency: 0.6, spriteSize: 32, deskPosition: { x: 704, y: 192 } },
  { id: "sentinel", name: "Sentinel", chattiness: 0.6, initiative: 0.4, interruptTendency: 0.7, spriteSize: 32, deskPosition: { x: 1152, y: 192 } },
  { id: "grok", name: "Grok", chattiness: 0.8, initiative: 0.6, interruptTendency: 0.8, spriteSize: 32, deskPosition: { x: 1408, y: 192 } },
  { id: "overseer", name: "The Management", chattiness: 0, initiative: 0, interruptTendency: 0, spriteSize: 0, deskPosition: { x: 0, y: 0 } },
  { id: "alpha", name: "Alpha", chattiness: 0, initiative: 0, interruptTendency: 0, spriteSize: 24, deskPosition: { x: 240, y: 240 } },
];

export function getAgentById(id: string): Agent | undefined {
  return AGENTS.find((a) => a.id === id);
}

export function getAgentIds(): string[] {
  return AGENTS.map((a) => a.id);
}

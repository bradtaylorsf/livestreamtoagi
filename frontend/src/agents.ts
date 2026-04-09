export interface Agent {
  id: string;
  name: string;
  chattiness: number;
  initiative: number;
  interruptTendency: number;
  spriteSize: number;
  deskPosition: { x: number; y: number };
  workspaceArea: string;
}

// Agent stands at center-x of their desk (desk.x + 48px), below/above desk.
// Desk image is 96px wide (3 tiles). Top-row desks at y=2, bottom at y=17.
// Top-row agents at y=5.5 tiles (below desk+chair). Bottom-row at y=16 tiles (above desk).
// Desk x positions (tiles): Top=[2,10,24,33], Bottom=[2,10,24]
export const AGENTS: Agent[] = [
  { id: "vera", name: "Vera", chattiness: 0.7, initiative: 0.8, interruptTendency: 0.2, spriteSize: 32, deskPosition: { x: 2 * 32 + 48, y: 6 * 32 }, workspaceArea: "workspace_vera" },
  { id: "aurora", name: "Aurora", chattiness: 0.8, initiative: 0.5, interruptTendency: 0.4, spriteSize: 32, deskPosition: { x: 10 * 32 + 48, y: 6 * 32 }, workspaceArea: "workspace_aurora" },
  { id: "sentinel", name: "Sentinel", chattiness: 0.6, initiative: 0.4, interruptTendency: 0.7, spriteSize: 32, deskPosition: { x: 24 * 32 + 48, y: 6 * 32 }, workspaceArea: "workspace_sentinel" },
  { id: "grok", name: "Grok", chattiness: 0.8, initiative: 0.6, interruptTendency: 0.8, spriteSize: 32, deskPosition: { x: 33 * 32 + 48, y: 6 * 32 }, workspaceArea: "workspace_grok" },
  { id: "rex", name: "Rex", chattiness: 0.3, initiative: 0.2, interruptTendency: 0.3, spriteSize: 32, deskPosition: { x: 2 * 32 + 48, y: 16 * 32 }, workspaceArea: "workspace_rex" },
  { id: "fork", name: "Fork", chattiness: 0.5, initiative: 0.3, interruptTendency: 0.6, spriteSize: 32, deskPosition: { x: 10 * 32 + 48, y: 16 * 32 }, workspaceArea: "workspace_fork" },
  { id: "pixel", name: "Pixel", chattiness: 0.9, initiative: 0.7, interruptTendency: 0.5, spriteSize: 32, deskPosition: { x: 24 * 32 + 48, y: 16 * 32 }, workspaceArea: "workspace_pixel" },
  { id: "management", name: "The Management", chattiness: 0, initiative: 0, interruptTendency: 0, spriteSize: 0, deskPosition: { x: 0, y: 0 }, workspaceArea: "workspace_management" },
  { id: "alpha", name: "Alpha", chattiness: 0, initiative: 0, interruptTendency: 0, spriteSize: 24, deskPosition: { x: 2 * 32 + 80, y: 7 * 32 }, workspaceArea: "workspace_alpha" },
];

export function getAgentById(id: string): Agent | undefined {
  return AGENTS.find((a) => a.id === id);
}

export function getAgentIds(): string[] {
  return AGENTS.map((a) => a.id);
}

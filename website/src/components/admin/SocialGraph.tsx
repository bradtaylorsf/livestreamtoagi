"use client";

import type { Relationship } from "@/types/admin";

const AGENT_COLORS: Record<string, string> = {
  vera: "#00f0ff",
  rex: "#ff6b35",
  aurora: "#ff69b4",
  pixel: "#7cfc00",
  fork: "#ffd700",
  sentinel: "#8a2be2",
  grok: "#ff4500",
  management: "#808080",
  alpha: "#c0c0c0",
};

const DEFAULT_COLOR = "#666666";

function sentimentColor(score: number): string {
  if (score > 0.3) return "#4ade80";
  if (score > 0) return "#86efac";
  if (score > -0.3) return "#9ca3af";
  if (score > -0.6) return "#f87171";
  return "#ef4444";
}

function edgeThickness(interactionCount: number): number {
  // Map interaction count to 1–4px
  const clamped = Math.min(Math.max(interactionCount, 0), 50);
  return 1 + (clamped / 50) * 3;
}

interface Props {
  relationships: Relationship[];
  onSelectPair: (agentA: string, agentB: string) => void;
}

export default function SocialGraph({ relationships, onSelectPair }: Props) {
  const WIDTH = 600;
  const HEIGHT = 500;
  const CX = WIDTH / 2;
  const CY = HEIGHT / 2;
  const RADIUS = 170;
  const NODE_R = 22;

  // Collect unique agent IDs from the relationship data
  const agentSet = new Set<string>();
  for (const r of relationships) {
    agentSet.add(r.agent_id);
    agentSet.add(r.target_agent_id);
  }
  const agents = Array.from(agentSet);

  // Position agents evenly around the circle
  const positions: Record<string, { x: number; y: number }> = {};
  agents.forEach((agentId, i) => {
    const angle = (2 * Math.PI * i) / agents.length - Math.PI / 2;
    positions[agentId] = {
      x: CX + RADIUS * Math.cos(angle),
      y: CY + RADIUS * Math.sin(angle),
    };
  });

  // De-duplicate edges: keep the strongest sentiment for each pair
  const edgeMap = new Map<string, Relationship>();
  for (const r of relationships) {
    const key = [r.agent_id, r.target_agent_id].sort().join("|");
    const existing = edgeMap.get(key);
    if (!existing || r.interaction_count > existing.interaction_count) {
      edgeMap.set(key, r);
    }
  }
  const edges = Array.from(edgeMap.values());

  if (agents.length === 0) {
    return (
      <p className="text-sm text-foreground/50 py-8 text-center">
        No relationship data available.
      </p>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full max-w-full"
      aria-label="Social graph showing agent relationships"
    >
      {/* Edges */}
      {edges.map((r) => {
        const a = positions[r.agent_id];
        const b = positions[r.target_agent_id];
        if (!a || !b) return null;
        const color = sentimentColor(Number(r.sentiment_score ?? 0));
        const thickness = edgeThickness(r.interaction_count);
        const key = `${r.agent_id}-${r.target_agent_id}`;
        return (
          <line
            key={key}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke={color}
            strokeWidth={thickness}
            strokeOpacity={0.7}
            className="cursor-pointer hover:stroke-opacity-100 transition-all"
            onClick={() => onSelectPair(r.agent_id, r.target_agent_id)}
          >
            <title>
              {r.agent_id} ↔ {r.target_agent_id} | sentiment:{" "}
              {Number(r.sentiment_score ?? 0).toFixed(2)} | interactions: {r.interaction_count}
            </title>
          </line>
        );
      })}

      {/* Nodes */}
      {agents.map((agentId) => {
        const pos = positions[agentId];
        if (!pos) return null;
        const color = AGENT_COLORS[agentId.toLowerCase()] ?? DEFAULT_COLOR;
        const label = agentId.charAt(0).toUpperCase() + agentId.slice(1);

        // Label position: push label outward from center
        const dx = pos.x - CX;
        const dy = pos.y - CY;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const labelOffset = NODE_R + 10;
        const lx = pos.x + (dx / dist) * labelOffset;
        const ly = pos.y + (dy / dist) * labelOffset;
        const textAnchor =
          Math.abs(dx) < 20 ? "middle" : dx > 0 ? "start" : "end";
        const dominantBaseline =
          Math.abs(dy) < 20 ? "middle" : dy > 0 ? "hanging" : "auto";

        return (
          <g key={agentId}>
            {/* Glow ring */}
            <circle
              cx={pos.x}
              cy={pos.y}
              r={NODE_R + 3}
              fill="none"
              stroke={color}
              strokeWidth={1}
              strokeOpacity={0.3}
            />
            {/* Node circle */}
            <circle
              cx={pos.x}
              cy={pos.y}
              r={NODE_R}
              fill="#0a0a0a"
              stroke={color}
              strokeWidth={2}
            />
            {/* Initial letter */}
            <text
              x={pos.x}
              y={pos.y}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={12}
              fontFamily="monospace"
              fill={color}
              fontWeight="bold"
            >
              {agentId.charAt(0).toUpperCase()}
            </text>
            {/* Name label */}
            <text
              x={lx}
              y={ly}
              textAnchor={textAnchor}
              dominantBaseline={dominantBaseline}
              fontSize={10}
              fontFamily="monospace"
              fill={color}
              fillOpacity={0.8}
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

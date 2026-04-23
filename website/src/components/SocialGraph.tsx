"use client";

import { useState } from "react";
import type { Relationship } from "@/types/admin";
import { AGENT_COLORS } from "@/lib/agent-data";

const DEFAULT_COLOR = "#666666";
const MIN_INTERACTION_THRESHOLD = 3;
const MIN_SENTIMENT_THRESHOLD = 0.05;

function sentimentColor(score: number): string {
  if (score > 0.3) return "#4ade80";
  if (score > 0) return "#86efac";
  if (score > -0.3) return "#9ca3af";
  if (score > -0.6) return "#f87171";
  return "#ef4444";
}

function sentimentLabel(score: number): string {
  if (score > 0.3) return "positive";
  if (score > 0) return "slightly positive";
  if (score > -0.3) return "neutral";
  if (score > -0.6) return "slightly negative";
  return "negative";
}

function edgeThickness(interactionCount: number): number {
  const clamped = Math.min(Math.max(interactionCount, 0), 50);
  return 1 + (clamped / 50) * 3;
}

interface Props {
  relationships: Relationship[];
  onSelectPair: (agentA: string, agentB: string) => void;
}

export default function SocialGraph({ relationships, onSelectPair }: Props) {
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });

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
  const allEdges = Array.from(edgeMap.values());

  // Filter low-signal edges: require BOTH meaningful interaction AND non-trivial sentiment
  const edges = allEdges.filter(
    (r) =>
      r.interaction_count >= MIN_INTERACTION_THRESHOLD &&
      Math.abs(Number(r.sentiment_score ?? 0)) > MIN_SENTIMENT_THRESHOLD,
  );
  const filteredCount = allEdges.length - edges.length;

  // Compute max interaction count for opacity scaling
  const maxInteraction = Math.max(1, ...edges.map((r) => r.interaction_count));

  if (agents.length === 0) {
    return (
      <p className="text-sm text-foreground/50 py-8 text-center">
        No relationship data available.
      </p>
    );
  }

  const hoveredRelationship = hoveredEdge
    ? edges.find(
        (r) =>
          `${r.agent_id}-${r.target_agent_id}` === hoveredEdge,
      )
    : null;

  return (
    <div>
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
          const score = Number(r.sentiment_score ?? 0);
          const color = sentimentColor(score);
          const thickness = edgeThickness(r.interaction_count);
          const key = `${r.agent_id}-${r.target_agent_id}`;
          const opacity =
            0.3 + 0.7 * (r.interaction_count / maxInteraction);
          const isHovered = hoveredEdge === key;
          return (
            <line
              key={key}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke={color}
              strokeWidth={isHovered ? thickness + 1 : thickness}
              strokeOpacity={isHovered ? 1 : opacity}
              className="cursor-pointer transition-all"
              onClick={() => onSelectPair(r.agent_id, r.target_agent_id)}
              onMouseEnter={(e) => {
                setHoveredEdge(key);
                const svg = e.currentTarget.ownerSVGElement;
                if (svg) {
                  const pt = svg.createSVGPoint();
                  pt.x = (a.x + b.x) / 2;
                  pt.y = (a.y + b.y) / 2;
                  setHoverPos({ x: pt.x, y: pt.y });
                }
              }}
              onMouseLeave={() => setHoveredEdge(null)}
            />
          );
        })}

        {/* Hover tooltip */}
        {hoveredRelationship && (
          <g
            transform={`translate(${hoverPos.x}, ${hoverPos.y - 35})`}
            pointerEvents="none"
          >
            <rect
              x={-80}
              y={-12}
              width={160}
              height={40}
              rx={4}
              fill="#1a1a2e"
              stroke="#333"
              strokeWidth={1}
              opacity={0.95}
            />
            <text
              x={0}
              y={2}
              textAnchor="middle"
              fontSize={9}
              fontFamily="monospace"
              fill="#e0e0e0"
            >
              {hoveredRelationship.agent_id} ↔{" "}
              {hoveredRelationship.target_agent_id}
            </text>
            <text
              x={0}
              y={18}
              textAnchor="middle"
              fontSize={8}
              fontFamily="monospace"
              fill={sentimentColor(
                Number(hoveredRelationship.sentiment_score ?? 0),
              )}
            >
              {sentimentLabel(
                Number(hoveredRelationship.sentiment_score ?? 0),
              )}{" "}
              ({Number(hoveredRelationship.sentiment_score ?? 0).toFixed(2)}) |{" "}
              {hoveredRelationship.interaction_count} interactions
            </text>
          </g>
        )}

        {/* Nodes */}
        {agents.map((agentId) => {
          const pos = positions[agentId];
          if (!pos) return null;
          const color =
            AGENT_COLORS[agentId.toLowerCase()] ?? DEFAULT_COLOR;
          const label =
            agentId.charAt(0).toUpperCase() + agentId.slice(1);

          const dx = pos.x - CX;
          const dy = pos.y - CY;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const labelOffset = NODE_R + 10;
          const lx = pos.x + (dx / dist) * labelOffset;
          const ly = pos.y + (dy / dist) * labelOffset;
          const textAnchor =
            Math.abs(dx) < 20 ? "middle" : dx > 0 ? "start" : "end";
          const dominantBaseline =
            Math.abs(dy) < 20
              ? "middle"
              : dy > 0
                ? "hanging"
                : "auto";

          return (
            <g key={agentId}>
              <circle
                cx={pos.x}
                cy={pos.y}
                r={NODE_R + 3}
                fill="none"
                stroke={color}
                strokeWidth={1}
                strokeOpacity={0.3}
              />
              <circle
                cx={pos.x}
                cy={pos.y}
                r={NODE_R}
                fill="#0a0a0a"
                stroke={color}
                strokeWidth={2}
              />
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

      {/* Legend and summary */}
      <div className="flex items-center justify-between mt-2 px-2">
        <div className="flex items-center gap-3 text-[10px] text-foreground/40">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-[#4ade80]" /> positive
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-[#9ca3af]" /> neutral
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-[#ef4444]" /> negative
          </span>
          <span className="text-foreground/30">|</span>
          <span>thickness = interaction count</span>
        </div>
        {filteredCount > 0 && (
          <p className="text-[10px] text-foreground/30">
            Showing {edges.length} of {allEdges.length} relationships
            (filtered {filteredCount} with no meaningful interaction)
          </p>
        )}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { fetchRelationshipDetail } from "@/lib/admin-api";
import type { RelationshipDetail } from "@/types/admin";

interface Props {
  agentA: string;
  agentB: string;
  simulationId: string;
}

export default function RelationshipTimeline({ agentA, agentB, simulationId }: Props) {
  const [detail, setDetail] = useState<RelationshipDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setDetail(null);
    fetchRelationshipDetail(agentA, agentB, simulationId)
      .then(setDetail)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load relationship"),
      )
      .finally(() => setLoading(false));
  }, [agentA, agentB, simulationId]);

  if (loading) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }

  if (!detail) return null;

  const evolution = detail.evolution ?? [];
  const hasEvolution = evolution.length >= 2;

  // SVG chart constants
  const W = 560;
  const H = 160;
  const PAD = { top: 12, right: 16, bottom: 32, left: 36 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  // Map sentiment -1..1 to y coordinate
  function toY(score: number) {
    return PAD.top + innerH * (1 - (score + 1) / 2);
  }

  const zeroY = toY(0);

  // Build SVG path points
  let positivePath = "";
  let negativePath = "";

  if (hasEvolution) {
    const points = evolution.map((p, i) => ({
      x: PAD.left + (i / (evolution.length - 1)) * innerW,
      y: toY(p.sentiment_score),
      score: p.sentiment_score,
    }));

    // Positive area (above zero)
    positivePath = [
      `M ${points[0].x},${zeroY}`,
      ...points.map((p) => `L ${p.x},${Math.min(p.y, zeroY)}`),
      `L ${points[points.length - 1].x},${zeroY}`,
      "Z",
    ].join(" ");

    // Negative area (below zero)
    negativePath = [
      `M ${points[0].x},${zeroY}`,
      ...points.map((p) => `L ${p.x},${Math.max(p.y, zeroY)}`),
      `L ${points[points.length - 1].x},${zeroY}`,
      "Z",
    ].join(" ");

    // X-axis tick labels (up to 5)
    const tickCount = Math.min(5, evolution.length);
    const ticks = Array.from({ length: tickCount }, (_, i) => {
      const idx =
        tickCount === 1 ? 0 : Math.round((i / (tickCount - 1)) * (evolution.length - 1));
      return { x: points[idx].x, label: new Date(evolution[idx].timestamp).toLocaleDateString() };
    });

    void ticks;
  }

  // Y-axis labels
  const yLabels = [
    { score: 1, label: "+1" },
    { score: 0, label: "0" },
    { score: -1, label: "-1" },
  ];

  return (
    <div className="rounded-lg border border-border bg-surface p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="font-pixel text-sm text-neon-cyan">
          {agentA} ↔ {agentB}
        </h3>
        <div className="flex gap-4 text-xs text-foreground/50 font-mono">
          <span>
            sentiment:{" "}
            <span
              style={{
                color:
                  detail.sentiment_score > 0.3
                    ? "#4ade80"
                    : detail.sentiment_score > -0.3
                      ? "#9ca3af"
                      : "#ef4444",
              }}
            >
              {detail.sentiment_score >= 0 ? "+" : ""}
              {detail.sentiment_score.toFixed(2)}
            </span>
          </span>
          <span>trust: {detail.trust_score.toFixed(2)}</span>
          <span>interactions: {detail.interaction_count}</span>
        </div>
      </div>

      {/* Summary */}
      {detail.relationship_summary && (
        <p className="text-xs text-foreground/60 italic">
          {detail.relationship_summary}
        </p>
      )}

      {/* Sentiment timeline chart */}
      {hasEvolution ? (
        <div>
          <p className="text-xs text-foreground/40 mb-2">Sentiment over time</p>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full"
            aria-label="Sentiment timeline"
          >
            {/* Zero line */}
            <line
              x1={PAD.left}
              y1={zeroY}
              x2={W - PAD.right}
              y2={zeroY}
              stroke="#9ca3af"
              strokeWidth={0.5}
              strokeDasharray="4 4"
            />

            {/* Positive fill */}
            <path d={positivePath} fill="#4ade80" fillOpacity={0.2} />

            {/* Negative fill */}
            <path d={negativePath} fill="#ef4444" fillOpacity={0.2} />

            {/* Line */}
            <polyline
              points={evolution
                .map((p, i) => {
                  const x = PAD.left + (i / (evolution.length - 1)) * innerW;
                  const y = toY(p.sentiment_score);
                  return `${x},${y}`;
                })
                .join(" ")}
              fill="none"
              stroke="#00f0ff"
              strokeWidth={1.5}
            />

            {/* Y-axis labels */}
            {yLabels.map(({ score, label }) => (
              <text
                key={label}
                x={PAD.left - 4}
                y={toY(score)}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={9}
                fontFamily="monospace"
                fill="#9ca3af"
              >
                {label}
              </text>
            ))}

            {/* X-axis timestamps */}
            {evolution.length > 0 && (
              <>
                <text
                  x={PAD.left}
                  y={H - 4}
                  textAnchor="start"
                  fontSize={8}
                  fontFamily="monospace"
                  fill="#9ca3af"
                >
                  {new Date(evolution[0].timestamp).toLocaleDateString()}
                </text>
                <text
                  x={W - PAD.right}
                  y={H - 4}
                  textAnchor="end"
                  fontSize={8}
                  fontFamily="monospace"
                  fill="#9ca3af"
                >
                  {new Date(
                    evolution[evolution.length - 1].timestamp,
                  ).toLocaleDateString()}
                </text>
              </>
            )}
          </svg>
        </div>
      ) : evolution.length === 1 ? (
        <p className="text-xs text-foreground/40">
          Single data point — no trend to display.
        </p>
      ) : (
        <p className="text-xs text-foreground/40">
          No evolution history available.
        </p>
      )}

      {/* Recent events */}
      {evolution.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-foreground/40">Recent events</p>
          {evolution
            .filter((e) => e.event)
            .slice(-5)
            .reverse()
            .map((e, i) => (
              <div
                key={i}
                className="flex gap-3 text-xs text-foreground/50"
              >
                <span className="text-foreground/30 tabular-nums shrink-0">
                  {new Date(e.timestamp).toLocaleString()}
                </span>
                <span>{e.event}</span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

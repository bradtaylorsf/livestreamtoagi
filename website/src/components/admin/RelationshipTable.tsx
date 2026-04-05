"use client";

import { useState } from "react";
import type { Relationship } from "@/types/admin";

type SortKey = "sentiment_score" | "interaction_count" | "trust_score";
type SortDir = "asc" | "desc";

function sentimentColor(score: number): string {
  if (score > 0.3) return "#4ade80";
  if (score > 0) return "#86efac";
  if (score > -0.3) return "#9ca3af";
  if (score > -0.6) return "#f87171";
  return "#ef4444";
}

interface Props {
  relationships: Relationship[];
  onSelectPair: (agentA: string, agentB: string) => void;
}

export default function RelationshipTable({ relationships, onSelectPair }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("interaction_count");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const sorted = [...relationships].sort((a, b) => {
    const av = a[sortKey] as number;
    const bv = b[sortKey] as number;
    return sortDir === "asc" ? av - bv : bv - av;
  });

  function SortIndicator({ col }: { col: SortKey }) {
    if (col !== sortKey) return <span className="ml-1 text-foreground/20">↕</span>;
    return (
      <span className="ml-1 text-neon-cyan">
        {sortDir === "asc" ? "↑" : "↓"}
      </span>
    );
  }

  if (sorted.length === 0) {
    return (
      <p className="text-sm text-foreground/50 py-8 text-center">
        No relationship data available.
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-foreground/50">
            <th className="px-4 py-2 font-medium">Agent A</th>
            <th className="px-4 py-2 font-medium">Agent B</th>
            <th
              className="px-4 py-2 font-medium cursor-pointer select-none hover:text-foreground/70"
              onClick={() => handleSort("sentiment_score")}
            >
              Sentiment
              <SortIndicator col="sentiment_score" />
            </th>
            <th
              className="px-4 py-2 font-medium cursor-pointer select-none hover:text-foreground/70"
              onClick={() => handleSort("trust_score")}
            >
              Trust
              <SortIndicator col="trust_score" />
            </th>
            <th
              className="px-4 py-2 font-medium cursor-pointer select-none hover:text-foreground/70 text-right"
              onClick={() => handleSort("interaction_count")}
            >
              Interactions
              <SortIndicator col="interaction_count" />
            </th>
            <th className="px-4 py-2 font-medium">Summary</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const color = sentimentColor(r.sentiment_score);
            const barWidth = Math.abs(r.sentiment_score) * 100;
            const barLeft = r.sentiment_score < 0 ? (1 - Math.abs(r.sentiment_score)) * 50 : 50;

            return (
              <tr
                key={`${r.agent_id}-${r.target_agent_id}-${i}`}
                className="border-b border-border last:border-0 hover:bg-surface-light transition-colors cursor-pointer"
                onClick={() => onSelectPair(r.agent_id, r.target_agent_id)}
              >
                <td className="px-4 py-2 font-mono text-foreground/80">
                  {r.agent_id}
                </td>
                <td className="px-4 py-2 font-mono text-foreground/80">
                  {r.target_agent_id}
                </td>
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span
                      className="font-mono text-xs tabular-nums"
                      style={{ color }}
                    >
                      {r.sentiment_score >= 0 ? "+" : ""}
                      {r.sentiment_score.toFixed(2)}
                    </span>
                    <div className="relative w-16 h-2 rounded-full bg-foreground/10 overflow-hidden">
                      <div
                        className="absolute top-0 h-2 rounded-full"
                        style={{
                          left: `${barLeft}%`,
                          width: `${barWidth / 2}%`,
                          backgroundColor: color,
                        }}
                      />
                    </div>
                  </div>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-foreground/60">
                  {r.trust_score.toFixed(2)}
                </td>
                <td className="px-4 py-2 text-right font-mono text-foreground/60">
                  {r.interaction_count}
                </td>
                <td className="px-4 py-2 text-xs text-foreground/50 max-w-xs truncate">
                  {r.relationship_summary ?? "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

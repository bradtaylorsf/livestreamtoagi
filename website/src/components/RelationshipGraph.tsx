"use client";

import Link from "next/link";
import { getAllAgents } from "@/lib/agent-data";

// Static adjacency scores derived from agent configs
const ADJACENCY_SCORES: Record<string, Record<string, number>> = {
  vera: { rex: 0.7, aurora: 0.6, sentinel: 0.8, pixel: 0.5, fork: 0.5, grok: 0.6 },
  rex: { vera: 0.5, fork: 0.8, aurora: 0.3, sentinel: 0.4, pixel: 0.4, grok: 0.3 },
  aurora: { rex: 0.6, vera: 0.5, pixel: 0.7, grok: 0.5, fork: 0.4, sentinel: 0.4 },
  pixel: { vera: 0.5, aurora: 0.7, grok: 0.6, rex: 0.4, fork: 0.3, sentinel: 0.3 },
  fork: { rex: 0.8, grok: 0.6, vera: 0.5, aurora: 0.4, sentinel: 0.5, pixel: 0.3 },
  sentinel: { vera: 0.8, rex: 0.5, grok: 0.6, aurora: 0.5, fork: 0.4, pixel: 0.3 },
  grok: { fork: 0.7, aurora: 0.6, vera: 0.5, pixel: 0.6, rex: 0.4, sentinel: 0.5 },
  management: {},
  alpha: {},
};

interface Props {
  agentId: string;
}

export default function RelationshipGraph({ agentId }: Props) {
  const allAgents = getAllAgents();
  const relationships = ADJACENCY_SCORES[agentId] ?? {};
  const sortedRelationships = Object.entries(relationships).sort(
    ([, a], [, b]) => b - a,
  );

  if (sortedRelationships.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        Relationship data not available for this agent.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {sortedRelationships.map(([targetId, score]) => {
        const target = allAgents.find((a) => a.id === targetId);
        if (!target) return null;

        const barWidth = Math.round(score * 100);

        return (
          <Link
            key={targetId}
            href={`/agents/${targetId}`}
            className="flex items-center gap-3 rounded border border-border bg-surface p-3 hover:bg-surface-light transition-colors"
          >
            <div
              className="w-8 h-8 rounded shrink-0 flex items-center justify-center font-pixel text-[10px] text-white/80"
              style={{ backgroundColor: target.color }}
            >
              {target.name[0]}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between mb-1">
                <span
                  className="text-sm font-medium"
                  style={{ color: target.color }}
                >
                  {target.name}
                </span>
                <span className="text-xs text-foreground/40">
                  {score.toFixed(1)}
                </span>
              </div>
              <div className="h-1.5 bg-surface-light rounded overflow-hidden">
                <div
                  className="h-full rounded"
                  style={{
                    width: `${barWidth}%`,
                    backgroundColor: target.color,
                    opacity: 0.6,
                  }}
                />
              </div>
            </div>
          </Link>
        );
      })}
    </div>
  );
}

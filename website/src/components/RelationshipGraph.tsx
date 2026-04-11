"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { getAllAgents } from "@/lib/agent-data";
import { getAgentRelationships } from "@/lib/api";
import type { AgentRelationshipResponse } from "@/types";

interface Props {
  agentId: string;
}

export default function RelationshipGraph({ agentId }: Props) {
  const [relationships, setRelationships] = useState<AgentRelationshipResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const allAgents = getAllAgents();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentRelationships(agentId)
      .then((data) => {
        if (!cancelled) setRelationships(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load relationships");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [agentId]);

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <span className="text-sm text-foreground/40">Loading relationships...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load relationships</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getAgentRelationships(agentId)
              .then(setRelationships)
              .catch((err) => setError(err instanceof Error ? err.message : "Failed to load relationships"))
              .finally(() => setLoading(false));
          }}
          className="text-xs text-neon-cyan hover:text-neon-cyan/80 mt-2"
        >
          Retry
        </button>
      </div>
    );
  }

  if (relationships.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        Relationship data not available for this agent.
      </p>
    );
  }

  const sorted = [...relationships].sort(
    (a, b) => b.sentiment_score - a.sentiment_score,
  );

  return (
    <div className="space-y-3">
      {sorted.map((rel) => {
        const target = allAgents.find((a) => a.id === rel.target_agent_id);
        if (!target) return null;

        const barWidth = Math.round(Math.abs(rel.sentiment_score) * 100);

        return (
          <Link
            key={rel.id}
            href={`/agents/${rel.target_agent_id}`}
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
                  {rel.sentiment_score.toFixed(1)}
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
              {rel.interaction_count > 0 && (
                <span className="text-xs text-foreground/30 mt-1 block">
                  {rel.interaction_count} interactions
                </span>
              )}
            </div>
          </Link>
        );
      })}
    </div>
  );
}

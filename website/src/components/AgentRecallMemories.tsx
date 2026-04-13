"use client";

import { useState, useEffect } from "react";
import { getAgentRecallMemories } from "@/lib/api";
import type { RecallMemoryPublic } from "@/types";

interface Props {
  agentId: string;
}

export default function AgentRecallMemories({ agentId }: Props) {
  const [memories, setMemories] = useState<RecallMemoryPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentRecallMemories(agentId)
      .then((result) => {
        if (!cancelled) setMemories(result.items);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load recall memories",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [agentId]);

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <span className="text-sm text-foreground/40">
          Loading recall memories...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load recall memories</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getAgentRecallMemories(agentId)
              .then((result) => setMemories(result.items))
              .catch((err) =>
                setError(
                  err instanceof Error
                    ? err.message
                    : "Failed to load recall memories",
                ),
              )
              .finally(() => setLoading(false));
          }}
          className="text-xs text-neon-cyan hover:text-neon-cyan/80 mt-2"
        >
          Retry
        </button>
      </div>
    );
  }

  if (memories.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        No recall memories yet. These will populate as the agent participates in
        conversations.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {memories.map((memory) => (
        <div
          key={memory.id}
          className="rounded border border-border bg-surface p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            {memory.created_at && (
              <time className="text-xs text-foreground/40">
                {memory.created_at}
              </time>
            )}
            {memory.event_type && (
              <span className="text-xs text-neon-cyan">
                {memory.event_type}
              </span>
            )}
            {memory.importance_score != null && (
              <span className="text-xs text-foreground/30">
                importance: {memory.importance_score.toFixed(1)}
              </span>
            )}
          </div>
          <p className="text-sm text-foreground/70">{memory.summary}</p>
        </div>
      ))}
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { getAgentEvolution } from "@/lib/api";
import type { AgentEvolutionResponse } from "@/types";

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  manual: { label: "Manual", color: "text-neon-cyan" },
  system: { label: "System", color: "text-neon-yellow" },
  evolution: { label: "Evolution", color: "text-neon-magenta" },
};

interface Props {
  agentId: string;
}

export default function EvolutionTimeline({ agentId }: Props) {
  const [events, setEvents] = useState<AgentEvolutionResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentEvolution(agentId)
      .then((data) => {
        if (!cancelled) setEvents(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load evolution history");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [agentId]);

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <span className="text-sm text-foreground/40">Loading evolution history...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load evolution history</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getAgentEvolution(agentId)
              .then(setEvents)
              .catch((err) => setError(err instanceof Error ? err.message : "Failed to load evolution history"))
              .finally(() => setLoading(false));
          }}
          className="text-xs text-neon-cyan hover:text-neon-cyan/80 mt-2"
        >
          Retry
        </button>
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        No evolution history yet.
      </p>
    );
  }

  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />
      <div className="space-y-6">
        {events.map((event) => {
          const sourceInfo = SOURCE_LABELS[event.source] ?? {
            label: event.source,
            color: "text-foreground/50",
          };
          return (
            <div key={event.id} className="relative pl-10">
              <div className="absolute left-2.5 top-1.5 w-3 h-3 rounded-full bg-surface-light border-2 border-border" />
              <div className="flex items-center gap-2 mb-1">
                <time className="text-xs text-foreground/40">
                  {event.created_at ?? "Unknown"}
                </time>
                <span className={`text-xs ${sourceInfo.color}`}>
                  {sourceInfo.label}
                </span>
                <span className="text-xs text-foreground/30">
                  v{event.version}
                </span>
              </div>
              <p className="text-sm text-foreground/70">
                {event.change_reason ?? "Configuration update"}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

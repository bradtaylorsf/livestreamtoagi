"use client";

import { useState, useEffect } from "react";
import { getAgentCoreMemory } from "@/lib/api";
import type { CoreMemoryPublic } from "@/types";

interface Props {
  agentId: string;
}

export default function AgentCoreMemory({ agentId }: Props) {
  const [data, setData] = useState<CoreMemoryPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentCoreMemory(agentId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof Error ? err.message : "Failed to load core memory",
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
          Loading core memory...
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load core memory</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getAgentCoreMemory(agentId)
              .then(setData)
              .catch((err) =>
                setError(
                  err instanceof Error
                    ? err.message
                    : "Failed to load core memory",
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

  if (!data?.current_content) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        No core memory data yet. This will populate once the simulation runs.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {data.last_updated && (
        <p className="text-xs text-foreground/40">
          Last updated: {data.last_updated}
        </p>
      )}
      <div className="rounded border border-border bg-surface p-4">
        <pre className="text-sm text-foreground/70 whitespace-pre-wrap font-mono leading-relaxed">
          {data.current_content}
        </pre>
      </div>
    </div>
  );
}

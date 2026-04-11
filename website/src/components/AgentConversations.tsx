"use client";

import { useState, useEffect } from "react";
import { getAgentConversations } from "@/lib/api";
import type { AgentConversation } from "@/types";

const PAGE_SIZE = 20;

interface Props {
  agentId: string;
}

export default function AgentConversations({ agentId }: Props) {
  const [conversations, setConversations] = useState<AgentConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentConversations(agentId, { limit: PAGE_SIZE, offset })
      .then((data) => {
        if (!cancelled) {
          setConversations(data.items);
          setTotal(data.total);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load conversations");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [agentId, offset]);

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <span className="text-sm text-foreground/40">Loading conversations...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load conversations</p>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            getAgentConversations(agentId, { limit: PAGE_SIZE, offset })
              .then((data) => {
                setConversations(data.items);
                setTotal(data.total);
              })
              .catch((err) => setError(err instanceof Error ? err.message : "Failed to load conversations"))
              .finally(() => setLoading(false));
          }}
          className="text-xs text-neon-cyan hover:text-neon-cyan/80 mt-2"
        >
          Retry
        </button>
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8">
        No conversations yet.
      </p>
    );
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <div className="space-y-3">
        {conversations.map((conv) => (
          <div
            key={conv.id}
            className="rounded border border-border bg-surface p-4"
          >
            <div className="flex items-center justify-between mb-2">
              <time className="text-xs text-foreground/40">
                {conv.started_at ?? "Unknown date"}
              </time>
              <div className="flex gap-1">
                {conv.participating_agents.map((name) => (
                  <span
                    key={name}
                    className="text-xs rounded bg-surface-light px-2 py-0.5 text-foreground/50"
                  >
                    {name}
                  </span>
                ))}
              </div>
            </div>
            <p className="text-sm text-foreground/70">
              {conv.topics_discussed?.join(", ") ?? conv.trigger_type}
            </p>
            {conv.turn_count > 0 && (
              <span className="text-xs text-foreground/30 mt-1 block">
                {conv.turn_count} turns
              </span>
            )}
          </div>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4 mt-4">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="text-xs text-neon-cyan hover:text-neon-cyan/80 disabled:text-foreground/20 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-xs text-foreground/40">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="text-xs text-neon-cyan hover:text-neon-cyan/80 disabled:text-foreground/20 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

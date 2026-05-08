"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { ConversationSummary } from "@/types";
import { getConversations } from "@/lib/api";
import { getAgentData } from "@/lib/agent-data";
import { useSimulation } from "@/lib/SimulationContext";
import { SkeletonCardList } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";

function ConversationCard({ conv }: { conv: ConversationSummary }) {
  const sim = useSimulation();
  const href = sim.simulationId
    ? `/simulations/${sim.simulationId}/conversations/${conv.id}`
    : `/conversations/${conv.id}`;
  return (
    <Link
      href={href}
      className="block rounded border border-border bg-surface p-4 hover:bg-surface-light transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="inline-block rounded bg-neon-cyan/10 px-2 py-0.5 text-xs text-neon-cyan">
            {conv.trigger_type}
          </span>
          {conv.location && (
            <span className="text-xs text-foreground/40">{conv.location}</span>
          )}
        </div>
        <span className="text-xs text-foreground/40">
          {conv.turn_count} turns
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-2">
        {conv.participating_agents.map((agentId) => {
          const agent = getAgentData(agentId);
          return (
            <span
              key={agentId}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs"
              style={{
                backgroundColor: agent
                  ? `${agent.color}15`
                  : "rgba(255,255,255,0.05)",
                color: agent?.color || "inherit",
              }}
            >
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: agent?.color || "#888" }}
              />
              {agent?.name || agentId}
            </span>
          );
        })}
      </div>

      {conv.topics_discussed && conv.topics_discussed.length > 0 && (
        <p className="text-xs text-foreground/50 truncate">
          Topics: {conv.topics_discussed.join(", ")}
        </p>
      )}

      {conv.started_at && (
        <time className="text-xs text-foreground/30 mt-1 block">
          {new Date(conv.started_at).toLocaleString()}
        </time>
      )}
    </Link>
  );
}

const PAGE_SIZE = 20;

export default function ScopedConversationsPage() {
  const sim = useSimulation();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const showSkeleton = useDelayedFlag(loading);

  const fetchConversations = useCallback(async () => {
    if (!sim.simulationId) return;
    setLoading(true);
    try {
      const data = await getConversations({
        simulation_id: sim.simulationId,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setConversations(data.items);
      setTotal(data.total);
    } catch {
      // API not available yet
    } finally {
      setLoading(false);
    }
  }, [sim.simulationId, page]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <nav className="text-xs text-foreground/40 mb-4" aria-label="Breadcrumb">
        <Link
          href={`/simulations/${sim.simulationId ?? ""}`}
          className="hover:text-foreground/60"
        >
          Simulation {(sim.simulationId ?? "").slice(0, 8)}
        </Link>
        {" / "}
        <span className="text-foreground/60">Conversations</span>
      </nav>

      <h1 className="font-pixel text-xl text-neon-cyan mb-4">CONVERSATIONS</h1>
      <p className="text-foreground/60 mb-6">
        Conversations recorded during this simulation.
      </p>

      {loading ? (
        showSkeleton ? <SkeletonCardList count={5} /> : null
      ) : conversations.length === 0 ? (
        <p className="text-foreground/50 text-sm">
          No conversations recorded yet.
        </p>
      ) : (
        <>
          <div className="space-y-3">
            {conversations.map((conv) => (
              <ConversationCard key={conv.id} conv={conv} />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="rounded border border-border px-3 py-1 text-sm text-foreground/60 hover:text-foreground disabled:opacity-30"
              >
                Previous
              </button>
              <span className="text-xs text-foreground/40">
                Page {page + 1} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="rounded border border-border px-3 py-1 text-sm text-foreground/60 hover:text-foreground disabled:opacity-30"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

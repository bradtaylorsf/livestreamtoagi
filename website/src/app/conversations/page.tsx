"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { ConversationSummary } from "@/types";
import { getConversations, getSimulations, type PublicSimulation } from "@/lib/api";
import { getAgentData } from "@/lib/agent-data";
import { useCurrentSimulationId } from "@/lib/simulation-store";

function ConversationCard({ conv }: { conv: ConversationSummary }) {
  return (
    <Link
      key={conv.id}
      href={`/conversations/${conv.id}`}
      className="block rounded border border-border bg-surface p-4 hover:bg-surface-light transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="inline-block rounded bg-neon-cyan/10 px-2 py-0.5 text-xs text-neon-cyan">
            {conv.trigger_type}
          </span>
          {conv.location && (
            <span className="text-xs text-foreground/40">
              {conv.location}
            </span>
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

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [simulations, setSimulations] = useState<PublicSimulation[]>([]);
  const [storedSimId, setStoredSimId] = useCurrentSimulationId();
  const selectedSim = storedSimId ?? "";
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const limit = 20;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getSimulations({ limit: 100 });
        if (!cancelled) setSimulations(data.items);
      } catch {
        // simulations endpoint not available — leave dropdown empty
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchConversations = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getConversations({
        simulation_id: selectedSim || undefined,
        limit,
        offset: page * limit,
      });
      setConversations(data.items);
      setTotal(data.total);
    } catch {
      // API not available yet
    } finally {
      setLoading(false);
    }
  }, [page, selectedSim]);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const totalPages = Math.max(1, Math.ceil(total / limit));

  const simNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const sim of simulations) map.set(sim.id, sim.name);
    return map;
  }, [simulations]);

  const groupedBySim = useMemo(() => {
    if (selectedSim) return null;
    const groups = new Map<string, ConversationSummary[]>();
    for (const conv of conversations) {
      const key = conv.simulation_id || "unknown";
      const existing = groups.get(key);
      if (existing) {
        existing.push(conv);
      } else {
        groups.set(key, [conv]);
      }
    }
    return Array.from(groups.entries());
  }, [conversations, selectedSim]);

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-4">CONVERSATIONS</h1>
      <p className="text-foreground/60 mb-6">
        Browse past conversations and replay them turn-by-turn to see how speaker
        selection works.
      </p>

      <div className="mb-6">
        <label
          htmlFor="sim-filter"
          className="block text-xs uppercase tracking-wide text-foreground/50 mb-1"
        >
          Simulation
        </label>
        <select
          id="sim-filter"
          value={selectedSim}
          onChange={(e) => {
            setStoredSimId(e.target.value || null);
            setPage(0);
          }}
          className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
        >
          <option value="">All simulations</option>
          {simulations.map((sim) => (
            <option key={sim.id} value={sim.id}>
              {sim.name}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-foreground/50 text-sm">Loading conversations...</p>
      ) : conversations.length === 0 ? (
        <p className="text-foreground/50 text-sm">
          No conversations recorded yet.
        </p>
      ) : (
        <>
          {groupedBySim ? (
            <div className="space-y-6">
              {groupedBySim.map(([simId, items]) => (
                <section key={simId}>
                  <h2 className="font-pixel text-sm text-neon-cyan/80 mb-2">
                    {simId === "unknown"
                      ? "Unassigned"
                      : simNameById.get(simId) || simId}
                  </h2>
                  <div className="space-y-3">
                    {items.map((conv) => (
                      <ConversationCard key={conv.id} conv={conv} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              {conversations.map((conv) => (
                <ConversationCard key={conv.id} conv={conv} />
              ))}
            </div>
          )}

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

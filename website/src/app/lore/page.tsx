"use client";

import { useCallback, useEffect, useState } from "react";
import type { LoreEvent } from "@/types";
import { getLore } from "@/lib/api";
import { getAllAgents } from "@/lib/agent-data";
import LoreTimeline from "@/components/LoreTimeline";

const agents = getAllAgents();

export default function LorePage() {
  const [events, setEvents] = useState<LoreEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [agentFilter, setAgentFilter] = useState("");
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const limit = 20;

  const fetchLore = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getLore({
        limit,
        offset: page * limit,
        agent: agentFilter || undefined,
        event_type: eventTypeFilter || undefined,
      });
      setEvents(data.items);
      setTotal(data.total);
    } catch {
      // API not available yet
    } finally {
      setLoading(false);
    }
  }, [page, agentFilter, eventTypeFilter]);

  useEffect(() => {
    fetchLore();
  }, [fetchLore]);

  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-4">LORE</h1>
      <p className="text-foreground/60 mb-2">
        The history of the world, as written by its inhabitants.
      </p>

      {/* Unreliable narrators note */}
      <div className="rounded border border-neon-magenta/30 bg-neon-magenta/5 p-3 mb-6">
        <p className="text-xs text-foreground/70">
          <span className="font-pixel text-neon-magenta text-[10px]">NOTE</span>{" "}
          These events are described by the agents themselves — unreliable
          narrators with their own perspectives. Different agents may describe
          the same events quite differently.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <select
          value={agentFilter}
          onChange={(e) => {
            setAgentFilter(e.target.value);
            setPage(0);
          }}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by agent"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        <select
          value={eventTypeFilter}
          onChange={(e) => {
            setEventTypeFilter(e.target.value);
            setPage(0);
          }}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by event type"
        >
          <option value="">All Event Types</option>
          <option value="discovery">Discovery</option>
          <option value="conflict">Conflict</option>
          <option value="creation">Creation</option>
          <option value="milestone">Milestone</option>
          <option value="social">Social</option>
        </select>
      </div>

      {/* Timeline */}
      {loading ? (
        <p className="text-foreground/50 text-sm">Loading lore...</p>
      ) : (
        <>
          <LoreTimeline events={events} />

          {/* Pagination */}
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

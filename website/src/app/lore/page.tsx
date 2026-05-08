"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { LoreEvent } from "@/types";
import { getLore } from "@/lib/api";
import { getAllAgents } from "@/lib/agent-data";
import LoreTimeline from "@/components/LoreTimeline";
import SimulationPicker from "@/components/SimulationPicker";

const agents = getAllAgents();
const LIMIT = 20;

export default function LorePage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const agentFilter = searchParams.get("agent") ?? "";
  const eventTypeFilter = searchParams.get("event_type") ?? "";
  const simulationFilter = searchParams.get("simulation_id") ?? "";
  const page = Math.max(0, parseInt(searchParams.get("page") ?? "0", 10) || 0);

  const [events, setEvents] = useState<LoreEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const updateParams = useCallback(
    (updates: Record<string, string>) => {
      const sp = new URLSearchParams(searchParams.toString());
      for (const [key, val] of Object.entries(updates)) {
        if (val) sp.set(key, val);
        else sp.delete(key);
      }
      router.replace(`?${sp.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  const fetchLore = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getLore({
        limit: LIMIT,
        offset: page * LIMIT,
        agent: agentFilter || undefined,
        event_type: eventTypeFilter || undefined,
        simulation_id: simulationFilter || undefined,
      });
      setEvents(data.items);
      setTotal(data.total);
    } catch {
      // API not available yet
    } finally {
      setLoading(false);
    }
  }, [page, agentFilter, eventTypeFilter, simulationFilter]);

  useEffect(() => {
    fetchLore();
  }, [fetchLore]);

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));

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
          These events are described by the agents themselves &mdash; unreliable
          narrators with their own perspectives. Different agents may describe
          the same events quite differently.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        <SimulationPicker
          id="lore-sim-filter"
          value={simulationFilter}
          onChange={(v) => updateParams({ simulation_id: v, page: "" })}
          allLabel="All simulations"
        />

        <select
          value={agentFilter}
          onChange={(e) =>
            updateParams({ agent: e.target.value, page: "" })
          }
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
          onChange={(e) =>
            updateParams({ event_type: e.target.value, page: "" })
          }
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
                onClick={() =>
                  updateParams({ page: String(Math.max(0, page - 1)) })
                }
                disabled={page === 0}
                className="rounded border border-border px-3 py-1 text-sm text-foreground/60 hover:text-foreground disabled:opacity-30"
              >
                Previous
              </button>
              <span className="text-xs text-foreground/40">
                Page {page + 1} of {totalPages}
              </span>
              <button
                onClick={() =>
                  updateParams({
                    page: String(Math.min(totalPages - 1, page + 1)),
                  })
                }
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

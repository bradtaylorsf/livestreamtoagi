"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import StatusBadge from "@/components/admin/StatusBadge";
import { fetchSimulations } from "@/lib/admin-api";
import type { Simulation, SimulationStatus } from "@/types/admin";

const STATUS_OPTIONS: (SimulationStatus | "all")[] = [
  "all",
  "running",
  "completed",
  "failed",
  "cancelled",
];

function formatDuration(iso: string | null): string {
  if (!iso) return "—";
  // Python timedelta serializes as "HH:MM:SS" or seconds float
  const seconds = parseFloat(iso);
  if (!isNaN(seconds)) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  }
  return iso;
}

export default function SimulationsPage() {
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [filter, setFilter] = useState<SimulationStatus | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const status = filter === "all" ? undefined : filter;
        const res = await fetchSimulations(status);
        setSimulations(res.items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load simulations");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [filter]);

  return (
    <div className="max-w-6xl">
      <h1 className="font-pixel text-lg text-foreground mb-6">Simulations</h1>

      {/* Status Filter */}
      <div className="flex gap-2 mb-4">
        {STATUS_OPTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === s
                ? "bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40"
                : "bg-surface-light text-foreground/60 border border-border hover:text-foreground"
            }`}
          >
            {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-foreground/50">Loading...</p>
      ) : simulations.length === 0 ? (
        <p className="text-sm text-foreground/50">No simulations found.</p>
      ) : (
        <div className="rounded-lg border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Duration</th>
                <th className="px-4 py-2 font-medium text-right">Convos</th>
                <th className="px-4 py-2 font-medium text-right">Turns</th>
                <th className="px-4 py-2 font-medium text-right">Cost</th>
                <th className="px-4 py-2 font-medium text-right">Flags</th>
              </tr>
            </thead>
            <tbody>
              {simulations.map((sim) => (
                <tr
                  key={sim.id}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2">
                    <Link
                      href={`/admin/simulations/${sim.id}`}
                      className="text-neon-cyan hover:underline"
                    >
                      {sim.name}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={sim.status} />
                  </td>
                  <td className="px-4 py-2 text-foreground/60">
                    {sim.started_at
                      ? new Date(sim.started_at).toLocaleDateString()
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-foreground/60 font-mono text-xs">
                    {formatDuration(sim.real_duration)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {sim.total_conversations}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {sim.total_turns}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    ${parseFloat(sim.total_cost || "0").toFixed(4)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {sim.total_overseer_flags > 0 ? (
                      <span className="text-red-400 font-mono">
                        {sim.total_overseer_flags}
                      </span>
                    ) : (
                      <span className="text-foreground/40">0</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

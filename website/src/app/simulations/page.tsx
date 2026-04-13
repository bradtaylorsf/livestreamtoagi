"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getSimulations } from "@/lib/api";
import type { PublicSimulation } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  running: "bg-neon-green/20 text-neon-green border-neon-green/40",
  completed: "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40",
};

function formatDuration(iso: string | null): string {
  if (!iso) return "\u2014";
  const seconds = parseFloat(iso);
  if (!isNaN(seconds)) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    if (mins >= 60) {
      const hrs = Math.floor(mins / 60);
      return `${hrs}h ${mins % 60}m`;
    }
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  }
  return iso;
}

export default function SimulationsPage() {
  const [simulations, setSimulations] = useState<PublicSimulation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSimulations();
      setSimulations(res.items);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load simulations",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">SIMULATIONS</h1>
      <p className="text-foreground/60 mb-8">
        All simulation runs — explore agent conversations, eval scores,
        relationships, and reports.
      </p>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-foreground/50">Loading simulations...</p>
      ) : simulations.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-foreground/40">
            No simulations yet. They will appear here once runs complete.
          </p>
        </div>
      ) : (
        <div className="rounded border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th scope="col" className="px-4 py-2 font-medium">
                  Name
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Status
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Date
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Duration
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Convos
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Turns
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Cost
                </th>
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
                      href={`/simulations/${sim.id}`}
                      className="text-neon-cyan hover:underline"
                    >
                      {sim.name}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[sim.status] ?? "bg-surface-light text-foreground/60 border-border"}`}
                    >
                      {sim.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-foreground/60">
                    {sim.started_at
                      ? new Date(sim.started_at).toLocaleDateString()
                      : "\u2014"}
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

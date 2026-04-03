"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import SummaryCard from "@/components/admin/SummaryCard";
import StatusBadge from "@/components/admin/StatusBadge";
import { fetchDashboardStats, fetchSimulations } from "@/lib/admin-api";
import type { DashboardStats, Simulation } from "@/types/admin";

export default function AdminDashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recent, setRecent] = useState<Simulation[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [dashStats, sims] = await Promise.all([
          fetchDashboardStats(),
          fetchSimulations(),
        ]);
        setStats(dashStats);
        setRecent(sims.items.slice(0, 5));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load dashboard");
      }
    }
    load();
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  return (
    <div className="max-w-5xl">
      <h1 className="font-pixel text-lg text-foreground mb-6">Dashboard</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4 mb-8 lg:grid-cols-4">
        <SummaryCard
          label="Total Simulations"
          value={stats?.total_simulations ?? "—"}
        />
        <SummaryCard
          label="Last Run"
          value={
            stats?.last_run_date
              ? new Date(stats.last_run_date).toLocaleDateString()
              : "—"
          }
        />
        <SummaryCard
          label="Avg Cost"
          value={stats ? `$${stats.average_cost}` : "—"}
        />
        <SummaryCard
          label="Total Conversations"
          value={stats?.total_conversations ?? "—"}
        />
      </div>

      {/* Recent Simulations */}
      <h2 className="text-sm font-medium text-foreground/70 mb-3">
        Recent Simulations
      </h2>
      {recent.length === 0 && !error ? (
        <p className="text-sm text-foreground/50">No simulations yet.</p>
      ) : (
        <div className="rounded-lg border border-border bg-surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((sim) => (
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
                  <td className="px-4 py-2 text-right font-mono">
                    ${parseFloat(sim.total_cost || "0").toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {recent.length > 0 && (
        <Link
          href="/admin/simulations"
          className="inline-block mt-3 text-sm text-neon-cyan hover:underline"
        >
          View all simulations →
        </Link>
      )}
    </div>
  );
}

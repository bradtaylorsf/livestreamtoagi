"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulation } from "@/lib/api";
import type { PublicSimulationDetail } from "@/lib/api";

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

function SummaryCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-border bg-surface p-3">
      <p className="text-xs text-foreground/40 mb-1">{label}</p>
      <p className="text-lg font-mono text-foreground">{value}</p>
    </div>
  );
}

export default function SimulationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [sim, setSim] = useState<PublicSimulationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulation(id)
      .then(setSim)
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load simulation",
        ),
      );
  }, [id]);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
      </div>
    );
  }

  if (!sim) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-8">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <span className="text-foreground/60">{sim.name}</span>
      </div>

      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="font-pixel text-lg text-neon-cyan">{sim.name}</h1>
          <span
            className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[sim.status] ?? "bg-surface-light text-foreground/60 border-border"}`}
          >
            {sim.status}
          </span>
        </div>
        {sim.description && (
          <p className="text-sm text-foreground/60">{sim.description}</p>
        )}
        <div className="flex gap-4 mt-2 text-xs text-foreground/40">
          {sim.started_at && (
            <span>
              Started: {new Date(sim.started_at).toLocaleString()}
            </span>
          )}
          {sim.completed_at && (
            <span>
              Completed: {new Date(sim.completed_at).toLocaleString()}
            </span>
          )}
          <span>Real: {formatDuration(sim.real_duration)}</span>
          <span>Simulated: {formatDuration(sim.simulated_duration)}</span>
        </div>
      </div>

      {/* Sub-page Links */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link
          href={`/simulations/${id}/report`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Report
        </Link>
        <Link
          href={`/simulations/${id}/evals`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Eval Results
        </Link>
        <Link
          href={`/simulations/${id}/assertions`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Assertions
        </Link>
        <Link
          href={`/simulations/${id}/relationships`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Social Graph
        </Link>
        <Link
          href={`/simulations/${id}/snapshots`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Snapshots
        </Link>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <SummaryCard label="Conversations" value={sim.total_conversations} />
        <SummaryCard label="Turns" value={sim.total_turns} />
        <SummaryCard
          label="Tokens"
          value={sim.total_tokens.toLocaleString()}
        />
        <SummaryCard
          label="Cost"
          value={`$${parseFloat(sim.total_cost || "0").toFixed(4)}`}
        />
        <SummaryCard label="Artifacts" value={sim.total_artifacts} />
        <SummaryCard
          label="Management Flags"
          value={sim.total_overseer_flags}
        />
      </div>

      {/* Agent Participation */}
      {sim.agents_participated.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-foreground/70 mb-2">
            Agents Participated
          </h2>
          <div className="flex flex-wrap gap-2">
            {sim.agents_participated.map((agent) => (
              <Link
                key={agent}
                href={`/agents/${agent}`}
                className="rounded border border-border bg-surface-light px-2 py-1 text-xs text-foreground/70 hover:text-neon-cyan transition-colors"
              >
                {agent}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

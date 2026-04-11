"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import StatusBadge from "@/components/admin/StatusBadge";
import SummaryCard from "@/components/admin/SummaryCard";
import TimelineView from "@/components/admin/TimelineView";
import CostChart from "@/components/admin/CostChart";
import ConfigViewer from "@/components/admin/ConfigViewer";
import {
  fetchSimulation,
  fetchSimulationConversations,
  cloneSimulation,
  exportSimulationSnapshot,
  deleteSimulation,
} from "@/lib/admin-api";
import type { AgentConversation, Simulation } from "@/types/admin";

function formatDuration(iso: string | null): string {
  if (!iso) return "—";
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

export default function SimulationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [sim, setSim] = useState<Simulation | null>(null);
  const [convos, setConvos] = useState<AgentConversation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    fetchSimulation(id)
      .then(setSim)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load simulation"),
      );
    fetchSimulationConversations(id)
      .then((res) => setConvos(res.items))
      .catch(() => {});
  }, [id]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  if (!sim) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="max-w-6xl space-y-8">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/admin/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <span className="text-foreground/60">{sim.name}</span>
      </div>

      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="font-pixel text-lg text-foreground">{sim.name}</h1>
          <StatusBadge status={sim.status} />
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

      {/* Navigation Links */}
      <div className="flex items-center gap-3 flex-wrap">
        <Link
          href={`/admin/simulations/${id}/evals`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          View Eval Results
        </Link>
        <Link
          href={`/admin/simulations/${id}/assertions`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Assertions
        </Link>
        <Link
          href={`/admin/simulations/${id}/relationships`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Social Graph
        </Link>
        <Link
          href={`/admin/simulations/${id}/report`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Report
        </Link>
        <Link
          href={`/admin/simulations/${id}/snapshots`}
          className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
        >
          Snapshots
        </Link>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          disabled={actionLoading}
          onClick={async () => {
            setActionLoading(true);
            setActionMsg(null);
            try {
              const result = await cloneSimulation(id);
              setActionMsg(`Cloned! New simulation: ${result.name} (${result.id})`);
            } catch (err) {
              setActionMsg(`Clone failed: ${err instanceof Error ? err.message : "Unknown error"}`);
            } finally {
              setActionLoading(false);
            }
          }}
          className="rounded border border-green-500/60 px-3 py-1.5 text-xs text-green-400 hover:bg-green-500/10 transition-colors disabled:opacity-50"
        >
          Clone
        </button>
        <button
          disabled={actionLoading}
          onClick={async () => {
            setActionLoading(true);
            setActionMsg(null);
            try {
              const result = await exportSimulationSnapshot(id);
              setActionMsg(`Exported to ${result.path} (${result.agents} agents, ${result.chunks} chunks)`);
            } catch (err) {
              setActionMsg(`Export failed: ${err instanceof Error ? err.message : "Unknown error"}`);
            } finally {
              setActionLoading(false);
            }
          }}
          className="rounded border border-yellow-500/60 px-3 py-1.5 text-xs text-yellow-400 hover:bg-yellow-500/10 transition-colors disabled:opacity-50"
        >
          Export Snapshot
        </button>
        {!sim.is_live && (
          <button
            disabled={actionLoading || sim.status === "running"}
            onClick={async () => {
              if (!confirm(`Delete simulation "${sim.name}"? This cannot be undone.`)) return;
              setActionLoading(true);
              setActionMsg(null);
              try {
                await deleteSimulation(id);
                setActionMsg("Deleted. Redirecting...");
                setTimeout(() => { window.location.href = "/admin/simulations"; }, 1000);
              } catch (err) {
                setActionMsg(`Delete failed: ${err instanceof Error ? err.message : "Unknown error"}`);
              } finally {
                setActionLoading(false);
              }
            }}
            className="rounded border border-red-500/60 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
          >
            Delete
          </button>
        )}
        {actionMsg && (
          <span className="text-xs text-foreground/60">{actionMsg}</span>
        )}
      </div>

      {/* Summary Panel */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <SummaryCard label="Conversations" value={sim.total_conversations} />
        <SummaryCard label="Turns" value={sim.total_turns} />
        <SummaryCard label="Tokens" value={sim.total_tokens.toLocaleString()} />
        <SummaryCard
          label="Cost"
          value={`$${parseFloat(sim.total_cost || "0").toFixed(4)}`}
        />
        <SummaryCard label="Artifacts" value={sim.total_artifacts} />
        <SummaryCard label="Management Flags" value={sim.total_overseer_flags} />
      </div>

      {/* Agent Participation */}
      {sim.agents_participated.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-foreground/70 mb-2">
            Agents Participated
          </h2>
          <div className="flex flex-wrap gap-2">
            {sim.agents_participated.map((agent) => (
              <span
                key={agent}
                className="rounded border border-border bg-surface-light px-2 py-1 text-xs text-foreground/70"
              >
                {agent}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Conversations */}
      {convos.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-foreground/70 mb-3">
            Conversations
          </h2>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th className="px-4 py-2 font-medium">Trigger</th>
                  <th className="px-4 py-2 font-medium">Participants</th>
                  <th className="px-4 py-2 font-medium text-right">Turns</th>
                  <th className="px-4 py-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {convos.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                  >
                    <td className="px-4 py-2">
                      <Link
                        href={`/admin/conversations/${c.id}`}
                        className="text-neon-cyan hover:underline"
                      >
                        {c.trigger_type}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-foreground/50 text-xs">
                      {c.participating_agents.join(", ")}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {c.turn_count}
                    </td>
                    <td className="px-4 py-2 text-foreground/40 text-xs">
                      {new Date(c.started_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cost Chart */}
      <div>
        <h2 className="text-sm font-medium text-foreground/70 mb-3">
          Cost by Agent
        </h2>
        <div className="rounded-lg border border-border bg-surface p-4">
          <CostChart simulationId={id} />
        </div>
      </div>

      {/* Timeline */}
      <div>
        <h2 className="text-sm font-medium text-foreground/70 mb-3">
          Timeline
        </h2>
        <TimelineView
          simulationId={id}
          agents={sim.agents_participated}
        />
      </div>

      {/* Config Viewer */}
      <ConfigViewer config={sim.config} />

      {/* Error Log */}
      {sim.error_log && (
        <div>
          <h2 className="text-sm font-medium text-red-400 mb-2">Error Log</h2>
          <pre className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 text-xs text-red-300 font-mono overflow-x-auto max-h-64">
            {JSON.stringify(sim.error_log, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

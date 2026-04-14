"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import TimelineView from "@/components/admin/TimelineView";
import CostChart from "@/components/admin/CostChart";
import ConfigViewer from "@/components/admin/ConfigViewer";
import {
  SimulationHeader,
  SectionNav,
  SummaryGrid,
  AgentList,
} from "@/components/simulation";
import {
  fetchSimulation,
  fetchSimulationConversations,
  cloneSimulation,
  exportSimulationSnapshot,
  deleteSimulation,
} from "@/lib/admin-api";
import type { AgentConversation, Simulation } from "@/types/admin";

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
      <SimulationHeader
        name={sim.name}
        status={sim.status}
        description={sim.description}
        started_at={sim.started_at}
        completed_at={sim.completed_at}
        real_duration={sim.real_duration}
        simulated_duration={sim.simulated_duration}
        breadcrumbHref="/admin/simulations"
      />

      <SectionNav
        links={[
          { href: `/admin/simulations/${id}/evals`, label: "View Eval Results" },
          { href: `/admin/simulations/${id}/assertions`, label: "Assertions" },
          { href: `/admin/simulations/${id}/relationships`, label: "Social Graph" },
          { href: `/admin/simulations/${id}/report`, label: "Report" },
          { href: `/admin/simulations/${id}/snapshots`, label: "Snapshots" },
        ]}
      />

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

      <SummaryGrid
        total_conversations={sim.total_conversations}
        total_turns={sim.total_turns}
        total_tokens={sim.total_tokens}
        total_cost={sim.total_cost}
        total_artifacts={sim.total_artifacts}
        total_management_flags={sim.total_management_flags}
      />

      <AgentList agents={sim.agents_participated} />

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
                  <th scope="col" className="px-4 py-2 font-medium">Trigger</th>
                  <th scope="col" className="px-4 py-2 font-medium">Participants</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Turns</th>
                  <th scope="col" className="px-4 py-2 font-medium">Date</th>
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

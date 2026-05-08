"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  createSimulation,
  getScenarios,
  getSimulations,
} from "@/lib/api";
import type { PublicSimulation, ScenarioInfo } from "@/lib/api";
import { formatDuration } from "@/components/simulation";

const STATUS_STYLES: Record<string, string> = {
  running: "bg-neon-green/20 text-neon-green border-neon-green/40",
  completed: "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40",
  failed: "bg-red-500/20 text-red-400 border-red-500/40",
  cancelled: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
};

const STATUS_FILTERS = ["all", "running", "completed", "failed", "cancelled"] as const;

export default function SimulationsPage() {
  const router = useRouter();
  const [simulations, setSimulations] = useState<PublicSimulation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [showLauncher, setShowLauncher] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getSimulations({
        status: statusFilter === "all" ? undefined : statusFilter,
      });
      setSimulations(res.items);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load simulations",
      );
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <div className="flex items-start justify-between mb-2">
        <h1 className="font-pixel text-xl text-neon-cyan">SIMULATIONS</h1>
        <button
          onClick={() => setShowLauncher(true)}
          className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-3 py-1.5 text-xs font-medium text-neon-cyan hover:bg-neon-cyan/20 transition-colors"
        >
          Run new simulation
        </button>
      </div>
      <p className="text-foreground/60 mb-8">
        All simulation runs — explore agent conversations, eval scores,
        relationships, and reports.
      </p>

      {showLauncher && (
        <RunSimulationModal
          onClose={() => setShowLauncher(false)}
          onLaunched={(simId) => router.push(`/simulations/${simId}`)}
        />
      )}

      <div className="flex gap-2 mb-6">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`rounded border px-3 py-1 text-xs font-medium transition-colors ${
              statusFilter === s
                ? "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40"
                : "bg-surface text-foreground/50 border-border hover:bg-surface-light"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

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

function RunSimulationModal({
  onClose,
  onLaunched,
}: {
  onClose: () => void;
  onLaunched: (simId: string) => void;
}) {
  const [scenarios, setScenarios] = useState<ScenarioInfo[] | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>("");
  const [maxCost, setMaxCost] = useState<number>(2.0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getScenarios()
      .then((items) => {
        if (cancelled) return;
        setScenarios(items);
        if (items.length > 0) setSelectedFile(items[0].filename);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load scenarios",
        );
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedFile) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await createSimulation({
        seed_file: selectedFile,
        max_cost: maxCost,
      });
      onLaunched(result.simulation_id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start simulation",
      );
      setSubmitting(false);
    }
  }

  const selected = scenarios?.find((s) => s.filename === selectedFile);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg border border-border bg-surface p-6 space-y-4"
      >
        <h2 className="font-pixel text-sm text-neon-cyan">RUN NEW SIMULATION</h2>

        {scenarios === null ? (
          <p className="text-sm text-foreground/50">Loading scenarios...</p>
        ) : scenarios.length === 0 ? (
          <p className="text-sm text-foreground/50">
            No scenario YAML files found in scenarios/.
          </p>
        ) : (
          <>
            <div className="space-y-1">
              <label
                htmlFor="scenario"
                className="block text-xs font-medium text-foreground/70"
              >
                Scenario
              </label>
              <select
                id="scenario"
                value={selectedFile}
                onChange={(e) => setSelectedFile(e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
              >
                {scenarios.map((s) => (
                  <option key={s.filename} value={s.filename}>
                    {s.name}
                  </option>
                ))}
              </select>
              {selected?.description && (
                <p className="text-xs text-foreground/50 mt-1">
                  {selected.description.length > 200
                    ? selected.description.slice(0, 200) + "…"
                    : selected.description}
                </p>
              )}
            </div>

            <div className="space-y-1">
              <label
                htmlFor="max-cost"
                className="block text-xs font-medium text-foreground/70"
              >
                Max cost ($)
              </label>
              <input
                id="max-cost"
                type="number"
                step="0.1"
                min={0}
                max={10}
                value={maxCost}
                onChange={(e) => setMaxCost(parseFloat(e.target.value) || 0)}
                className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
              />
            </div>
          </>
        )}

        {error && (
          <div className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded border border-border px-3 py-1.5 text-xs text-foreground/60 hover:bg-surface-light transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={
              submitting ||
              !selectedFile ||
              scenarios === null ||
              scenarios.length === 0
            }
            className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-3 py-1.5 text-xs font-medium text-neon-cyan hover:bg-neon-cyan/20 transition-colors disabled:opacity-50"
          >
            {submitting ? "Starting..." : "Start"}
          </button>
        </div>
      </form>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import StatusBadge from "@/components/admin/StatusBadge";
import { fetchSimulations, createSimulation } from "@/lib/admin-api";
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

const CONVO_TYPES = ["freeform", "standup", "debate", "idle"] as const;

const DEFAULT_AGENTS = ["vera", "rex", "aurora", "pixel", "fork", "sentinel", "grok"];

export default function SimulationsPage() {
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [filter, setFilter] = useState<SimulationStatus | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNewDialog, setShowNewDialog] = useState(false);
  const [creating, setCreating] = useState(false);

  const loadSims = useCallback(async () => {
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
  }, [filter]);

  useEffect(() => {
    loadSims();
  }, [loadSims]);

  const handleCreate = async (params: {
    name: string;
    agents: string[];
    convo_type: string;
    topic: string;
    turns: number | undefined;
    management_shadow: boolean;
  }) => {
    setCreating(true);
    setError(null);
    try {
      await createSimulation({
        name: params.name || undefined,
        agents: params.agents,
        convo_type: params.convo_type,
        topic: params.topic || undefined,
        turns: params.turns,
        management_shadow: params.management_shadow,
      });
      setShowNewDialog(false);
      // Reload after a short delay to let the simulation start
      setTimeout(loadSims, 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create simulation");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="font-pixel text-lg text-foreground">Simulations</h1>
        <div className="flex items-center gap-3">
          <Link
            href="/admin/simulations/compare"
            className="rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
          >
            Compare Simulations
          </Link>
          <button
            onClick={() => setShowNewDialog(true)}
            className="rounded bg-neon-cyan/20 px-4 py-2 text-sm text-neon-cyan border border-neon-cyan/40 hover:bg-neon-cyan/30 transition-colors"
          >
            + New Simulation
          </button>
        </div>
      </div>

      {showNewDialog && (
        <NewSimulationDialog
          onSubmit={handleCreate}
          onCancel={() => setShowNewDialog(false)}
          submitting={creating}
        />
      )}

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


// ── New Simulation Dialog ──────────────────────────────────────

function NewSimulationDialog({
  onSubmit,
  onCancel,
  submitting,
}: {
  onSubmit: (params: {
    name: string;
    agents: string[];
    convo_type: string;
    topic: string;
    turns: number | undefined;
    management_shadow: boolean;
  }) => void;
  onCancel: () => void;
  submitting: boolean;
}) {
  const [name, setName] = useState("");
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(
    new Set(DEFAULT_AGENTS),
  );
  const [convoType, setConvoType] = useState("freeform");
  const [topic, setTopic] = useState("");
  const [turnsStr, setTurnsStr] = useState("10");
  const [managementShadow, setManagementShadow] = useState(true);

  const toggleAgent = (id: string) => {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const turns = turnsStr ? parseInt(turnsStr, 10) : undefined;
    onSubmit({
      name,
      agents: [...selectedAgents],
      convo_type: convoType,
      topic,
      turns: turns && !isNaN(turns) ? turns : undefined,
      management_shadow: managementShadow,
    });
  };

  return (
    <div className="mb-6 rounded-lg border border-neon-cyan/30 bg-surface p-5 space-y-4">
      <h3 className="text-sm font-medium text-foreground/80">New Simulation</h3>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Name */}
        <div>
          <label className="block text-xs text-foreground/50 mb-1">
            Name (optional)
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Auto-generated if empty"
            className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
          />
        </div>

        {/* Agents */}
        <div>
          <label className="block text-xs text-foreground/50 mb-1">
            Agents ({selectedAgents.size} selected)
          </label>
          <div className="flex flex-wrap gap-2">
            {DEFAULT_AGENTS.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => toggleAgent(id)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  selectedAgents.has(id)
                    ? "bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40"
                    : "bg-surface-light text-foreground/40 border border-border"
                }`}
              >
                {id}
              </button>
            ))}
          </div>
        </div>

        {/* Type + Turns row */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-foreground/50 mb-1">
              Conversation Type
            </label>
            <select
              value={convoType}
              onChange={(e) => setConvoType(e.target.value)}
              className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground"
            >
              {CONVO_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-foreground/50 mb-1">
              Max Turns
            </label>
            <input
              type="number"
              min={2}
              max={100}
              value={turnsStr}
              onChange={(e) => setTurnsStr(e.target.value)}
              className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground"
            />
          </div>
        </div>

        {/* Topic */}
        <div>
          <label className="block text-xs text-foreground/50 mb-1">
            Topic (optional)
          </label>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Leave empty for agents to pick"
            className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
          />
        </div>

        {/* Management Shadow */}
        <label className="flex items-center gap-2 text-xs text-foreground/60">
          <input
            type="checkbox"
            checked={managementShadow}
            onChange={(e) => setManagementShadow(e.target.checked)}
            className="rounded border-border"
          />
          Management shadow mode (log-only, never blocks)
        </label>

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button
            type="submit"
            disabled={submitting || selectedAgents.size < 2}
            className="rounded bg-neon-cyan/20 px-4 py-2 text-sm text-neon-cyan border border-neon-cyan/40 hover:bg-neon-cyan/30 transition-colors disabled:opacity-40"
          >
            {submitting ? "Starting..." : "Start Simulation"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-4 py-2 text-sm text-foreground/50 border border-border hover:bg-surface-light transition-colors"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

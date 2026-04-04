"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ArtifactCard from "@/components/admin/ArtifactCard";
import ArtifactDetailModal from "@/components/admin/ArtifactDetailModal";
import { fetchArtifacts, fetchSimulations, fetchAgents } from "@/lib/admin-api";
import type {
  AgentArtifact,
  AgentSummary,
  ArtifactFilters,
  ArtifactType,
  ArtifactStatus,
  Simulation,
} from "@/types/admin";

const ALL_ARTIFACT_TYPES: ArtifactType[] = [
  "social_post",
  "email",
  "code_execution",
  "web_search",
  "tilemap",
  "poll",
  "memory_operation",
  "alpha_dispatch",
  "self_modification",
  "message",
];

const ALL_STATUSES: ArtifactStatus[] = [
  "draft",
  "executed",
  "failed",
  "pending_approval",
];

const TYPE_ICONS: Record<string, string> = {
  social_post: "📱",
  email: "✉",
  code_execution: "⌨",
  web_search: "🔍",
  tilemap: "🗺",
  poll: "📊",
  memory_operation: "🧠",
  alpha_dispatch: "🐺",
  self_modification: "🔧",
  message: "💬",
};

const AGENT_COLORS: Record<string, string> = {
  vera: "#9b59b6",
  rex: "#e74c3c",
  aurora: "#f1c40f",
  pixel: "#3498db",
  fork: "#2ecc71",
  sentinel: "#e67e22",
  grok: "#1abc9c",
  overseer: "#95a5a6",
  alpha: "#8e44ad",
};

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-yellow-500/10 text-yellow-400",
  executed: "bg-green-500/10 text-green-400",
  success: "bg-green-500/10 text-green-400",
  failed: "bg-red-500/10 text-red-400",
  error: "bg-red-500/10 text-red-400",
  pending_approval: "bg-blue-500/10 text-blue-400",
  pending: "bg-yellow-500/10 text-yellow-400",
};

type SortOption = "newest" | "oldest" | "agent" | "type";
type ViewMode = "card" | "table";

const PAGE_SIZE = 30;

export default function ArtifactsPage() {
  // Data
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  const [total, setTotal] = useState(0);
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const simNameMap = useRef<Record<string, string>>({});

  // UI state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("card");
  const [selectedArtifact, setSelectedArtifact] = useState<AgentArtifact | null>(null);

  // Filters
  const [simulationId, setSimulationId] = useState<string>("");
  const [selectedAgents, setSelectedAgents] = useState<Set<string>>(new Set());
  const [selectedTypes, setSelectedTypes] = useState<Set<ArtifactType>>(new Set());
  const [selectedStatuses, setSelectedStatuses] = useState<Set<ArtifactStatus>>(new Set());
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sort, setSort] = useState<SortOption>("newest");
  const [offset, setOffset] = useState(0);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(timer);
  }, [search]);

  // Load simulations and agents once
  useEffect(() => {
    fetchSimulations().then((res) => {
      setSimulations(res.items);
      const map: Record<string, string> = {};
      for (const s of res.items) map[s.id] = s.name;
      simNameMap.current = map;
    }).catch(() => {});
    fetchAgents().then(setAgents).catch(() => {});
  }, []);

  // Build filters and load artifacts
  const loadArtifacts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filters: ArtifactFilters = {
        sort,
        limit: PAGE_SIZE,
        offset,
      };
      if (simulationId) filters.simulation_id = simulationId;
      if (selectedAgents.size > 0) filters.agent_ids = [...selectedAgents];
      if (selectedTypes.size > 0) filters.types = [...selectedTypes];
      if (selectedStatuses.size > 0) filters.statuses = [...selectedStatuses];
      if (since) filters.since = new Date(since).toISOString();
      if (until) filters.until = new Date(until).toISOString();
      if (debouncedSearch) filters.search = debouncedSearch;

      const res = await fetchArtifacts(filters);
      setArtifacts(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load artifacts");
    } finally {
      setLoading(false);
    }
  }, [simulationId, selectedAgents, selectedTypes, selectedStatuses, since, until, debouncedSearch, sort, offset]);

  useEffect(() => {
    loadArtifacts();
  }, [loadArtifacts]);

  // Reset offset when filters change
  useEffect(() => {
    setOffset(0);
  }, [simulationId, selectedAgents, selectedTypes, selectedStatuses, since, until, debouncedSearch, sort]);

  const toggleAgent = (id: string) => {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleType = (t: ArtifactType) => {
    setSelectedTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  };

  const toggleStatus = (s: ArtifactStatus) => {
    setSelectedStatuses((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="max-w-7xl">
      <h1 className="font-pixel text-lg text-foreground mb-6">Artifacts</h1>

      {/* Filter Bar */}
      <div className="rounded-lg border border-border bg-surface p-4 mb-6 space-y-4">
        {/* Row 1: Simulation + Search + Date Range */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs text-foreground/50 mb-1">Simulation</label>
            <select
              value={simulationId}
              onChange={(e) => setSimulationId(e.target.value)}
              className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground"
            >
              <option value="">All simulations</option>
              {simulations.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-foreground/50 mb-1">Search content</label>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Keyword search..."
              className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground placeholder:text-foreground/30"
            />
          </div>
          <div>
            <label className="block text-xs text-foreground/50 mb-1">From</label>
            <input
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground"
            />
          </div>
          <div>
            <label className="block text-xs text-foreground/50 mb-1">Until</label>
            <input
              type="date"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className="w-full rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground"
            />
          </div>
        </div>

        {/* Row 2: Agent multi-select */}
        <div>
          <label className="block text-xs text-foreground/50 mb-1">
            Agents {selectedAgents.size > 0 && `(${selectedAgents.size})`}
          </label>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((a) => (
              <button
                key={a.id}
                onClick={() => toggleAgent(a.id)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  selectedAgents.has(a.id)
                    ? "border"
                    : "bg-surface-light text-foreground/40 border border-border"
                }`}
                style={
                  selectedAgents.has(a.id)
                    ? { backgroundColor: `${a.color}20`, color: a.color, borderColor: `${a.color}60` }
                    : undefined
                }
              >
                {a.display_name || a.id}
              </button>
            ))}
          </div>
        </div>

        {/* Row 3: Type checkboxes */}
        <div>
          <label className="block text-xs text-foreground/50 mb-1">Artifact Type</label>
          <div className="flex flex-wrap gap-1.5">
            {ALL_ARTIFACT_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => toggleType(t)}
                className={`rounded px-2.5 py-1 text-xs transition-colors ${
                  selectedTypes.has(t)
                    ? "bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40"
                    : "bg-surface-light text-foreground/40 border border-border"
                }`}
              >
                {TYPE_ICONS[t]} {t}
              </button>
            ))}
          </div>
        </div>

        {/* Row 4: Status + Sort */}
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="block text-xs text-foreground/50 mb-1">Status</label>
            <div className="flex gap-1.5">
              {ALL_STATUSES.map((s) => (
                <button
                  key={s}
                  onClick={() => toggleStatus(s)}
                  className={`rounded px-2.5 py-1 text-xs transition-colors ${
                    selectedStatuses.has(s)
                      ? STATUS_STYLES[s] + " border border-current/40"
                      : "bg-surface-light text-foreground/40 border border-border"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-xs text-foreground/50 mb-1">Sort</label>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortOption)}
              className="rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground"
            >
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
              <option value="agent">Agent</option>
              <option value="type">Type</option>
            </select>
          </div>
          <div className="ml-auto flex gap-1">
            <button
              onClick={() => setViewMode("card")}
              className={`rounded px-2.5 py-1.5 text-xs transition-colors ${
                viewMode === "card"
                  ? "bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40"
                  : "bg-surface-light text-foreground/40 border border-border"
              }`}
            >
              Cards
            </button>
            <button
              onClick={() => setViewMode("table")}
              className={`rounded px-2.5 py-1.5 text-xs transition-colors ${
                viewMode === "table"
                  ? "bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40"
                  : "bg-surface-light text-foreground/40 border border-border"
              }`}
            >
              Table
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400 mb-4">
          {error}
        </div>
      )}

      {/* Results header */}
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-foreground/40">
          {total} artifact{total !== 1 ? "s" : ""} found
          {total > 0 && ` — showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, total)}`}
        </p>
      </div>

      {/* Content */}
      {loading ? (
        <p className="text-sm text-foreground/50">Loading...</p>
      ) : artifacts.length === 0 ? (
        <p className="text-sm text-foreground/50">No artifacts found.</p>
      ) : viewMode === "card" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {artifacts.map((a) => (
            <ArtifactCard
              key={a.id}
              artifact={a}
              onClick={() => setSelectedArtifact(a)}
              simulationName={a.simulation_id ? simNameMap.current[a.simulation_id] : undefined}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Agent</th>
                <th className="px-3 py-2 font-medium">Content</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Simulation</th>
              </tr>
            </thead>
            <tbody>
              {artifacts.map((a) => {
                const icon = TYPE_ICONS[a.artifact_type] ?? "◇";
                const preview = getTablePreview(a);
                return (
                  <tr
                    key={a.id}
                    onClick={() => setSelectedArtifact(a)}
                    className="border-b border-border last:border-0 hover:bg-surface-light transition-colors cursor-pointer"
                  >
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="mr-1">{icon}</span>
                      <span className="text-xs text-foreground/60">{a.artifact_type}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className="text-xs font-medium"
                        style={{ color: AGENT_COLORS[a.agent_id] ?? "#888" }}
                      >
                        {a.agent_id}
                      </span>
                    </td>
                    <td className="px-3 py-2 max-w-xs">
                      <p className="text-xs text-foreground/50 truncate">{preview}</p>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded ${STATUS_STYLES[a.status] ?? "bg-foreground/10 text-foreground/60"}`}
                      >
                        {a.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-foreground/40 whitespace-nowrap">
                      {new Date(a.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-xs text-foreground/40 truncate max-w-[120px]">
                      {a.simulation_id ? simNameMap.current[a.simulation_id] ?? "—" : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-6">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="rounded px-3 py-1.5 text-xs border border-border bg-surface-light text-foreground/60 hover:text-foreground disabled:opacity-30 transition-colors"
          >
            Previous
          </button>
          <span className="text-xs text-foreground/40">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="rounded px-3 py-1.5 text-xs border border-border bg-surface-light text-foreground/60 hover:text-foreground disabled:opacity-30 transition-colors"
          >
            Next
          </button>
        </div>
      )}

      {/* Detail Modal */}
      {selectedArtifact && (
        <ArtifactDetailModal
          artifact={selectedArtifact}
          onClose={() => setSelectedArtifact(null)}
        />
      )}
    </div>
  );
}

function getTablePreview(artifact: AgentArtifact): string {
  const output = artifact.tool_output;
  if (output == null) return "(no output)";
  if (typeof output === "string") return output.slice(0, 200);
  return JSON.stringify(output).slice(0, 200);
}

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchSnapshots,
  fetchSnapshot,
  triggerSnapshotExport,
  fetchCurrentMemoryState,
} from "@/lib/admin-api";
import type {
  SnapshotSummary,
  SnapshotData,
  CurrentMemoryState,
} from "@/types/admin";

// ── Simple line-by-line diff ──────────────────────────────────

function SimpleDiff({ textA, textB }: { textA: string; textB: string }) {
  const linesA = textA.split("\n");
  const linesB = textB.split("\n");

  return (
    <div className="grid grid-cols-2 gap-2 text-xs font-mono">
      <div className="rounded border border-border bg-surface-light p-3 overflow-auto max-h-64">
        <div className="text-foreground/50 mb-2 text-xs">Snapshot A</div>
        {linesA.map((line, i) => (
          <div
            key={i}
            className={
              linesB[i] !== line
                ? "bg-red-500/10 text-red-300"
                : "text-foreground/70"
            }
          >
            {line || "\u00A0"}
          </div>
        ))}
      </div>
      <div className="rounded border border-border bg-surface-light p-3 overflow-auto max-h-64">
        <div className="text-foreground/50 mb-2 text-xs">Snapshot B</div>
        {linesB.map((line, i) => (
          <div
            key={i}
            className={
              linesA[i] !== line
                ? "bg-green-500/10 text-green-300"
                : "text-foreground/70"
            }
          >
            {line || "\u00A0"}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Agent card used in Browse tab ─────────────────────────────

function AgentSnapshotCard({
  agentId,
  data,
}: {
  agentId: string;
  data: {
    core_memory: string;
    recall_memories?: Record<string, unknown>[];
    journal_entries?: Record<string, unknown>[];
  };
}) {
  const [open, setOpen] = useState(false);
  const recallCount = data.recall_memories?.length ?? 0;
  const journalCount = data.journal_entries?.length ?? 0;
  const preview = data.core_memory?.slice(0, 200) ?? "";

  return (
    <div className="rounded border border-border bg-surface-light">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="w-full flex items-center justify-between px-4 py-3 text-left text-sm hover:bg-surface transition-colors"
      >
        <span className="font-mono text-neon-cyan">{agentId}</span>
        <span className="text-xs text-foreground/40">
          {recallCount} recall / {journalCount} journal
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-2">
          <p className="text-xs text-foreground/50 mb-1">Core memory preview</p>
          <pre className="rounded bg-surface p-2 text-xs text-foreground/70 font-mono overflow-x-auto whitespace-pre-wrap break-words">
            {preview || "(empty)"}
            {data.core_memory?.length > 200 ? "…" : ""}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────

export default function SnapshotsPage() {
  const params = useParams();
  const id = params.id as string;

  const [activeTab, setActiveTab] = useState<"browse" | "compare">("browse");
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Browse tab
  const [expandedSnapshot, setExpandedSnapshot] = useState<string | null>(null);
  const [snapshotContents, setSnapshotContents] = useState<
    Record<string, SnapshotData>
  >({});
  const [loadingContent, setLoadingContent] = useState<string | null>(null);

  // Compare tab
  const [selectedA, setSelectedA] = useState<string>("");
  const [selectedB, setSelectedB] = useState<string>("");
  const [comparing, setComparing] = useState(false);
  const [diffData, setDiffData] = useState<{
    a: SnapshotData | CurrentMemoryState | null;
    b: SnapshotData | CurrentMemoryState | null;
  }>({ a: null, b: null });
  const [compareError, setCompareError] = useState<string | null>(null);

  useEffect(() => {
    fetchSnapshots(id)
      .then((data) => {
        setSnapshots(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load snapshots");
        setLoading(false);
      });
  }, [id]);

  async function handleExport() {
    setExporting(true);
    try {
      const summary = await triggerSnapshotExport(id);
      setSnapshots((prev) => [summary, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleToggleSnapshot(filename: string) {
    if (expandedSnapshot === filename) {
      setExpandedSnapshot(null);
      return;
    }
    setExpandedSnapshot(filename);
    if (!snapshotContents[filename]) {
      setLoadingContent(filename);
      try {
        const data = await fetchSnapshot(id, filename);
        setSnapshotContents((prev) => ({ ...prev, [filename]: data }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load snapshot");
      } finally {
        setLoadingContent(null);
      }
    }
  }

  async function loadSide(
    value: string,
  ): Promise<SnapshotData | CurrentMemoryState> {
    if (value === "current") {
      return fetchCurrentMemoryState(id);
    }
    if (snapshotContents[value]) {
      return snapshotContents[value];
    }
    const data = await fetchSnapshot(id, value);
    setSnapshotContents((prev) => ({ ...prev, [value]: data }));
    return data;
  }

  async function handleCompare() {
    if (!selectedA || !selectedB) return;
    setComparing(true);
    setCompareError(null);
    try {
      const [a, b] = await Promise.all([loadSide(selectedA), loadSide(selectedB)]);
      setDiffData({ a, b });
    } catch (err) {
      setCompareError(err instanceof Error ? err.message : "Comparison failed");
    } finally {
      setComparing(false);
    }
  }

  // Helper: extract per-agent core memory from either type
  function getAgentCoreMemory(
    data: SnapshotData | CurrentMemoryState,
    agentId: string,
  ): string {
    const agents = data.agents as Record<string, { core_memory: string }>;
    return agents[agentId]?.core_memory ?? "";
  }

  // All agent IDs across both diff sides
  const diffAgentIds =
    diffData.a && diffData.b
      ? Array.from(
          new Set([
            ...Object.keys(diffData.a.agents),
            ...Object.keys(diffData.b.agents),
          ]),
        )
      : [];

  const snapshotOptions = snapshots.map((s) => ({
    value: s.filename,
    label: `${s.filename} (${s.snapshot_at ? new Date(s.snapshot_at).toLocaleString() : "unknown"})`,
  }));

  return (
    <div className="max-w-6xl space-y-8">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/admin/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <Link
          href={`/admin/simulations/${id}`}
          className="hover:text-foreground/60"
        >
          {id}
        </Link>
        {" / "}
        <span className="text-foreground/60">Snapshots</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="font-pixel text-lg text-foreground">Memory Snapshots</h1>
        <button
          type="button"
          onClick={handleExport}
          disabled={exporting}
          className="rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {exporting ? "Exporting..." : "Export Snapshot"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
      )}

      {/* Tab nav */}
      <div className="flex gap-1 border-b border-border">
        {(["browse", "compare"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-xs capitalize transition-colors ${
              activeTab === tab
                ? "border-b-2 border-neon-cyan text-neon-cyan"
                : "text-foreground/50 hover:text-foreground/70"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ── Browse tab ── */}
      {activeTab === "browse" && (
        <div className="space-y-4">
          {loading && <p className="text-sm text-foreground/50">Loading...</p>}
          {!loading && snapshots.length === 0 && (
            <p className="text-sm text-foreground/50">
              No snapshots found for this simulation. Use "Export Snapshot" to
              create one.
            </p>
          )}
          {snapshots.map((s) => (
            <div
              key={s.filename}
              className="rounded-lg border border-border bg-surface overflow-hidden"
            >
              {/* Snapshot card header */}
              <button
                type="button"
                onClick={() => handleToggleSnapshot(s.filename)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-surface-light transition-colors"
              >
                <div className="space-y-0.5">
                  <p className="font-mono text-xs text-neon-cyan">{s.filename}</p>
                  {s.snapshot_at && (
                    <p className="text-xs text-foreground/50">
                      {new Date(s.snapshot_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <span className="text-xs text-foreground/40">
                  {s.agent_count} agent{s.agent_count !== 1 ? "s" : ""}
                </span>
              </button>

              {/* Expanded content */}
              {expandedSnapshot === s.filename && (
                <div className="border-t border-border px-4 pb-4 pt-3 space-y-3">
                  {loadingContent === s.filename && (
                    <p className="text-sm text-foreground/50">Loading...</p>
                  )}
                  {snapshotContents[s.filename] &&
                    Object.entries(snapshotContents[s.filename].agents).map(
                      ([agentId, agentData]) => (
                        <AgentSnapshotCard
                          key={agentId}
                          agentId={agentId}
                          data={agentData}
                        />
                      ),
                    )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Compare tab ── */}
      {activeTab === "compare" && (
        <div className="space-y-6">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label className="block text-xs text-foreground/50">
                Snapshot A
              </label>
              <select
                value={selectedA}
                onChange={(e) => setSelectedA(e.target.value)}
                className="rounded border border-border bg-surface px-3 py-1.5 text-xs text-foreground focus:outline-none focus:border-neon-cyan min-w-64"
              >
                <option value="">Select snapshot A...</option>
                <option value="current">Current State</option>
                {snapshotOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="block text-xs text-foreground/50">
                Snapshot B
              </label>
              <select
                value={selectedB}
                onChange={(e) => setSelectedB(e.target.value)}
                className="rounded border border-border bg-surface px-3 py-1.5 text-xs text-foreground focus:outline-none focus:border-neon-cyan min-w-64"
              >
                <option value="">Select snapshot B...</option>
                <option value="current">Current State</option>
                {snapshotOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="button"
              onClick={handleCompare}
              disabled={!selectedA || !selectedB || comparing}
              className="rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {comparing ? "Comparing..." : "Compare"}
            </button>
          </div>

          {compareError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
              {compareError}
            </div>
          )}

          {diffData.a && diffData.b && diffAgentIds.length === 0 && (
            <p className="text-sm text-foreground/50">
              No agents found in either snapshot.
            </p>
          )}

          {diffData.a && diffData.b && diffAgentIds.length > 0 && (
            <div className="space-y-6">
              {diffAgentIds.map((agentId) => {
                const textA = getAgentCoreMemory(diffData.a!, agentId);
                const textB = getAgentCoreMemory(diffData.b!, agentId);
                return (
                  <div key={agentId} className="space-y-2">
                    <h3 className="font-mono text-xs text-neon-cyan">
                      {agentId}
                    </h3>
                    <SimpleDiff textA={textA} textB={textB} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

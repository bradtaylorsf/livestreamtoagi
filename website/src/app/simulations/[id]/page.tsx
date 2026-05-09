"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getSimulation,
  getSimulationConversations,
  getSimulationEvals,
  getSimulationSocialGraph,
  getSimulationCosts,
  getSimulationSnapshots,
  getEvalRuns,
} from "@/lib/api";
import type {
  PublicSimulationDetail,
  SimulationEvalRun,
  SimulationCostResponse,
  SnapshotSummary,
  PublicEvalRun,
} from "@/lib/api";
import type { ConversationSummary, PaginatedResponse } from "@/types";
import { conversationTopicLabel } from "@/lib/conversation-display";
import {
  SimulationHeader,
  OverviewTab,
  AgentsTab,
  MemoriesTab,
  EnergyTab,
  HypothesisOutcomesTab,
  LearningsTab,
} from "@/components/simulation";
import {
  SkeletonBlock,
  SkeletonCardList,
  SkeletonGrid,
  SkeletonTable,
} from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";

// ── Tab definitions ──────────────────────────────────────────────

const TAB_KEYS = [
  "overview",
  "agents",
  "memories",
  "evals",
  "energy",
  "hypothesis-outcomes",
  "learnings",
  "conversations",
  "social-graph",
  "snapshots",
  "costs",
] as const;

type TabKey = (typeof TAB_KEYS)[number];

const TAB_LABELS: Record<TabKey, string> = {
  overview: "Overview",
  agents: "Agents",
  memories: "Memories",
  evals: "Evals",
  energy: "Energy",
  "hypothesis-outcomes": "Hypothesis & Outcomes",
  learnings: "Learnings",
  conversations: "Conversations",
  "social-graph": "Social Graph",
  snapshots: "Snapshots",
  costs: "Cost Analysis",
};

function isValidTab(value: string | null): value is TabKey {
  return value !== null && TAB_KEYS.includes(value as TabKey);
}

function shouldPollSimulation(sim: PublicSimulationDetail | null): boolean {
  if (!sim) return false;
  if (sim.status === "queued" || sim.status === "running") return true;
  if (sim.status === "cancelled") return false;
  if (sim.video_render_status === null) {
    return sim.status === "completed" || sim.status === "failed";
  }
  return (
    sim.video_render_status === "pending" ||
    sim.video_render_status === "rendering"
  );
}

// API returns Decimal fields as strings; coerce to number for display.
function toNumber(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

const SENTIMENT_TRUST_MIN_INTERACTIONS = 3;

const REAL_AGENT_IDS = new Set([
  "vera",
  "rex",
  "aurora",
  "pixel",
  "fork",
  "sentinel",
  "grok",
  "management",
  "alpha",
]);

function scoreColor(score: number | null | undefined): string {
  if (score == null) return "text-foreground/50";
  if (score > 7) return "text-green-400";
  if (score > 4) return "text-yellow-400";
  return "text-red-400";
}

function scoreBg(score: number | null | undefined): string {
  if (score == null) return "bg-surface-light border-border";
  if (score > 7) return "bg-green-500/10 border-green-500/30";
  if (score > 4) return "bg-yellow-500/10 border-yellow-500/30";
  return "bg-red-500/10 border-red-500/30";
}

// ── Conversations tab ────────────────────────────────────────────

function ConversationsTab({ simulationId }: { simulationId: string }) {
  const [data, setData] = useState<PaginatedResponse<ConversationSummary> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const showSkeleton = useDelayedFlag(loading && !data);

  const fetchData = useCallback(
    (newOffset: number) => {
      setLoading(true);
      getSimulationConversations(simulationId, { limit, offset: newOffset })
        .then((res) => {
          setData(res);
          setOffset(newOffset);
        })
        .catch((err) =>
          setError(err instanceof Error ? err.message : "Failed to load conversations"),
        )
        .finally(() => setLoading(false));
    },
    [simulationId],
  );

  useEffect(() => {
    fetchData(0);
  }, [fetchData]);

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading && !data) {
    return showSkeleton ? <SkeletonCardList count={5} /> : null;
  }

  if (!data || data.items.length === 0) {
    return <p className="text-sm text-foreground/50">No conversations found for this simulation.</p>;
  }

  const totalPages = Math.ceil(data.total / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="space-y-4">
      <p className="text-xs text-foreground/40">{data.total} conversations total</p>

      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Topic</th>
              <th scope="col" className="px-4 py-2 font-medium">Status</th>
              <th scope="col" className="px-4 py-2 font-medium">Participants</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Turns</th>
              <th scope="col" className="px-4 py-2 font-medium">Started At</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((c) => (
              <tr
                key={c.id}
                className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
              >
                <td className="px-4 py-2">
                  <Link
                    href={`/simulations/${simulationId}/conversations/${c.id}`}
                    className="text-neon-cyan hover:underline"
                  >
                    {conversationTopicLabel(c.topics_discussed)}
                  </Link>
                </td>
                <td className="px-4 py-2">
                  <span className="inline-block rounded border border-border bg-surface-light px-2 py-0.5 text-xs font-medium text-foreground/70">
                    {c.trigger_type}
                  </span>
                </td>
                <td className="px-4 py-2 text-foreground/50 text-xs">
                  {c.participating_agents.join(", ")}
                </td>
                <td className="px-4 py-2 text-right font-mono">{c.turn_count}</td>
                <td className="px-4 py-2 text-foreground/40 text-xs">
                  {c.started_at ? new Date(c.started_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <button
            disabled={offset === 0 || loading}
            onClick={() => fetchData(Math.max(0, offset - limit))}
            className="rounded border border-border px-3 py-1.5 text-xs text-foreground/60 hover:bg-surface-light transition-colors disabled:opacity-30"
          >
            Previous
          </button>
          <span className="text-xs text-foreground/40">
            Page {currentPage} of {totalPages}
          </span>
          <button
            disabled={offset + limit >= data.total || loading}
            onClick={() => fetchData(offset + limit)}
            className="rounded border border-border px-3 py-1.5 text-xs text-foreground/60 hover:bg-surface-light transition-colors disabled:opacity-30"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

// ── Evals tab (with comparable-run lookup) ──────────────────────

function EvalsTab({
  simulationId,
  scenarioId,
}: {
  simulationId: string;
  scenarioId: string | null;
}) {
  const [evalRuns, setEvalRuns] = useState<SimulationEvalRun[] | null>(null);
  const [comparable, setComparable] = useState<PublicEvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set());
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    let cancelled = false;
    getSimulationEvals(simulationId)
      .then((runs) => {
        if (cancelled) return;
        setEvalRuns(runs);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load eval results");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId]);

  // Pull comparable recent runs (best-effort; non-blocking)
  useEffect(() => {
    let cancelled = false;
    getEvalRuns({ limit: 12 })
      .then((runs) => {
        if (cancelled) return;
        const filtered = runs.filter(
          (r) => r.simulation_id !== simulationId && r.overall_score != null,
        );
        setComparable(filtered.slice(0, 5));
      })
      .catch(() => {
        // Silent fallback — comparable runs are optional context.
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId, scenarioId]);

  const toggleRun = (id: string) => {
    setExpandedRuns((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading) {
    return showSkeleton ? <SkeletonGrid count={6} /> : null;
  }

  if (!evalRuns || evalRuns.length === 0) {
    return <p className="text-sm text-foreground/50">No eval runs found for this simulation.</p>;
  }

  return (
    <div className="space-y-6" data-testid="evals-tab">
      <div className="space-y-4">
        {evalRuns.map((run) => {
          const expanded = expandedRuns.has(run.id);
          return (
            <div key={run.id} className="rounded border border-border bg-surface">
              <button
                onClick={() => toggleRun(run.id)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-surface-light transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-2">
                    <span className={`font-mono text-lg font-bold ${scoreColor(run.overall_score)}`}>
                      {run.overall_score != null ? run.overall_score.toFixed(1) : "N/A"}
                    </span>
                    <span className="text-xs text-foreground/40">overall</span>
                  </div>
                  <div className="text-xs text-foreground/50">
                    {run.started_at ? new Date(run.started_at).toLocaleDateString() : "Unknown date"}
                  </div>
                  <span
                    className={`rounded border px-1.5 py-0.5 text-xs ${
                      run.status === "completed"
                        ? "border-green-500/40 text-green-400"
                        : run.status === "failed"
                          ? "border-red-500/40 text-red-400"
                          : "border-border text-foreground/50"
                    }`}
                  >
                    {run.status}
                  </span>
                  {run.cost > 0 && (
                    <span className="text-xs text-foreground/40 font-mono">
                      ${run.cost.toFixed(4)}
                    </span>
                  )}
                </div>
                <svg
                  className={`w-4 h-4 text-foreground/40 transition-transform ${expanded ? "rotate-180" : ""}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {expanded && run.results && run.results.length > 0 && (
                <div className="px-4 pb-4">
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                    {run.results.map((result) => (
                      <div
                        key={result.category}
                        className={`rounded border p-3 ${scoreBg(result.score)}`}
                      >
                        <div className="text-xs text-foreground/50 mb-1">
                          {result.category.replace(/_/g, " ")}
                        </div>
                        <div className={`font-mono text-sm font-medium ${scoreColor(result.score)}`}>
                          {result.score != null ? result.score.toFixed(1) : "N/A"}
                        </div>
                        {result.reasoning && (
                          <div className="text-xs text-foreground/40 mt-1 line-clamp-2">
                            {result.reasoning}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {comparable.length > 0 && (
        <section
          className="space-y-3"
          data-testid="evals-comparable-runs"
        >
          <h3 className="text-xs font-medium uppercase tracking-wide text-foreground/50">
            Comparable runs
          </h3>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Simulation</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Overall</th>
                  <th scope="col" className="px-4 py-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {comparable.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                  >
                    <td className="px-4 py-2">
                      <Link
                        href={`/simulations/${run.simulation_id}?tab=evals`}
                        className="text-neon-cyan hover:underline"
                      >
                        {run.simulation_name ?? run.simulation_id}
                      </Link>
                    </td>
                    <td className="px-4 py-2 font-mono text-right">
                      {run.overall_score != null
                        ? run.overall_score.toFixed(1)
                        : "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-foreground/50">
                      {run.date ? new Date(run.date).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function SocialGraphTab({ simulationId }: { simulationId: string }) {
  const [data, setData] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    getSimulationSocialGraph(simulationId)
      .then(setData)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load social graph"),
      )
      .finally(() => setLoading(false));
  }, [simulationId]);

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading) {
    return showSkeleton ? (
      <div className="space-y-4">
        <SkeletonBlock width="w-1/4" height="h-5" />
        <div className="rounded border border-border bg-surface p-6">
          <SkeletonBlock width="w-full" height="h-64" />
        </div>
      </div>
    ) : null;
  }

  if (!data || data.length === 0) {
    return <p className="text-sm text-foreground/50">No social graph data available.</p>;
  }

  const anyQualifies = data.some(
    (row) =>
      (toNumber(row.interaction_count ?? row.interactions) ?? 0) >=
      SENTIMENT_TRUST_MIN_INTERACTIONS,
  );

  return (
    <div className="space-y-4">
      <p className="text-xs text-foreground/40">{data.length} relationships</p>

      {!anyQualifies && (
        <p className="text-xs text-foreground/50 italic">
          Sentiment & trust hidden {"—"} fewer than {SENTIMENT_TRUST_MIN_INTERACTIONS} interactions per
          pair.
        </p>
      )}

      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Agent A</th>
              <th scope="col" className="px-4 py-2 font-medium">Agent B</th>
              {anyQualifies && (
                <>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Sentiment</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Trust</th>
                </>
              )}
              <th scope="col" className="px-4 py-2 font-medium text-right">Interactions</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row, idx) => {
              const sentiment = toNumber(row.sentiment_score ?? row.sentiment);
              const trust = toNumber(row.trust_score ?? row.trust);
              const interactions =
                toNumber(row.interaction_count ?? row.interactions) ?? 0;
              const showScores = interactions >= SENTIMENT_TRUST_MIN_INTERACTIONS;
              return (
                <tr
                  key={idx}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-foreground/80">
                    {String(row.source_agent_id ?? row.agent_id ?? row.agent_a ?? row.from ?? "")}
                  </td>
                  <td className="px-4 py-2 font-mono text-foreground/80">
                    {String(row.target_agent_id ?? row.agent_b ?? row.to ?? "")}
                  </td>
                  {anyQualifies && (
                    <>
                      <td className="px-4 py-2 font-mono text-right">
                        {showScores && sentiment != null ? sentiment.toFixed(2) : "—"}
                      </td>
                      <td className="px-4 py-2 font-mono text-right">
                        {showScores && trust != null ? trust.toFixed(2) : "—"}
                      </td>
                    </>
                  )}
                  <td className="px-4 py-2 font-mono text-right">
                    {String(row.interaction_count ?? row.interactions ?? "—")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CostsTab({ simulationId }: { simulationId: string }) {
  const [data, setData] = useState<SimulationCostResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    getSimulationCosts(simulationId)
      .then(setData)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load cost data"),
      )
      .finally(() => setLoading(false));
  }, [simulationId]);

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading) {
    return showSkeleton ? (
      <SkeletonTable rows={6} columnWidths={["w-32", "w-20", "w-16", "w-16"]} />
    ) : null;
  }

  if (!data) {
    return <p className="text-sm text-foreground/50">No cost data available.</p>;
  }

  const agentCosts = [...data.by_agent].sort(
    (a, b) => Number(b.total) - Number(a.total),
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded border border-border bg-surface-light p-4">
          <div className="text-xs text-foreground/50 mb-1">Total Cost</div>
          <div className="font-mono text-xl text-foreground">
            ${parseFloat(data.total || "0").toFixed(4)}
          </div>
        </div>
        <div className="rounded border border-border bg-surface-light p-4">
          <div className="text-xs text-foreground/50 mb-1">Input Tokens</div>
          <div className="font-mono text-xl text-foreground">
            {data.total_input_tokens.toLocaleString()}
          </div>
        </div>
        <div className="rounded border border-border bg-surface-light p-4">
          <div className="text-xs text-foreground/50 mb-1">Output Tokens</div>
          <div className="font-mono text-xl text-foreground">
            {data.total_output_tokens.toLocaleString()}
          </div>
        </div>
      </div>

      {agentCosts.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">
            Cost by Agent
          </h3>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Agent</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {agentCosts.map((entry) => {
                  const isRealAgent = REAL_AGENT_IDS.has(entry.agent_id);
                  return (
                    <tr
                      key={entry.agent_id}
                      className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                    >
                      <td className="px-4 py-2 font-mono text-foreground/80">
                        {isRealAgent ? (
                          <Link
                            href={`/agents/${entry.agent_id}`}
                            className="hover:text-neon-cyan transition-colors"
                          >
                            {entry.agent_id}
                          </Link>
                        ) : (
                          <span className="text-foreground/60">{entry.agent_id}</span>
                        )}
                      </td>
                      <td className="px-4 py-2 font-mono text-right">
                        ${parseFloat(entry.total || "0").toFixed(4)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function SnapshotsTab({ simulationId }: { simulationId: string }) {
  const [snapshots, setSnapshots] = useState<SnapshotSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    getSimulationSnapshots(simulationId)
      .then(setSnapshots)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load snapshots"),
      )
      .finally(() => setLoading(false));
  }, [simulationId]);

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading) {
    return showSkeleton ? <SkeletonCardList count={3} /> : null;
  }

  if (!snapshots || snapshots.length === 0) {
    return <p className="text-sm text-foreground/50">No snapshots found for this simulation.</p>;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-foreground/40">{snapshots.length} snapshots</p>

      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Filename</th>
              <th scope="col" className="px-4 py-2 font-medium">Date</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Agent Count</th>
            </tr>
          </thead>
          <tbody>
            {snapshots.map((snap, idx) => (
              <tr
                key={snap.filename ?? idx}
                className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
              >
                <td className="px-4 py-2 font-mono text-xs">
                  <Link
                    href={`/simulations/${simulationId}/snapshots/${encodeURIComponent(snap.filename)}`}
                    className="text-neon-cyan hover:underline"
                  >
                    {snap.filename}
                  </Link>
                </td>
                <td className="px-4 py-2 text-xs text-foreground/50">
                  {snap.snapshot_at
                    ? new Date(snap.snapshot_at).toLocaleString()
                    : "—"}
                </td>
                <td className="px-4 py-2 font-mono text-right">
                  {snap.agent_count != null ? String(snap.agent_count) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main page (with Suspense boundary for useSearchParams) ───────

function SimulationDetailContent() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const id = params.id as string;

  const tabParam = searchParams.get("tab");
  const activeTab: TabKey = isValidTab(tabParam) ? tabParam : "overview";
  const justQueued = searchParams.get("queued") === "1";

  const [sim, setSim] = useState<PublicSimulationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSimulation(id)
      .then((next) => {
        if (!cancelled) setSim(next);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load simulation",
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const shouldPoll = shouldPollSimulation(sim);

  useEffect(() => {
    if (!shouldPoll) return;

    let cancelled = false;
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      getSimulation(id)
        .then((next) => {
          if (!cancelled) {
            setSim(next);
            setError(null);
          }
        })
        .catch((err) => {
          if (cancelled) return;
          setError(
            err instanceof Error ? err.message : "Failed to refresh simulation",
          );
        });
    };

    const intervalId = window.setInterval(tick, 5_000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [id, shouldPoll]);

  const setActiveTab = useCallback(
    (tab: TabKey) => {
      const newParams = new URLSearchParams(searchParams.toString());
      if (tab === "overview") {
        newParams.delete("tab");
      } else {
        newParams.set("tab", tab);
      }
      const qs = newParams.toString();
      router.push(`/simulations/${id}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [id, router, searchParams],
  );

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

  const scenarioId =
    typeof sim.config?.scenario_id === "string"
      ? (sim.config.scenario_id as string)
      : null;

  const renderTabContent = () => {
    switch (activeTab) {
      case "overview":
        return (
          <OverviewTab
            sim={sim}
            simulationId={id}
            onJumpToHypothesis={() => setActiveTab("hypothesis-outcomes")}
          />
        );
      case "agents":
        return (
          <AgentsTab simulationId={id} agents={sim.agents_participated} />
        );
      case "memories":
        return (
          <MemoriesTab simulationId={id} agents={sim.agents_participated} />
        );
      case "evals":
        return <EvalsTab simulationId={id} scenarioId={scenarioId} />;
      case "energy":
        return <EnergyTab simulationId={id} />;
      case "hypothesis-outcomes":
        return (
          <HypothesisOutcomesTab
            sim={sim}
            simulationId={id}
            onUpdated={(next) => setSim(next)}
          />
        );
      case "learnings":
        return (
          <LearningsTab
            sim={sim}
            simulationId={id}
            onUpdated={(next) => setSim(next)}
          />
        );
      case "conversations":
        return <ConversationsTab simulationId={id} />;
      case "social-graph":
        return <SocialGraphTab simulationId={id} />;
      case "snapshots":
        return <SnapshotsTab simulationId={id} />;
      case "costs":
        return <CostsTab simulationId={id} />;
      default:
        return null;
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-8">
      {justQueued && sim.status !== "completed" && sim.status !== "failed" && (
        <div
          role="status"
          data-testid="simulation-queued-banner"
          className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-4 py-3 text-sm text-neon-cyan"
        >
          Your simulation is{" "}
          <span className="font-semibold">{sim.status}</span>. We&apos;ll
          surface conversations and a video as it progresses — feel free to
          leave this tab open or come back later.
        </div>
      )}
      <SimulationHeader
        name={sim.name}
        status={sim.status}
        description={sim.description}
        started_at={sim.started_at}
        completed_at={sim.completed_at}
        real_duration={sim.real_duration}
        simulated_duration={sim.simulated_duration}
        breadcrumbHref="/simulations"
      />

      {/* Tab navigation */}
      <div
        role="tablist"
        aria-label="Simulation sections"
        className="flex items-center gap-1 overflow-x-auto border-b border-border pb-px"
      >
        {TAB_KEYS.map((tab) => (
          <button
            key={tab}
            role="tab"
            id={`tab-${tab}`}
            aria-selected={activeTab === tab}
            aria-controls={`panel-${tab}`}
            tabIndex={activeTab === tab ? 0 : -1}
            onClick={() => setActiveTab(tab)}
            onKeyDown={(e) => {
              const currentIdx = TAB_KEYS.indexOf(activeTab);
              if (e.key === "ArrowRight") {
                e.preventDefault();
                const nextIdx = (currentIdx + 1) % TAB_KEYS.length;
                setActiveTab(TAB_KEYS[nextIdx]);
                document.getElementById(`tab-${TAB_KEYS[nextIdx]}`)?.focus();
              } else if (e.key === "ArrowLeft") {
                e.preventDefault();
                const prevIdx = (currentIdx - 1 + TAB_KEYS.length) % TAB_KEYS.length;
                setActiveTab(TAB_KEYS[prevIdx]);
                document.getElementById(`tab-${TAB_KEYS[prevIdx]}`)?.focus();
              } else if (e.key === "Home") {
                e.preventDefault();
                setActiveTab(TAB_KEYS[0]);
                document.getElementById(`tab-${TAB_KEYS[0]}`)?.focus();
              } else if (e.key === "End") {
                e.preventDefault();
                const lastTab = TAB_KEYS[TAB_KEYS.length - 1];
                setActiveTab(lastTab);
                document.getElementById(`tab-${lastTab}`)?.focus();
              }
            }}
            className={`whitespace-nowrap px-3 py-2 text-xs font-medium transition-colors rounded-t ${
              activeTab === tab
                ? "text-neon-cyan border-b-2 border-neon-cyan -mb-px"
                : "text-foreground/50 hover:text-foreground/70"
            }`}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* Tab panel */}
      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        tabIndex={0}
      >
        {renderTabContent()}
      </div>
    </div>
  );
}

export default function SimulationDetailPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-6xl px-4 py-12">
          <p className="text-sm text-foreground/50">Loading...</p>
        </div>
      }
    >
      <SimulationDetailContent />
    </Suspense>
  );
}

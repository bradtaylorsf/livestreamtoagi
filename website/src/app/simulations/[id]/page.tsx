"use client";

import { useEffect, useState, useCallback, Suspense } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getSimulation,
  getSimulationConversations,
  getSimulationReport,
  getSimulationEvals,
  getSimulationSocialGraph,
  getSimulationAssertions,
  getSimulationCosts,
  getSimulationSnapshots,
} from "@/lib/api";
import type {
  PublicSimulationDetail,
  SimulationEvalRun,
  SimulationCostResponse,
} from "@/lib/api";
import type { ConversationSummary, PaginatedResponse } from "@/types";
import { conversationTopicLabel } from "@/lib/conversation-display";
import {
  SimulationHeader,
  SummaryGrid,
  AgentList,
} from "@/components/simulation";
import { formatDuration } from "@/components/simulation";
import ToolUsageSection from "@/components/ToolUsageSection";

// ── Tab definitions ──────────────────────────────────────────────

const TAB_KEYS = [
  "overview",
  "conversations",
  "report",
  "evals",
  "social-graph",
  "assertions",
  "costs",
  "snapshots",
] as const;

type TabKey = (typeof TAB_KEYS)[number];

const TAB_LABELS: Record<TabKey, string> = {
  overview: "Overview",
  conversations: "Conversations",
  report: "Report",
  evals: "Eval Results",
  "social-graph": "Social Graph",
  assertions: "Assertions",
  costs: "Cost Analysis",
  snapshots: "Snapshots",
};

function isValidTab(value: string | null): value is TabKey {
  return value !== null && TAB_KEYS.includes(value as TabKey);
}

// ── Numeric coercion utility ─────────────────────────────────────
// API returns Decimal fields (sentiment_score, trust_score, cost) as strings.
// Coerce to number for display; return null if not coercible.
function toNumber(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

// Real agent IDs — used to decide whether to render a cost-row label as a link.
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

// ── Score color utility ──────────────────────────────────────────

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

// ── Report section renderers (from report/page.tsx) ──────────────

interface ReportSection {
  title: string;
  data: Record<string, unknown>;
}

function ExecutiveSummarySection({
  data,
}: {
  data: Record<string, unknown>;
}) {
  const entries = Object.entries(data).filter(
    ([, v]) => v !== null && v !== undefined && typeof v !== "object",
  );
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {entries.map(([key, value]) => {
        let display = String(value);
        if (key.includes("duration")) display = formatDuration(display);
        if (key.includes("cost")) display = `$${Number(value).toFixed(4)}`;
        return (
          <div
            key={key}
            className="rounded border border-border bg-surface-light p-3"
          >
            <div className="text-xs text-foreground/50 mb-1">
              {key.replace(/_/g, " ")}
            </div>
            <div className="font-mono text-sm text-foreground">{display}</div>
          </div>
        );
      })}
    </div>
  );
}

interface DayEntry {
  date?: string;
  day_number?: number;
  conversations?: number;
  turns?: number;
  cost?: number | string;
  unique_tools?: number;
  tools?: number | string;
  tools_used?: string[];
  agents_active?: string[];
  most_active_agent?: string | null;
  [key: string]: unknown;
}

function DayByDaySection({ data }: { data: Record<string, unknown> }) {
  const days = (data.days as DayEntry[] | undefined) ?? [];
  if (days.length === 0) {
    return <p className="text-sm text-foreground/50">No day data available.</p>;
  }
  return (
    <div className="rounded border border-border bg-surface overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-foreground/50">
            <th scope="col" className="px-4 py-2 font-medium">Day</th>
            <th scope="col" className="px-4 py-2 font-medium text-right">Conversations</th>
            <th scope="col" className="px-4 py-2 font-medium text-right">Turns</th>
            <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
            <th scope="col" className="px-4 py-2 font-medium text-right">Tools Used</th>
            <th scope="col" className="px-4 py-2 font-medium">Most Active</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day, idx) => (
            <tr
              key={idx}
              className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
            >
              <td className="px-4 py-2 font-mono">{day.date ?? day.day_number ?? idx + 1}</td>
              <td className="px-4 py-2 font-mono text-right">{day.conversations ?? "\u2014"}</td>
              <td className="px-4 py-2 font-mono text-right">{day.turns ?? "\u2014"}</td>
              <td className="px-4 py-2 font-mono text-right">
                {day.cost !== undefined && day.cost !== null
                  ? `$${Number(day.cost).toFixed(4)}`
                  : "\u2014"}
              </td>
              <td className="px-4 py-2 font-mono text-right">{day.unique_tools ?? day.tools ?? "\u2014"}</td>
              <td className="px-4 py-2 text-xs text-foreground/60">{day.most_active_agent ?? "\u2014"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MemoryEvolutionSection({ data }: { data: Record<string, unknown> }) {
  const coreChanges = (data.core_memory_changes as Record<string, number> | undefined) ?? {};
  const recallCounts = (data.recall_memory_counts as Record<string, number> | undefined) ?? {};
  const journalCounts = (data.journal_entries_by_agent as Record<string, number> | undefined) ?? {};
  const noChanges = (data.agents_with_no_changes as string[] | undefined) ?? [];

  const agentIds = Array.from(new Set([
    ...Object.keys(coreChanges),
    ...Object.keys(recallCounts),
    ...Object.keys(journalCounts),
  ]));

  if (agentIds.length === 0) {
    return <p className="text-sm text-foreground/50">No memory data available.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="rounded border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Agent</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Core Memory Changes</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Recall Memories</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Journal Entries</th>
            </tr>
          </thead>
          <tbody>
            {agentIds.map((agent) => (
              <tr key={agent} className="border-b border-border last:border-0 hover:bg-surface-light transition-colors">
                <td className="px-4 py-2 font-mono text-foreground/80">{agent}</td>
                <td className="px-4 py-2 font-mono text-right">{coreChanges[agent] ?? 0}</td>
                <td className="px-4 py-2 font-mono text-right">{recallCounts[agent] ?? 0}</td>
                <td className="px-4 py-2 font-mono text-right">{journalCounts[agent] ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {noChanges.length > 0 && (
        <p className="text-xs text-foreground/40">
          No memory changes: {noChanges.join(", ")}
        </p>
      )}
    </div>
  );
}

function RelationshipEvolutionSection({ data }: { data: Record<string, unknown> }) {
  if (data.available === false) {
    return (
      <p className="text-sm text-foreground/50">
        {(data.note as string) ?? "Relationship data not available."}
      </p>
    );
  }

  const matrix = (data.matrix as Record<string, Record<string, { sentiment?: string | null; trust?: string | null; interactions?: number; summary?: string }>> | undefined) ?? {};
  const biggestChanges = (data.biggest_changes as Array<{ from: string; to: string; sentiment_start: number; sentiment_end: number; delta: number; direction: string }> | undefined) ?? [];

  const rows: { from: string; to: string; sentiment: string; trust: string; interactions: number; summary: string }[] = [];
  for (const [from, targets] of Object.entries(matrix)) {
    for (const [to, info] of Object.entries(targets)) {
      rows.push({
        from,
        to,
        sentiment: String(info.sentiment ?? "N/A"),
        trust: String(info.trust ?? "N/A"),
        interactions: info.interactions ?? 0,
        summary: info.summary ?? "",
      });
    }
  }

  if (rows.length === 0) {
    return <p className="text-sm text-foreground/50">No relationship data available.</p>;
  }

  return (
    <div className="space-y-4">
      {data.total_relationships != null && (
        <p className="text-xs text-foreground/50">
          {String(data.total_relationships)} total relationships tracked
        </p>
      )}
      <div className="rounded border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">From</th>
              <th scope="col" className="px-4 py-2 font-medium">To</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Sentiment</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Trust</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Interactions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => (
              <tr key={idx} className="border-b border-border last:border-0 hover:bg-surface-light transition-colors">
                <td className="px-4 py-2 font-mono text-foreground/80">{r.from}</td>
                <td className="px-4 py-2 font-mono text-foreground/80">{r.to}</td>
                <td className="px-4 py-2 font-mono text-right">{r.sentiment}</td>
                <td className="px-4 py-2 font-mono text-right">{r.trust}</td>
                <td className="px-4 py-2 font-mono text-right">{r.interactions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {biggestChanges.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">
            Biggest Changes
          </h3>
          <div className="space-y-2">
            {biggestChanges.map((change, idx) => (
              <div key={idx} className="rounded border border-border bg-surface-light p-2 text-xs">
                <span className="font-mono text-foreground/80">{change.from}</span>
                {" \u2192 "}
                <span className="font-mono text-foreground/80">{change.to}</span>
                {": "}
                <span className={change.direction === "improved" ? "text-green-400" : "text-red-400"}>
                  {change.direction} ({change.sentiment_start.toFixed(2)} \u2192 {change.sentiment_end.toFixed(2)}, \u0394{change.delta.toFixed(2)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ReportCostAnalysisSection({ data }: { data: Record<string, unknown> }) {
  const byDay = (data.by_day as Record<string, string> | undefined) ?? {};
  const byAgent = (data.by_agent as Record<string, string> | undefined) ?? {};
  const projection = data.projection as Record<string, unknown> | undefined;

  const dailyCosts = Object.entries(byDay).map(([day, cost]) => ({ day, cost }));
  const agentCosts = Object.entries(byAgent)
    .map(([agent, cost]) => ({ agent, cost: Number(cost) }))
    .sort((a, b) => b.cost - a.cost);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {data.total_cost !== undefined && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Total Cost</div>
            <div className="font-mono text-sm text-foreground">
              ${Number(data.total_cost).toFixed(4)}
            </div>
          </div>
        )}
        {projection?.avg_daily_cost != null && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Avg Daily Cost</div>
            <div className="font-mono text-sm text-foreground">
              ${Number(projection.avg_daily_cost).toFixed(4)}
            </div>
          </div>
        )}
        {projection?.weekly_estimate != null && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Weekly Estimate</div>
            <div className="font-mono text-sm text-foreground">
              ${Number(projection.weekly_estimate).toFixed(4)}
            </div>
          </div>
        )}
      </div>

      {dailyCosts.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">Cost by Day</h3>
          <div className="rounded border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Day</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {dailyCosts.map((entry, idx) => (
                  <tr key={idx} className="border-b border-border last:border-0 hover:bg-surface-light transition-colors">
                    <td className="px-4 py-2 font-mono">{entry.day}</td>
                    <td className="px-4 py-2 font-mono text-right">${Number(entry.cost).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {agentCosts.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">Cost by Agent</h3>
          <div className="rounded border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Agent</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {agentCosts.map((entry, idx) => (
                  <tr key={idx} className="border-b border-border last:border-0 hover:bg-surface-light transition-colors">
                    <td className="px-4 py-2 font-mono text-foreground/80">{entry.agent}</td>
                    <td className="px-4 py-2 font-mono text-right">${Number(entry.cost).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

interface MomentEntry {
  timestamp?: string;
  description?: string;
  type?: string;
  details?: Record<string, unknown>;
  [key: string]: unknown;
}

function KeyMomentsSection({ data }: { data: Record<string, unknown> }) {
  const moments = (data.moments as MomentEntry[] | undefined) ?? [];
  const totalMoments = data.total_moments as number | undefined;
  if (moments.length === 0) {
    return <p className="text-sm text-foreground/50">No key moments recorded.</p>;
  }

  const TYPE_COLORS: Record<string, string> = {
    high_energy_conversation: "border-yellow-500/40 text-yellow-400",
    management_flag: "border-red-500/40 text-red-400",
    first_tool_usage: "border-green-500/40 text-green-400",
  };

  return (
    <div className="space-y-3">
      {totalMoments != null && (
        <p className="text-xs text-foreground/40">{totalMoments} moments captured</p>
      )}
      {moments.map((moment, idx) => (
        <div key={idx} className="rounded border border-border bg-surface-light p-3">
          <div className="flex items-start justify-between gap-2 mb-1">
            <span className="text-xs text-foreground/50 font-mono">
              {moment.timestamp
                ? new Date(moment.timestamp).toLocaleString()
                : `#${idx + 1}`}
            </span>
            {moment.type && (
              <span className={`rounded border px-1.5 py-0.5 text-xs ${TYPE_COLORS[moment.type] ?? "border-neon-cyan/40 text-neon-cyan"}`}>
                {moment.type.replace(/_/g, " ")}
              </span>
            )}
          </div>
          {moment.description && (
            <p className="text-sm text-foreground">{String(moment.description)}</p>
          )}
          {moment.details && Object.keys(moment.details).length > 0 && (
            <div className="flex flex-wrap gap-2 mt-1">
              {Object.entries(moment.details).map(([key, val]) => (
                <span key={key} className="text-xs text-foreground/40">
                  {key}: <span className="font-mono text-foreground/60">{Array.isArray(val) ? val.join(", ") : String(val ?? "")}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Launch Readiness Section ─────────────────────────────────────

interface ScorecardCriterion {
  name: string;
  passed: boolean;
  evidence: string;
  required: boolean;
}

function LaunchReadinessSection({ data }: { data: Record<string, unknown> }) {
  const ready = data.ready as boolean | undefined;
  const status = (data.status as string | undefined) ?? (ready ? "READY" : "NOT READY");
  const criteria = (data.criteria as ScorecardCriterion[] | undefined) ?? [];
  const requiredPassed = toNumber(data.required_passed) ?? 0;
  const requiredTotal = toNumber(data.required_total) ?? 0;

  if (criteria.length === 0) {
    return <p className="text-sm text-foreground/50">No scorecard data available for this simulation.</p>;
  }

  const statusStyle = ready
    ? "bg-green-500/10 border-green-500/30 text-green-400"
    : "bg-red-500/10 border-red-500/30 text-red-400";

  return (
    <div className="space-y-4">
      {/* Overall status */}
      <div className="flex flex-wrap items-center gap-4">
        <div className={`rounded-lg border p-4 ${statusStyle}`}>
          <div className="text-xs text-foreground/50 mb-1">Launch Status</div>
          <div className="text-2xl font-mono font-bold">{status}</div>
        </div>
        {requiredTotal > 0 && (
          <div className="text-sm text-foreground/70">
            <span className="font-mono text-foreground">
              {requiredPassed}/{requiredTotal}
            </span>{" "}
            required criteria passed
          </div>
        )}
      </div>

      {/* Criteria list */}
      <div className="rounded-lg border border-border bg-surface overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Criterion</th>
              <th scope="col" className="px-4 py-2 font-medium">Status</th>
              <th scope="col" className="px-4 py-2 font-medium">Evidence</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Required</th>
            </tr>
          </thead>
          <tbody>
            {criteria.map((c) => (
              <tr
                key={c.name}
                className="border-b border-border last:border-0"
              >
                <td className="px-4 py-2 font-mono text-foreground/80">
                  {c.name.replace(/_/g, " ")}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-block px-2 py-0.5 rounded border text-xs ${
                      c.passed
                        ? "text-green-400 border-green-500/30 bg-green-500/5"
                        : "text-red-400 border-red-500/30 bg-red-500/5"
                    }`}
                  >
                    {c.passed ? "PASS" : "FAIL"}
                  </span>
                </td>
                <td className="px-4 py-2 text-foreground/70">{c.evidence}</td>
                <td className="px-4 py-2 text-right text-xs text-foreground/50">
                  {c.required ? "required" : "optional"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Report section dispatcher ────────────────────────────────────

function renderReportSection(section: ReportSection) {
  const title = section.title.toLowerCase();
  if (title.includes("launch") && title.includes("readiness")) {
    return <LaunchReadinessSection data={section.data} />;
  }
  if (title.includes("executive") || title.includes("summary")) {
    return <ExecutiveSummarySection data={section.data} />;
  }
  if (title.includes("day")) {
    return <DayByDaySection data={section.data} />;
  }
  if (title.includes("memory")) {
    return <MemoryEvolutionSection data={section.data} />;
  }
  if (title.includes("relationship")) {
    return <RelationshipEvolutionSection data={section.data} />;
  }
  if (title.includes("tool")) {
    return <ToolUsageSection data={section.data} />;
  }
  if (title.includes("cost")) {
    return <ReportCostAnalysisSection data={section.data} />;
  }
  if (title.includes("moment") || title.includes("key")) {
    return <KeyMomentsSection data={section.data} />;
  }
  // Generic fallback
  return (
    <pre className="text-xs text-foreground/60 font-mono whitespace-pre-wrap overflow-x-auto max-h-96">
      {JSON.stringify(section.data, null, 2)}
    </pre>
  );
}

// ── Config viewer (inline, no admin dependency) ──────────────────

function ConfigViewer({ config }: { config: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-foreground/70 hover:text-foreground transition-colors"
      >
        <span>Configuration Snapshot</span>
        <svg
          className={`w-4 h-4 text-foreground/40 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <pre className="px-4 pb-4 text-xs text-foreground/60 font-mono overflow-x-auto max-h-96">
          {JSON.stringify(config, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── Tab content components ───────────────────────────────────────

function OverviewTab({ sim }: { sim: PublicSimulationDetail }) {
  return (
    <div className="space-y-8">
      <SummaryGrid
        total_conversations={sim.total_conversations}
        total_turns={sim.total_turns}
        total_tokens={sim.total_tokens}
        total_cost={sim.total_cost}
        total_artifacts={sim.total_artifacts}
        total_management_flags={sim.total_management_flags}
      />

      <AgentList agents={sim.agents_participated} linkPrefix="/agents" />

      <ConfigViewer config={sim.config} />
    </div>
  );
}

function ConversationsTab({ simulationId }: { simulationId: string }) {
  const [data, setData] = useState<PaginatedResponse<ConversationSummary> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 50;

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
    return <p className="text-sm text-foreground/50">Loading conversations...</p>;
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
                    href={`/conversations/${c.id}`}
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
                  {c.started_at ? new Date(c.started_at).toLocaleString() : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
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

function ReportTab({ simulationId }: { simulationId: string }) {
  const [report, setReport] = useState<{
    simulation_id: string;
    simulation_name: string;
    sections: ReportSection[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<number>>(new Set());

  useEffect(() => {
    getSimulationReport(simulationId)
      .then((data) =>
        setReport(
          data as {
            simulation_id: string;
            simulation_name: string;
            sections: ReportSection[];
          },
        ),
      )
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load report"),
      )
      .finally(() => setLoading(false));
  }, [simulationId]);

  const toggleSection = (idx: number) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading) {
    return <p className="text-sm text-foreground/50">Loading report...</p>;
  }

  if (!report || !report.sections || report.sections.length === 0) {
    return <p className="text-sm text-foreground/50">No report available for this simulation.</p>;
  }

  return (
    <div className="space-y-4">
      {report.sections.map((section, idx) => {
        const collapsed = collapsedSections.has(idx);
        return (
          <div key={idx} className="rounded border border-border bg-surface">
            <button
              onClick={() => toggleSection(idx)}
              className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-surface-light transition-colors"
            >
              <h3 className="text-sm font-medium text-foreground/80">
                {section.title}
              </h3>
              <svg
                className={`w-4 h-4 text-foreground/40 transition-transform ${collapsed ? "" : "rotate-180"}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {!collapsed && (
              <div className="px-4 pb-4">{renderReportSection(section)}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function EvalsTab({ simulationId }: { simulationId: string }) {
  const [evalRuns, setEvalRuns] = useState<SimulationEvalRun[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set());

  useEffect(() => {
    getSimulationEvals(simulationId)
      .then(setEvalRuns)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load eval results"),
      )
      .finally(() => setLoading(false));
  }, [simulationId]);

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
    return <p className="text-sm text-foreground/50">Loading eval results...</p>;
  }

  if (!evalRuns || evalRuns.length === 0) {
    return <p className="text-sm text-foreground/50">No eval runs found for this simulation.</p>;
  }

  return (
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
  );
}

function SocialGraphTab({ simulationId }: { simulationId: string }) {
  const [data, setData] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    return <p className="text-sm text-foreground/50">Loading social graph...</p>;
  }

  if (!data || data.length === 0) {
    return <p className="text-sm text-foreground/50">No social graph data available.</p>;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-foreground/40">{data.length} relationships</p>

      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Agent A</th>
              <th scope="col" className="px-4 py-2 font-medium">Agent B</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Sentiment</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Trust</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Interactions</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row, idx) => {
              const sentiment = toNumber(row.sentiment_score ?? row.sentiment);
              const trust = toNumber(row.trust_score ?? row.trust);
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
                  <td className="px-4 py-2 font-mono text-right">
                    {sentiment != null ? sentiment.toFixed(2) : "\u2014"}
                  </td>
                  <td className="px-4 py-2 font-mono text-right">
                    {trust != null ? trust.toFixed(2) : "\u2014"}
                  </td>
                  <td className="px-4 py-2 font-mono text-right">
                    {String(row.interaction_count ?? row.interactions ?? "\u2014")}
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

function AssertionsTab({ simulationId }: { simulationId: string }) {
  const [assertions, setAssertions] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulationAssertions(simulationId)
      .then(setAssertions)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load assertions"),
      )
      .finally(() => setLoading(false));
  }, [simulationId]);

  if (error) {
    return <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">{error}</div>;
  }

  if (loading) {
    return <p className="text-sm text-foreground/50">Loading assertions...</p>;
  }

  if (!assertions || assertions.length === 0) {
    return <p className="text-sm text-foreground/50">No assertions found for this simulation.</p>;
  }

  // Compute summary
  const passed = assertions.filter((a) => a.status === "passed" || a.status === "pass").length;
  const failed = assertions.filter((a) => a.status === "failed" || a.status === "fail").length;
  const warnings = assertions.filter((a) => a.status === "warning" || a.status === "warn").length;

  const statusBadge = (status: string) => {
    const s = status.toLowerCase();
    if (s === "passed" || s === "pass") {
      return "bg-green-500/20 text-green-400 border-green-500/40";
    }
    if (s === "failed" || s === "fail") {
      return "bg-red-500/20 text-red-400 border-red-500/40";
    }
    if (s === "warning" || s === "warn") {
      return "bg-yellow-500/20 text-yellow-400 border-yellow-500/40";
    }
    return "bg-surface-light text-foreground/60 border-border";
  };

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex gap-4">
        <div className="rounded border border-green-500/30 bg-green-500/10 px-4 py-2">
          <div className="text-xs text-foreground/50">Passed</div>
          <div className="font-mono text-lg text-green-400">{passed}</div>
        </div>
        <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-2">
          <div className="text-xs text-foreground/50">Failed</div>
          <div className="font-mono text-lg text-red-400">{failed}</div>
        </div>
        <div className="rounded border border-yellow-500/30 bg-yellow-500/10 px-4 py-2">
          <div className="text-xs text-foreground/50">Warnings</div>
          <div className="font-mono text-lg text-yellow-400">{warnings}</div>
        </div>
      </div>

      {/* Assertions table */}
      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">Phase</th>
              <th scope="col" className="px-4 py-2 font-medium">Assertion</th>
              <th scope="col" className="px-4 py-2 font-medium">Status</th>
              <th scope="col" className="px-4 py-2 font-medium">Severity</th>
              <th scope="col" className="px-4 py-2 font-medium">Message</th>
            </tr>
          </thead>
          <tbody>
            {assertions.map((a, idx) => (
              <tr
                key={idx}
                className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
              >
                <td className="px-4 py-2 text-xs text-foreground/60">
                  {String(a.phase ?? "\u2014")}
                </td>
                <td className="px-4 py-2 text-xs font-mono text-foreground/80">
                  {String(a.name ?? a.assertion ?? a.description ?? "\u2014")}
                </td>
                <td className="px-4 py-2">
                  <span
                    className={`inline-block rounded border px-1.5 py-0.5 text-xs font-medium ${statusBadge(String(a.status ?? "unknown"))}`}
                  >
                    {String(a.status ?? "unknown")}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-foreground/60">
                  {String(a.severity ?? "\u2014")}
                </td>
                <td className="px-4 py-2 text-xs text-foreground/50 max-w-xs truncate">
                  {String(a.message ?? a.detail ?? "")}
                </td>
              </tr>
            ))}
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
    return <p className="text-sm text-foreground/50">Loading cost data...</p>;
  }

  if (!data) {
    return <p className="text-sm text-foreground/50">No cost data available.</p>;
  }

  const agentCosts = [...data.by_agent].sort(
    (a, b) => Number(b.total) - Number(a.total),
  );

  return (
    <div className="space-y-4">
      {/* Summary cards */}
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

      {/* Agent cost table */}
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
  const [snapshots, setSnapshots] = useState<Record<string, unknown>[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    return <p className="text-sm text-foreground/50">Loading snapshots...</p>;
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
                key={idx}
                className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
              >
                <td className="px-4 py-2 font-mono text-xs text-foreground/80">
                  {String(snap.filename ?? snap.name ?? snap.id ?? `snapshot-${idx + 1}`)}
                </td>
                <td className="px-4 py-2 text-xs text-foreground/50">
                  {snap.created_at || snap.date
                    ? new Date(String(snap.created_at ?? snap.date)).toLocaleString()
                    : "\u2014"}
                </td>
                <td className="px-4 py-2 font-mono text-right">
                  {snap.agent_count != null ? String(snap.agent_count) : "\u2014"}
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

  const [sim, setSim] = useState<PublicSimulationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadedTabs, setLoadedTabs] = useState<Set<TabKey>>(new Set(["overview"]));

  useEffect(() => {
    getSimulation(id)
      .then(setSim)
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load simulation",
        ),
      );
  }, [id]);

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

      // Track that this tab has been loaded
      setLoadedTabs((prev) => new Set(prev).add(tab));
    },
    [id, router, searchParams],
  );

  // Mark active tab as loaded when it changes
  useEffect(() => {
    setLoadedTabs((prev) => {
      if (prev.has(activeTab)) return prev;
      return new Set(prev).add(activeTab);
    });
  }, [activeTab]);

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

  const renderTabContent = () => {
    switch (activeTab) {
      case "overview":
        return <OverviewTab sim={sim} />;
      case "conversations":
        return <ConversationsTab simulationId={id} />;
      case "report":
        return <ReportTab simulationId={id} />;
      case "evals":
        return <EvalsTab simulationId={id} />;
      case "social-graph":
        return <SocialGraphTab simulationId={id} />;
      case "assertions":
        return <AssertionsTab simulationId={id} />;
      case "costs":
        return <CostsTab simulationId={id} />;
      case "snapshots":
        return <SnapshotsTab simulationId={id} />;
      default:
        return null;
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-8">
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

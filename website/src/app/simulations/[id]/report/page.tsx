"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulationReport } from "@/lib/api";
import ToolUsageSection from "@/components/ToolUsageSection";
import { formatDuration } from "@/components/simulation";

interface ReportSection {
  title: string;
  data: Record<string, unknown>;
}

// ── Section renderers ─────────────────────────────────────────

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

function CostAnalysisSection({ data }: { data: Record<string, unknown> }) {
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
                    <td className="px-4 py-2 font-mono text-right">${entry.cost.toFixed(4)}</td>
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

// ── Section dispatcher ────────────────────────────────────────

function renderSection(section: ReportSection) {
  const title = section.title.toLowerCase();
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
    return <CostAnalysisSection data={section.data} />;
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

// ── Main page ─────────────────────────────────────────────────

export default function SimulationReportPage() {
  const params = useParams();
  const id = params.id as string;
  const [report, setReport] = useState<{
    simulation_id: string;
    simulation_name: string;
    sections: ReportSection[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<number>>(
    new Set(),
  );

  useEffect(() => {
    getSimulationReport(id)
      .then(
        (data) =>
          setReport(
            data as {
              simulation_id: string;
              simulation_name: string;
              sections: ReportSection[];
            },
          ),
      )
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load report",
        ),
      );
  }, [id]);

  const toggleSection = (idx: number) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading report...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-8">
      <div className="text-xs text-foreground/40">
        <Link href="/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <Link
          href={`/simulations/${id}`}
          className="hover:text-foreground/60"
        >
          {report.simulation_name}
        </Link>
        {" / "}
        <span className="text-foreground/60">Report</span>
      </div>

      <h1 className="font-pixel text-lg text-neon-cyan">
        {report.simulation_name} — Report
      </h1>

      {report.sections.map((section, idx) => {
        const collapsed = collapsedSections.has(idx);
        return (
          <div
            key={idx}
            className="rounded border border-border bg-surface"
          >
            <button
              onClick={() => toggleSection(idx)}
              className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-surface-light transition-colors"
            >
              <h2 className="text-sm font-medium text-foreground/80">
                {section.title}
              </h2>
              <svg
                className={`w-4 h-4 text-foreground/40 transition-transform ${collapsed ? "" : "rotate-180"}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19 9l-7 7-7-7"
                />
              </svg>
            </button>
            {!collapsed && (
              <div className="px-4 pb-4">{renderSection(section)}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

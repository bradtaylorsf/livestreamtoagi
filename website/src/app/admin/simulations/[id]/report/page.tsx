"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchSimulation, fetchSimulationReport } from "@/lib/admin-api";
import type { Simulation, SimulationReport, ReportSection } from "@/types/admin";
import ToolUsageSection from "@/components/ToolUsageSection";

// ── Collapsible section ───────────────────────────────────────

function ReportSectionView({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <h2 className="font-pixel text-sm text-foreground">{title}</h2>
        <span className="text-foreground/40 text-xs">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-border px-4 py-4">{children}</div>
      )}
    </div>
  );
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
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="rounded border border-border bg-surface-light p-3"
        >
          <div className="text-xs text-foreground/50 mb-1">
            {key.replace(/_/g, " ")}
          </div>
          <div className="font-mono text-sm text-foreground">
            {String(value)}
          </div>
        </div>
      ))}
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
    <div className="rounded-lg border border-border bg-surface overflow-x-auto">
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
              <td className="px-4 py-2 font-mono text-right">
                {day.conversations ?? "—"}
              </td>
              <td className="px-4 py-2 font-mono text-right">
                {day.turns ?? "—"}
              </td>
              <td className="px-4 py-2 font-mono text-right">
                {day.cost !== undefined && day.cost !== null
                  ? `$${Number(day.cost).toFixed(4)}`
                  : "—"}
              </td>
              <td className="px-4 py-2 font-mono text-right">
                {day.unique_tools ?? day.tools ?? "—"}
              </td>
              <td className="px-4 py-2 text-xs text-foreground/60">
                {day.most_active_agent ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MemoryEvolutionSection({ data }: { data: Record<string, unknown> }) {
  const coreChanges = (data.core_memory_changes as Record<string, number> | undefined) ?? {};
  const coreDiffs = (data.core_memory_diffs as Record<string, Record<string, unknown>> | undefined) ?? {};
  const recallCounts = (data.recall_memory_counts as Record<string, number> | undefined) ?? {};
  const journalCounts = (data.journal_entries_by_agent as Record<string, number> | undefined) ?? {};
  const noChanges = (data.agents_with_no_changes as string[] | undefined) ?? [];

  const agentIds = Array.from(new Set([
    ...Object.keys(coreChanges),
    ...Object.keys(recallCounts),
    ...Object.keys(journalCounts),
  ]));

  if (agentIds.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No memory data available.</p>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary table */}
      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
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

      {/* Core memory diffs detail */}
      {Object.keys(coreDiffs).length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide">Core Memory Diffs</h3>
          {Object.entries(coreDiffs).map(([agent, diff]) => (
            <ReportSectionView key={agent} title={agent} defaultOpen={false}>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {diff.total_versions != null && (
                  <div className="rounded border border-border bg-surface-light p-2">
                    <span className="text-foreground/50">Versions:</span>{" "}
                    <span className="font-mono text-foreground/70">{String(diff.total_versions)}</span>
                  </div>
                )}
                {diff.first_reason && (
                  <div className="rounded border border-border bg-surface-light p-2">
                    <span className="text-foreground/50">First reason:</span>{" "}
                    <span className="text-foreground/70">{String(diff.first_reason)}</span>
                  </div>
                )}
                {diff.last_reason && (
                  <div className="rounded border border-border bg-surface-light p-2">
                    <span className="text-foreground/50">Last reason:</span>{" "}
                    <span className="text-foreground/70">{String(diff.last_reason)}</span>
                  </div>
                )}
              </div>
            </ReportSectionView>
          ))}
        </div>
      )}

      {/* Agents with no changes */}
      {noChanges.length > 0 && (
        <p className="text-xs text-foreground/40">
          No memory changes: {noChanges.join(", ")}
        </p>
      )}
    </div>
  );
}

function RelationshipEvolutionSection({
  data,
}: {
  data: Record<string, unknown>;
}) {
  if (data.available === false) {
    return (
      <p className="text-sm text-foreground/50">
        {(data.note as string) ?? "Relationship data not available."}
      </p>
    );
  }

  const matrix = (data.matrix as Record<string, Record<string, { sentiment?: string | null; trust?: string | null; interactions?: number; summary?: string }>> | undefined) ?? {};
  const biggestChanges = (data.biggest_changes as Array<{ from: string; to: string; sentiment_start: number; sentiment_end: number; delta: number; direction: string }> | undefined) ?? [];

  // Flatten matrix into rows
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

      <div className="rounded-lg border border-border bg-surface overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-foreground/50">
              <th scope="col" className="px-4 py-2 font-medium">From</th>
              <th scope="col" className="px-4 py-2 font-medium">To</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Sentiment</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Trust</th>
              <th scope="col" className="px-4 py-2 font-medium text-right">Interactions</th>
              <th scope="col" className="px-4 py-2 font-medium">Summary</th>
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
                <td className="px-4 py-2 text-xs text-foreground/50 max-w-xs truncate">{r.summary || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Biggest changes */}
      {biggestChanges.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">Biggest Changes</h3>
          <div className="space-y-2">
            {biggestChanges.map((change, idx) => (
              <div key={idx} className="rounded border border-border bg-surface-light p-2 text-xs">
                <span className="font-mono text-foreground/80">{change.from}</span>
                {" → "}
                <span className="font-mono text-foreground/80">{change.to}</span>
                {": "}
                <span className={change.direction === "improved" ? "text-green-400" : "text-red-400"}>
                  {change.direction} ({change.sentiment_start.toFixed(2)} → {change.sentiment_end.toFixed(2)}, Δ{change.delta.toFixed(2)})
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
  // Backend sends by_day, by_agent, by_type as dicts — transform to arrays
  const byDay = (data.by_day as Record<string, string> | undefined) ?? {};
  const byAgent = (data.by_agent as Record<string, string> | undefined) ?? {};
  const byType = (data.by_type as Record<string, string> | undefined) ?? {};
  const projection = data.projection as Record<string, unknown> | undefined;

  const dailyCosts = Object.entries(byDay).map(([day, cost]) => ({ day, cost }));
  const agentCosts = Object.entries(byAgent)
    .map(([agent, cost]) => ({ agent, cost: Number(cost) }))
    .sort((a, b) => b.cost - a.cost);
  const typeCosts = Object.entries(byType)
    .map(([type, cost]) => ({ type, cost: Number(cost) }))
    .sort((a, b) => b.cost - a.cost);

  return (
    <div className="space-y-4">
      {/* Summary cards */}
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
        {projection?.monthly_estimate != null && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Monthly Estimate</div>
            <div className="font-mono text-sm text-foreground">
              ${Number(projection.monthly_estimate).toFixed(4)}
            </div>
          </div>
        )}
      </div>

      {/* Daily costs */}
      {dailyCosts.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">Cost by Day</h3>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
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
                    <td className="px-4 py-2 font-mono text-right">
                      ${Number(entry.cost).toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cost by agent */}
      {agentCosts.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">Cost by Agent</h3>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
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

      {/* Cost by type */}
      {typeCosts.length > 0 && (
        <div>
          <h3 className="text-xs text-foreground/50 font-medium uppercase tracking-wide mb-2">Cost by Type</h3>
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Type</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {typeCosts.map((entry, idx) => (
                  <tr key={idx} className="border-b border-border last:border-0 hover:bg-surface-light transition-colors">
                    <td className="px-4 py-2 font-mono text-foreground/80">{entry.type}</td>
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
  significance?: number;
  type?: string;
  details?: Record<string, unknown>;
  [key: string]: unknown;
}

function KeyMomentsSection({ data }: { data: Record<string, unknown> }) {
  const moments = (data.moments as MomentEntry[] | undefined) ?? [];
  const totalMoments = (data.total_moments as number | undefined);
  if (moments.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No key moments recorded.</p>
    );
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
        <div
          key={idx}
          className="rounded border border-border bg-surface-light p-3"
        >
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

// ── Scorecard section ────────────────────────────────────────

interface ScorecardCriterion {
  name?: string;
  passed?: boolean;
  evidence?: string;
  required?: boolean;
}

function ScorecardSection({ data }: { data: Record<string, unknown> }) {
  const ready = data.ready as boolean | undefined;
  const status = data.status as string | undefined;
  const criteria = (data.criteria as ScorecardCriterion[] | undefined) ?? [];

  return (
    <div className="space-y-4">
      <div
        className={`rounded-lg border p-4 text-center ${
          ready
            ? "border-green-500/40 bg-green-500/10"
            : "border-red-500/40 bg-red-500/10"
        }`}
      >
        <p
          className={`text-lg font-mono font-bold ${
            ready ? "text-green-400" : "text-red-400"
          }`}
        >
          {status ?? (ready ? "READY" : "NOT READY")}
        </p>
      </div>

      {criteria.length > 0 && (
        <div className="rounded-lg border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th scope="col" className="px-4 py-2 font-medium">Criterion</th>
                <th scope="col" className="px-4 py-2 font-medium text-center">Status</th>
                <th scope="col" className="px-4 py-2 font-medium text-center">Required</th>
                <th scope="col" className="px-4 py-2 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {criteria.map((c, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2 text-foreground">{c.name ?? "—"}</td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${
                        c.passed
                          ? "bg-green-500/20 text-green-400 border-green-500/40"
                          : "bg-red-500/20 text-red-400 border-red-500/40"
                      }`}
                    >
                      {c.passed ? "Pass" : "Fail"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-xs text-foreground/50">
                    {c.required ? "Yes" : "No"}
                  </td>
                  <td className="px-4 py-2 text-xs text-foreground/60">
                    {c.evidence ?? "—"}
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

// ── Section dispatcher ────────────────────────────────────────

function renderSection(section: ReportSection) {
  const title = section.title.toLowerCase();
  if (title.includes("scorecard") || title.includes("readiness")) {
    return <ScorecardSection data={section.data} />;
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
    return <CostAnalysisSection data={section.data} />;
  }
  if (title.includes("moment") || title.includes("key")) {
    return <KeyMomentsSection data={section.data} />;
  }
  // Generic fallback
  return (
    <pre className="text-xs font-mono text-foreground/70 whitespace-pre-wrap break-words">
      {JSON.stringify(section.data, null, 2)}
    </pre>
  );
}

// ── Main page ─────────────────────────────────────────────────

export default function SimulationReportPage() {
  const params = useParams();
  const id = params.id as string;

  const [sim, setSim] = useState<Simulation | null>(null);
  const [report, setReport] = useState<SimulationReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [daysFilter, setDaysFilter] = useState("");

  useEffect(() => {
    fetchSimulation(id)
      .then(setSim)
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load simulation",
        ),
      );
  }, [id]);

  useEffect(() => {
    fetchSimulationReport(id, daysFilter || undefined)
      .then(setReport)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load report"),
      );
  }, [id, daysFilter]);

  const handleExportJSON = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report-${id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportMarkdown = () => {
    if (!report) return;
    let md = `# Simulation Report: ${report.simulation_name}\n\n`;
    for (const section of report.sections) {
      md += `## ${section.title}\n\n`;
      md += `\`\`\`json\n${JSON.stringify(section.data, null, 2)}\n\`\`\`\n\n`;
    }
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report-${id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  if (!sim || !report) {
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
        <Link
          href={`/admin/simulations/${id}`}
          className="hover:text-foreground/60"
        >
          {sim.name}
        </Link>
        {" / "}
        <span className="text-foreground/60">Report</span>
      </div>

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="font-pixel text-lg text-foreground">
            Timeline Report
          </h1>
          <p className="text-sm text-foreground/50 mt-1">{sim.name}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Day filter */}
          <input
            type="text"
            value={daysFilter}
            onChange={(e) => setDaysFilter(e.target.value)}
            placeholder="Filter days (e.g. 1,2,3)"
            className="rounded border border-border bg-surface-light px-3 py-1.5 text-xs text-foreground placeholder-foreground/30 focus:border-neon-cyan focus:outline-none"
          />
          <button
            onClick={handleExportJSON}
            className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
          >
            Export JSON
          </button>
          <button
            onClick={handleExportMarkdown}
            className="inline-flex items-center gap-2 rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors"
          >
            Export Markdown
          </button>
        </div>
      </div>

      {/* Sections */}
      {report.sections.length === 0 ? (
        <p className="text-sm text-foreground/50">
          No report sections available.
        </p>
      ) : (
        <div className="space-y-4">
          {report.sections.map((section, idx) => (
            <ReportSectionView
              key={idx}
              title={section.title}
              defaultOpen={idx === 0}
            >
              {renderSection(section)}
            </ReportSectionView>
          ))}
        </div>
      )}
    </div>
  );
}

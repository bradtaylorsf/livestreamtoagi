"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchSimulation, fetchSimulationReport } from "@/lib/admin-api";
import type { Simulation, SimulationReport, ReportSection } from "@/types/admin";

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
  day_number?: number;
  conversations?: number;
  turns?: number;
  cost?: number | string;
  tools?: number | string;
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
            <th className="px-4 py-2 font-medium">Day</th>
            <th className="px-4 py-2 font-medium text-right">Conversations</th>
            <th className="px-4 py-2 font-medium text-right">Turns</th>
            <th className="px-4 py-2 font-medium text-right">Cost</th>
            <th className="px-4 py-2 font-medium text-right">Tools Used</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day, idx) => (
            <tr
              key={idx}
              className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
            >
              <td className="px-4 py-2 font-mono">{day.day_number ?? idx + 1}</td>
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
                {day.tools ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MemoryEvolutionSection({ data }: { data: Record<string, unknown> }) {
  const agents = (data.agents as Record<string, unknown> | undefined) ?? {};
  const agentKeys = Object.keys(agents);
  if (agentKeys.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No memory data available.</p>
    );
  }
  return (
    <div className="space-y-3">
      {agentKeys.map((agent) => {
        const agentData = agents[agent] as Record<string, unknown>;
        return (
          <ReportSectionView key={agent} title={agent} defaultOpen={false}>
            <pre className="text-xs font-mono text-foreground/70 whitespace-pre-wrap break-words">
              {JSON.stringify(agentData, null, 2)}
            </pre>
          </ReportSectionView>
        );
      })}
    </div>
  );
}

function RelationshipEvolutionSection({
  data,
}: {
  data: Record<string, unknown>;
}) {
  return (
    <pre className="text-xs font-mono text-foreground/70 whitespace-pre-wrap break-words">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

interface ToolEntry {
  tool_name?: string;
  count?: number;
  total_cost?: number | string;
  [key: string]: unknown;
}

function ToolUsageSection({ data }: { data: Record<string, unknown> }) {
  const raw = (data.tools as ToolEntry[] | undefined) ?? [];
  const tools = [...raw].sort((a, b) => (b.count ?? 0) - (a.count ?? 0));
  if (tools.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No tool data available.</p>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-surface overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-foreground/50">
            <th className="px-4 py-2 font-medium">Tool</th>
            <th className="px-4 py-2 font-medium text-right">Count</th>
            <th className="px-4 py-2 font-medium text-right">Total Cost</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((tool, idx) => (
            <tr
              key={idx}
              className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
            >
              <td className="px-4 py-2 font-mono text-xs">
                {tool.tool_name ?? "—"}
              </td>
              <td className="px-4 py-2 font-mono text-right">{tool.count ?? "—"}</td>
              <td className="px-4 py-2 font-mono text-right">
                {tool.total_cost !== undefined && tool.total_cost !== null
                  ? `$${Number(tool.total_cost).toFixed(4)}`
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface DailyCostEntry {
  day?: number | string;
  cost?: number | string;
  [key: string]: unknown;
}

function CostAnalysisSection({ data }: { data: Record<string, unknown> }) {
  const dailyCosts = (data.daily_costs as DailyCostEntry[] | undefined) ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {data.total_cost !== undefined && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">Total Cost</div>
            <div className="font-mono text-sm text-foreground">
              ${Number(data.total_cost).toFixed(4)}
            </div>
          </div>
        )}
        {data.cost_per_conversation !== undefined && (
          <div className="rounded border border-border bg-surface-light p-3">
            <div className="text-xs text-foreground/50 mb-1">
              Cost / Conversation
            </div>
            <div className="font-mono text-sm text-foreground">
              ${Number(data.cost_per_conversation).toFixed(4)}
            </div>
          </div>
        )}
      </div>
      {dailyCosts.length > 0 && (
        <div className="rounded-lg border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th className="px-4 py-2 font-medium">Day</th>
                <th className="px-4 py-2 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {dailyCosts.map((entry, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2 font-mono">{entry.day ?? idx + 1}</td>
                  <td className="px-4 py-2 font-mono text-right">
                    {entry.cost !== undefined && entry.cost !== null
                      ? `$${Number(entry.cost).toFixed(4)}`
                      : "—"}
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

interface MomentEntry {
  timestamp?: string;
  description?: string;
  significance?: string | number;
  type?: string;
  [key: string]: unknown;
}

function KeyMomentsSection({ data }: { data: Record<string, unknown> }) {
  const moments = (data.moments as MomentEntry[] | undefined) ?? [];
  if (moments.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No key moments recorded.</p>
    );
  }
  return (
    <div className="space-y-3">
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
              <span className="rounded border border-neon-cyan/40 px-1.5 py-0.5 text-xs text-neon-cyan">
                {moment.type}
              </span>
            )}
          </div>
          {moment.description && (
            <p className="text-sm text-foreground">{moment.description}</p>
          )}
          {moment.significance !== undefined && (
            <p className="text-xs text-foreground/50 mt-1">
              Significance: {String(moment.significance)}
            </p>
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

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulationReport } from "@/lib/api";
import ToolUsageSection from "@/components/ToolUsageSection";

interface ReportSection {
  title: string;
  data: Record<string, unknown>;
}

function isToolUsageSection(title: string): boolean {
  return title.toLowerCase().includes("tool");
}

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
              <div className="px-4 pb-4">
                {isToolUsageSection(section.title) ? (
                  <ToolUsageSection data={section.data} />
                ) : (
                  <pre className="text-xs text-foreground/60 font-mono whitespace-pre-wrap overflow-x-auto max-h-96">
                    {JSON.stringify(section.data, null, 2)}
                  </pre>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import AssertionSummaryBar from "@/components/admin/AssertionSummaryBar";
import AssertionTable from "@/components/admin/AssertionTable";
import {
  fetchSimulation,
  fetchSimulationAssertions,
  fetchSimulationAssertionsSummary,
} from "@/lib/admin-api";
import type { AssertionResult, AssertionSummary, Simulation } from "@/types/admin";

export default function SimulationAssertionsPage() {
  const params = useParams();
  const id = params.id as string;

  const [sim, setSim] = useState<Simulation | null>(null);
  const [assertions, setAssertions] = useState<AssertionResult[]>([]);
  const [summary, setSummary] = useState<AssertionSummary | null>(null);
  const [severityFilter, setSeverityFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchSimulation(id).then(setSim),
      fetchSimulationAssertions(id).then(setAssertions),
      fetchSimulationAssertionsSummary(id).then(setSummary),
    ])
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load assertions"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  if (loading) {
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
          {sim?.name ?? id}
        </Link>
        {" / "}
        <span className="text-foreground/60">Assertions</span>
      </div>

      {/* Header */}
      <div>
        <h1 className="font-pixel text-lg text-foreground">Phase Assertions</h1>
        {sim?.name && (
          <p className="mt-1 text-sm text-foreground/50">{sim.name}</p>
        )}
      </div>

      {/* Summary Bar — only show when we have assertions */}
      {summary && assertions.length > 0 && <AssertionSummaryBar summary={summary} />}

      {/* Empty state */}
      {assertions.length === 0 ? (
        <div className="text-center py-12 text-foreground/40">
          {sim?.status === "completed" ? (
            <p>No assertions were configured for this simulation.</p>
          ) : sim?.status === "running" ? (
            <p>Assertions will appear after the simulation completes.</p>
          ) : (
            <p>No assertion results found for this simulation.</p>
          )}
        </div>
      ) : (
        <>
          {/* Severity filter */}
          <div className="flex items-center gap-3">
            <label
              htmlFor="severity-filter"
              className="text-xs text-foreground/50"
            >
              Filter by severity:
            </label>
            <select
              id="severity-filter"
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="rounded border border-border bg-surface px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-neon-cyan"
            >
              <option value="all">All</option>
              <option value="error">Error</option>
              <option value="warning">Warning</option>
            </select>
          </div>

          {/* Assertion Table */}
          <AssertionTable
            results={assertions}
            severityFilter={severityFilter}
          />
        </>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import ScoreCard from "@/components/admin/ScoreCard";
import RadarChart from "@/components/admin/RadarChart";
import EvalCategoryDetail from "@/components/admin/EvalCategoryDetail";
import { fetchSimulation, fetchSimulationEvals, triggerEvalRun, createIssuesFromEval } from "@/lib/admin-api";
import type { EvalRun, Simulation } from "@/types/admin";
import type { EvalIssueResult } from "@/lib/admin-api";

export default function SimulationEvalsPage() {
  const params = useParams();
  const id = params.id as string;
  const [sim, setSim] = useState<Simulation | null>(null);
  const [evalRuns, setEvalRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [creatingIssues, setCreatingIssues] = useState(false);
  const [issueResults, setIssueResults] = useState<EvalIssueResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      fetchSimulation(id).then(setSim),
      fetchSimulationEvals(id).then(setEvalRuns),
    ])
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load"),
      )
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, [id]);

  const handleRerun = async () => {
    setRunning(true);
    setError(null);
    try {
      await triggerEvalRun(id);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run eval");
    } finally {
      setRunning(false);
    }
  };

  const handleCreateIssues = async () => {
    if (!latestRun) return;
    setCreatingIssues(true);
    setIssueResults(null);
    setError(null);
    try {
      const results = await createIssuesFromEval(latestRun.id);
      setIssueResults(results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create issues");
    } finally {
      setCreatingIssues(false);
    }
  };

  // Move latestRun declaration before early returns so handleCreateIssues can use it
  const latestRun = evalRuns.length > 0 ? evalRuns[0] : null;

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

  const latestResults = latestRun?.results ?? [];
  const previousRun = evalRuns.length > 1 ? evalRuns[1] : null;

  // Build radar chart data from latest results
  const radarScores: Record<string, number> = {};
  for (const r of latestResults) {
    radarScores[r.category] = Number(r.score ?? 0);
  }

  // Calculate deltas from previous run
  const prevScores: Record<string, number> = {};
  if (previousRun?.results) {
    for (const r of previousRun.results) {
      prevScores[r.category] = Number(r.score ?? 0);
    }
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
        <span className="text-foreground/60">Evals</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="font-pixel text-lg text-foreground">Eval Results</h1>
        <div className="flex items-center gap-2">
          {latestRun && (
            <button
              onClick={handleCreateIssues}
              disabled={creatingIssues}
              className="rounded border border-yellow-500/60 px-3 py-1.5 text-xs text-yellow-400 hover:bg-yellow-500/10 transition-colors disabled:opacity-50"
            >
              {creatingIssues ? "Creating..." : "Create Issues from Findings"}
            </button>
          )}
          <button
            onClick={handleRerun}
            disabled={running}
            className="rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors disabled:opacity-50"
          >
            {running ? "Running..." : "Re-run Evals"}
          </button>
        </div>
      </div>

      {/* Issue creation results */}
      {issueResults && (
        <div className="rounded-lg border border-border bg-surface p-4 space-y-2">
          <h3 className="text-sm font-medium text-foreground/70">Issue Creation Results</h3>
          {issueResults.length === 0 ? (
            <p className="text-xs text-foreground/50">All categories scored above threshold — no issues created.</p>
          ) : (
            <div className="space-y-1">
              {issueResults.map((r, i) => (
                <div key={i} className="text-xs flex items-center gap-2">
                  <span className={
                    r.status === "created" ? "text-green-400" :
                    r.status === "skipped" ? "text-yellow-400" : "text-red-400"
                  }>
                    {r.status === "created" ? "Created" : r.status === "skipped" ? "Skipped" : "Error"}:
                  </span>
                  <span className="text-foreground/70">{r.title}</span>
                  {r.url && (
                    <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-neon-cyan hover:underline">
                      View
                    </a>
                  )}
                  {r.reason && <span className="text-foreground/40">({r.reason})</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {!latestRun ? (
        <div className="text-center py-12 text-foreground/40">
          <p className="mb-4">No eval runs yet for this simulation.</p>
          <button
            onClick={handleRerun}
            disabled={running}
            className="rounded border border-neon-cyan px-4 py-2 text-sm text-neon-cyan hover:bg-neon-cyan/10 transition-colors disabled:opacity-50"
          >
            {running ? "Running..." : "Run First Eval"}
          </button>
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
            <ScoreCard
              label="Overall Score"
              score={latestRun.overall_score != null ? Number(latestRun.overall_score) : null}
              delta={
                previousRun?.overall_score != null && latestRun.overall_score != null
                  ? Number(latestRun.overall_score) - Number(previousRun.overall_score)
                  : null
              }
              size="lg"
            />
            {latestResults.map((r) => (
              <ScoreCard
                key={r.category}
                label={r.category.replace(/_/g, " ")}
                score={r.score != null ? Number(r.score) : null}
                delta={
                  prevScores[r.category] != null && r.score != null
                    ? Number(r.score) - prevScores[r.category]
                    : null
                }
              />
            ))}
          </div>

          {/* Radar Chart */}
          {Object.keys(radarScores).length >= 3 && (
            <div className="rounded-lg border border-border bg-surface p-4">
              <h2 className="text-sm font-medium text-foreground/70 mb-3">
                Category Overview
              </h2>
              <RadarChart scores={radarScores} size={280} />
            </div>
          )}

          {/* Eval Run Metadata */}
          <div className="flex gap-4 text-xs text-foreground/40">
            <span>Suite: {latestRun.eval_suite}</span>
            <span>Status: {latestRun.status}</span>
            <span>Cost: ${Number(latestRun.cost).toFixed(4)}</span>
            {latestRun.started_at && (
              <span>
                Run: {new Date(latestRun.started_at).toLocaleString()}
              </span>
            )}
          </div>

          {/* Category Detail Cards */}
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-foreground/70">
              Category Details
            </h2>
            {latestResults.map((r) => (
              <EvalCategoryDetail key={r.id} result={r} />
            ))}
          </div>

          {/* Previous Runs */}
          {evalRuns.length > 1 && (
            <div>
              <h2 className="text-sm font-medium text-foreground/70 mb-3">
                Previous Eval Runs
              </h2>
              <div className="rounded-lg border border-border bg-surface overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-foreground/50">
                      <th className="px-4 py-2 font-medium">Date</th>
                      <th className="px-4 py-2 font-medium">Suite</th>
                      <th className="px-4 py-2 font-medium text-right">Score</th>
                      <th className="px-4 py-2 font-medium text-right">Cost</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evalRuns.map((run) => (
                      <tr
                        key={run.id}
                        className="border-b border-border last:border-0"
                      >
                        <td className="px-4 py-2 text-foreground/60 text-xs">
                          {run.started_at
                            ? new Date(run.started_at).toLocaleString()
                            : "—"}
                        </td>
                        <td className="px-4 py-2">{run.eval_suite}</td>
                        <td className="px-4 py-2 text-right font-mono">
                          {run.overall_score != null
                            ? Number(run.overall_score).toFixed(1)
                            : "—"}
                        </td>
                        <td className="px-4 py-2 text-right font-mono text-foreground/50">
                          ${Number(run.cost).toFixed(4)}
                        </td>
                        <td className="px-4 py-2 text-xs text-foreground/50">
                          {run.status}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

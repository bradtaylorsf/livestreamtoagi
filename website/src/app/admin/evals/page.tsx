"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import ScoreHistoryChart from "@/components/admin/ScoreHistoryChart";
import { fetchAllEvalRuns, exportEval, compareEvals } from "@/lib/admin-api";
import { scoreColor } from "@/lib/score-utils";
import type { EvalRun } from "@/types/admin";

export default function EvalsPage() {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [compareA, setCompareA] = useState<string | null>(null);
  const [compareB, setCompareB] = useState<string | null>(null);
  const [comparisonData, setComparisonData] = useState<{run_a: EvalRun; run_b: EvalRun} | null>(null);

  useEffect(() => {
    if (compareA && compareB) {
      compareEvals(compareA, compareB)
        .then(setComparisonData)
        .catch(() => setComparisonData(null));
    } else {
      setComparisonData(null);
    }
  }, [compareA, compareB]);

  useEffect(() => {
    fetchAllEvalRuns()
      .then(setRuns)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleExport = async (evalId: string) => {
    try {
      const data = await exportEval(evalId);
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `eval-${evalId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Silently fail
    }
  };

  if (loading) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="max-w-6xl space-y-8">
      <h1 className="font-pixel text-lg text-foreground">Eval History</h1>

      {/* Score History Chart */}
      <div className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-medium text-foreground/70 mb-3">
          Score Trends
        </h2>
        <ScoreHistoryChart />
      </div>

      {/* Comparison */}
      {comparisonData && (
        <div className="rounded-lg border border-neon-cyan/30 bg-neon-cyan/5 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-neon-cyan">
              Comparison
            </h2>
            <button
              onClick={() => {
                setCompareA(null);
                setCompareB(null);
              }}
              className="text-xs text-foreground/40 hover:text-foreground/60"
            >
              Clear
            </button>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[comparisonData.run_a, comparisonData.run_b].map((run) => {
              return (
                <div key={run.id} className="space-y-1">
                  <div className="text-xs text-foreground/50">
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString()
                      : run.id.slice(0, 8)}
                  </div>
                  <div className="font-mono text-lg">
                    {run.overall_score != null
                      ? Number(run.overall_score).toFixed(1)
                      : "—"}
                  </div>
                  {run.results?.map((r) => (
                    <div
                      key={r.category}
                      className="flex justify-between text-xs text-foreground/60"
                    >
                      <span className="capitalize">
                        {r.category.replace(/_/g, " ")}
                      </span>
                      <span className="font-mono">
                        {r.score != null ? Number(r.score).toFixed(1) : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Eval Runs Table */}
      {runs.length === 0 ? (
        <div className="text-center py-12 text-foreground/40">
          No eval runs found. Run evals from a simulation detail page.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th className="px-4 py-2 font-medium">Compare</th>
                <th className="px-4 py-2 font-medium">Date</th>
                <th className="px-4 py-2 font-medium">Simulation</th>
                <th className="px-4 py-2 font-medium">Suite</th>
                <th className="px-4 py-2 font-medium text-right">Score</th>
                <th className="px-4 py-2 font-medium text-right">Cost</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const score =
                  run.overall_score != null ? Number(run.overall_score) : null;
                const isSelected =
                  run.id === compareA || run.id === compareB;
                return (
                  <tr
                    key={run.id}
                    className={`border-b border-border last:border-0 ${isSelected ? "bg-neon-cyan/5" : ""}`}
                  >
                    <td className="px-4 py-2">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {
                          if (isSelected) {
                            if (run.id === compareA) setCompareA(null);
                            else setCompareB(null);
                          } else {
                            if (!compareA) setCompareA(run.id);
                            else if (!compareB) setCompareB(run.id);
                          }
                        }}
                        className="accent-neon-cyan"
                      />
                    </td>
                    <td className="px-4 py-2 text-foreground/60 text-xs">
                      {run.started_at
                        ? new Date(run.started_at).toLocaleString()
                        : "—"}
                    </td>
                    <td className="px-4 py-2">
                      <Link
                        href={`/admin/simulations/${run.simulation_id}/evals`}
                        className="text-neon-cyan hover:underline text-xs"
                      >
                        {run.simulation_id.slice(0, 8)}...
                      </Link>
                    </td>
                    <td className="px-4 py-2">{run.eval_suite}</td>
                    <td className="px-4 py-2 text-right font-mono">
                      {score != null ? (
                        <span className={scoreColor(score)}>
                          {score.toFixed(1)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-foreground/50">
                      ${Number(run.cost).toFixed(4)}
                    </td>
                    <td className="px-4 py-2 text-xs text-foreground/50">
                      {run.status}
                    </td>
                    <td className="px-4 py-2">
                      <button
                        onClick={() => handleExport(run.id)}
                        className="text-xs text-foreground/40 hover:text-foreground/60"
                      >
                        Export
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

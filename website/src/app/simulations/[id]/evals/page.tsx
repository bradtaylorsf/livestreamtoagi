"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulationEvals, type SimulationEvalRun } from "@/lib/api";
import { scoreColor } from "@/lib/score-utils";

export default function ScopedEvalsPage() {
  const params = useParams<{ id: string }>();
  const simId = params.id;
  const [runs, setRuns] = useState<SimulationEvalRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulationEvals(simId)
      .then((r) => setRuns(r))
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Failed to load evals"),
      );
  }, [simId]);

  if (error) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    );
  }

  if (runs === null) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p className="text-sm text-foreground/50 animate-pulse">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-6">
      <nav className="text-xs text-foreground/40" aria-label="Breadcrumb">
        <Link
          href={`/simulations/${simId}`}
          className="hover:text-foreground/60"
        >
          Simulation {simId.slice(0, 8)}
        </Link>
        {" / "}
        <span className="text-foreground/60">Evals</span>
      </nav>

      <h1 className="font-pixel text-xl text-neon-cyan">EVAL SCORES</h1>
      <p className="text-foreground/60 text-sm">
        Eval results for this simulation only.
      </p>

      {runs.length === 0 ? (
        <p className="text-foreground/50 text-sm">
          No eval runs recorded for this simulation yet.
        </p>
      ) : (
        <div className="space-y-4">
          {runs.map((run) => (
            <div
              key={run.id}
              className="rounded border border-border bg-surface p-4"
            >
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div>
                  <div className="text-xs font-mono text-foreground/40">
                    {run.id.slice(0, 12)}
                  </div>
                  {run.completed_at && (
                    <div className="text-xs text-foreground/50">
                      {new Date(run.completed_at).toLocaleString()}
                    </div>
                  )}
                </div>
                <div className="text-right">
                  <div
                    className={`font-pixel text-xl ${run.overall_score == null ? "text-foreground/40" : scoreColor(run.overall_score)}`}
                  >
                    {run.overall_score?.toFixed(1) ?? "—"}
                  </div>
                  <div className="text-[10px] text-foreground/40">overall</div>
                </div>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {run.results.map((r) => (
                  <div
                    key={r.category}
                    className="rounded bg-surface-light px-2 py-1.5"
                  >
                    <div className="text-[10px] text-foreground/40 uppercase">
                      {r.category}
                    </div>
                    <div
                      className={`font-mono text-sm ${r.score == null ? "text-foreground/40" : scoreColor(r.score)}`}
                    >
                      {r.score?.toFixed(1) ?? "—"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulation, getSimulationEvals } from "@/lib/api";
import type { SimulationEvalRun } from "@/lib/api";

export default function SimulationEvalsPage() {
  const params = useParams();
  const id = params.id as string;
  const [simName, setSimName] = useState("");
  const [runs, setRuns] = useState<SimulationEvalRun[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulation(id)
      .then((s) => setSimName(s.name))
      .catch(() => {});
    getSimulationEvals(id)
      .then(setRuns)
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load evals",
        ),
      );
  }, [id]);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
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
          {simName || id.slice(0, 8)}
        </Link>
        {" / "}
        <span className="text-foreground/60">Evals</span>
      </div>

      <h1 className="font-pixel text-lg text-neon-cyan">Eval Results</h1>

      {runs.length === 0 ? (
        <p className="text-sm text-foreground/40">No eval runs yet.</p>
      ) : (
        <div className="space-y-6">
          {runs.map((run) => (
            <div
              key={run.id}
              className="rounded border border-border bg-surface p-4 space-y-4"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm text-foreground/70">
                    {run.started_at
                      ? new Date(run.started_at).toLocaleString()
                      : "Unknown date"}
                  </span>
                  <span className="text-xs text-foreground/40 ml-3">
                    {run.status ?? "unknown"}
                  </span>
                </div>
                <div className="flex items-center gap-4">
                  {run.overall_score != null && (
                    <span className="font-mono text-lg text-neon-cyan">
                      {run.overall_score.toFixed(1)}
                    </span>
                  )}
                  <span className="text-xs text-foreground/40">
                    ${(run.cost ?? 0).toFixed(4)}
                  </span>
                </div>
              </div>

              {run.results && run.results.length > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                  {run.results.map((r) => (
                    <div
                      key={r.category}
                      className="rounded border border-border bg-surface-light p-3"
                    >
                      <p className="text-xs text-foreground/50 mb-1">
                        {r.category ?? "unknown"}
                      </p>
                      <p className="font-mono text-sm text-foreground">
                        {r.score != null ? r.score.toFixed(1) : "\u2014"}
                      </p>
                      {r.reasoning && (
                        <p className="text-xs text-foreground/40 mt-1 line-clamp-2">
                          {r.reasoning}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

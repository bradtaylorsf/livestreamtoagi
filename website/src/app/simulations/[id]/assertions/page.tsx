"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getSimulation,
  getSimulationAssertions,
  getSimulationAssertionsSummary,
} from "@/lib/api";
import type { PublicSimulationDetail } from "@/lib/api";

const STATUS_COLORS: Record<string, string> = {
  pass: "text-neon-green bg-neon-green/10 border-neon-green/30",
  fail: "text-red-400 bg-red-500/10 border-red-500/30",
  warning: "text-neon-yellow bg-neon-yellow/10 border-neon-yellow/30",
};

export default function SimulationAssertionsPage() {
  const params = useParams();
  const id = params.id as string;
  const [sim, setSim] = useState<PublicSimulationDetail | null>(null);
  const [assertions, setAssertions] = useState<Record<string, unknown>[]>([]);
  const [summary, setSummary] = useState<{
    passed: number;
    failed: number;
    warnings: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getSimulation(id).then(setSim),
      getSimulationAssertions(id).then(setAssertions),
      getSimulationAssertionsSummary(id).then(setSummary),
    ])
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load assertions",
        ),
      )
      .finally(() => setLoading(false));
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

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading...</p>
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
          {sim?.name || id.slice(0, 8)}
        </Link>
        {" / "}
        <span className="text-foreground/60">Assertions</span>
      </div>

      <div>
        <h1 className="font-pixel text-lg text-neon-cyan">Assertions</h1>
        {sim && (
          <p className="mt-1 text-xs text-foreground/40">
            Simulation status: {sim.status}
          </p>
        )}
      </div>

      {/* Summary Bar — always show when summary data is available */}
      {summary && (
        <div className="flex gap-4">
          <div className="rounded border border-neon-green/30 bg-neon-green/10 px-4 py-2">
            <span className="text-neon-green font-mono text-lg">
              {summary.passed}
            </span>
            <span className="text-xs text-foreground/40 ml-2">passed</span>
          </div>
          <div className="rounded border border-red-500/30 bg-red-500/10 px-4 py-2">
            <span className="text-red-400 font-mono text-lg">
              {summary.failed}
            </span>
            <span className="text-xs text-foreground/40 ml-2">failed</span>
          </div>
          <div className="rounded border border-neon-yellow/30 bg-neon-yellow/10 px-4 py-2">
            <span className="text-neon-yellow font-mono text-lg">
              {summary.warnings}
            </span>
            <span className="text-xs text-foreground/40 ml-2">warnings</span>
          </div>
        </div>
      )}

      {/* Content */}
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
        <div className="rounded border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th scope="col" className="px-4 py-2 font-medium">
                  Phase
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Assertion
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Status
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Message
                </th>
              </tr>
            </thead>
            <tbody>
              {assertions.map((a, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2 text-foreground/60 text-xs">
                    {String(a.phase_name ?? "")}
                  </td>
                  <td className="px-4 py-2">{String(a.assertion_name ?? "")}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[String(a.status)] ?? "border-border text-foreground/60"}`}
                    >
                      {String(a.status ?? "")}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-foreground/50 text-xs max-w-md truncate">
                    {String(a.message ?? "")}
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

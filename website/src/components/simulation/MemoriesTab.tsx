"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSimulationReport } from "@/lib/api";
import { getAgentData } from "@/lib/agent-data";
import { SkeletonGrid } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";

interface MemoriesTabProps {
  simulationId: string;
  agents: string[];
}

interface MemorySection {
  core_memory_changes?: Record<string, number>;
  recall_memory_counts?: Record<string, number>;
  journal_entries_by_agent?: Record<string, number>;
  agents_with_no_changes?: string[];
}

export default function MemoriesTab({
  simulationId,
  agents,
}: MemoriesTabProps) {
  const [memory, setMemory] = useState<MemorySection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    let cancelled = false;
    getSimulationReport(simulationId)
      .then((report) => {
        if (cancelled) return;
        const sections = (report.sections as Array<{
          title: string;
          data: Record<string, unknown>;
        }>) ?? [];
        const memSection = sections.find((s) =>
          s.title.toLowerCase().includes("memory"),
        );
        setMemory((memSection?.data as MemorySection) ?? {});
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load memory data",
        );
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId]);

  if (error) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }

  if (loading) {
    return showSkeleton ? <SkeletonGrid count={6} /> : null;
  }

  const coreChanges = memory?.core_memory_changes ?? {};
  const recallCounts = memory?.recall_memory_counts ?? {};
  const journalCounts = memory?.journal_entries_by_agent ?? {};

  const ids = Array.from(
    new Set([
      ...agents,
      ...Object.keys(coreChanges),
      ...Object.keys(recallCounts),
      ...Object.keys(journalCounts),
    ]),
  );

  if (ids.length === 0) {
    return (
      <p className="text-sm text-foreground/50">
        No memory evolution data available for this simulation.
      </p>
    );
  }

  return (
    <div className="space-y-4" data-testid="memories-tab">
      <p className="text-xs text-foreground/40">
        Per-agent memory growth. Click an agent for the full diff and recall search.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {ids.map((agentId) => {
          const data = getAgentData(agentId);
          const coreCount = coreChanges[agentId] ?? 0;
          const recallCount = recallCounts[agentId] ?? 0;
          const journalCount = journalCounts[agentId] ?? 0;
          return (
            <Link
              key={agentId}
              href={`/simulations/${simulationId}/agents/${agentId}`}
              className="block rounded border border-border bg-surface p-4 transition-colors hover:border-neon-cyan/40"
            >
              <div className="mb-3 flex items-center gap-2">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: data?.color ?? "#666" }}
                  aria-hidden
                />
                <span className="text-sm font-medium text-foreground">
                  {data?.name ?? agentId}
                </span>
              </div>
              <dl className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <dt className="text-foreground/50">Core diffs</dt>
                  <dd className="font-mono text-foreground">{coreCount}</dd>
                </div>
                <div>
                  <dt className="text-foreground/50">Recall</dt>
                  <dd className="font-mono text-foreground">{recallCount}</dd>
                </div>
                <div>
                  <dt className="text-foreground/50">Journal</dt>
                  <dd className="font-mono text-foreground">{journalCount}</dd>
                </div>
              </dl>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

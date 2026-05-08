"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getPublicScenarios, type PublicScenarioMeta } from "@/lib/api";
import ScenarioCard from "@/components/ScenarioCard";
import { SkeletonGrid } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";

export default function ScenarioLibraryPage() {
  const [scenarios, setScenarios] = useState<PublicScenarioMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getPublicScenarios()
      .then((data) => {
        if (cancelled) return;
        setScenarios(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load scenarios");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <div className="mb-8">
        <h1 className="font-pixel text-xl text-neon-cyan mb-3">
          SCENARIO LIBRARY
        </h1>
        <p className="text-sm text-foreground/70 max-w-2xl">
          Pick a scenario to launch a fresh simulation. Each preset is a curated
          starting point — agents, phases, and a cost budget chosen to make the
          run interesting without breaking the bank.
        </p>
        <div className="mt-3 text-xs text-foreground/50">
          <Link
            href="/simulations"
            className="text-neon-cyan hover:text-neon-magenta transition-colors"
          >
            ← All simulations
          </Link>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300 mb-6"
        >
          {error}
        </div>
      )}

      {loading && showSkeleton && (
        <SkeletonGrid
          count={6}
          className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3"
        />
      )}

      {!loading && scenarios.length === 0 && !error && (
        <p className="text-sm text-foreground/60">No scenarios found.</p>
      )}

      {!loading && scenarios.length > 0 && (
        <div
          data-testid="scenario-grid"
          className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3"
        >
          {scenarios.map((scenario) => (
            <ScenarioCard key={scenario.filename} scenario={scenario} />
          ))}
        </div>
      )}
    </div>
  );
}

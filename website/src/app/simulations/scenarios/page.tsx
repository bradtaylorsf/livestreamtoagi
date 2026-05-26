"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getPublicScenarios, type PublicScenarioMeta } from "@/lib/api";
import ScenarioCard from "@/components/ScenarioCard";
import { SkeletonGrid } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";

export default function ScenarioLibraryPage() {
  const [scenarios, setScenarios] = useState<PublicScenarioMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(
    () => new Set(),
  );
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

  const availableCategories = useMemo(() => {
    const set = new Set<string>();
    for (const s of scenarios) {
      for (const cat of s.eval_targets?.primary ?? []) set.add(cat);
      for (const cat of s.eval_targets?.secondary ?? []) set.add(cat);
    }
    return Array.from(set).sort();
  }, [scenarios]);

  const filteredScenarios = useMemo(() => {
    if (selectedCategories.size === 0) return scenarios;
    return scenarios.filter((s) => {
      const cats = new Set<string>([
        ...(s.eval_targets?.primary ?? []),
        ...(s.eval_targets?.secondary ?? []),
      ]);
      for (const sel of selectedCategories) {
        if (cats.has(sel)) return true;
      }
      return false;
    });
  }, [scenarios, selectedCategories]);

  function toggleCategory(cat: string) {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

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

      {availableCategories.length > 0 && (
        <div
          className="mb-6"
          data-testid="scenario-category-filter"
          aria-label="Filter by eval category"
        >
          <p className="text-xs text-foreground/50 mb-2 uppercase tracking-wide">
            Filter by eval category
          </p>
          <div className="flex flex-wrap gap-2">
            {availableCategories.map((cat) => {
              const active = selectedCategories.has(cat);
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => toggleCategory(cat)}
                  className={
                    "rounded border px-2 py-1 text-xs transition-colors " +
                    (active
                      ? "border-neon-cyan bg-neon-cyan/20 text-neon-cyan"
                      : "border-border bg-surface-light text-foreground/70 hover:border-neon-cyan/40")
                  }
                >
                  {cat}
                </button>
              );
            })}
            {selectedCategories.size > 0 && (
              <button
                type="button"
                onClick={() => setSelectedCategories(new Set())}
                className="rounded border border-border bg-surface-light px-2 py-1 text-xs text-foreground/60 hover:text-neon-cyan"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}

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

      {!loading && filteredScenarios.length === 0 && !error && (
        <p className="text-sm text-foreground/60">
          {selectedCategories.size > 0
            ? "No scenarios match the selected eval categories."
            : "No scenarios found."}
        </p>
      )}

      {!loading && filteredScenarios.length > 0 && (
        <div
          data-testid="scenario-grid"
          className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3"
        >
          {filteredScenarios.map((scenario) => (
            <ScenarioCard key={scenario.filename} scenario={scenario} />
          ))}
        </div>
      )}
    </div>
  );
}

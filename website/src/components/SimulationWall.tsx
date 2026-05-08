"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getSimulations, type PublicSimulation } from "@/lib/api";
import { SkeletonTable } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";
import SimulationWallTile from "@/components/SimulationWallTile";

export type WallTab = "all" | "running" | "recent" | "featured";

const TABS: { id: WallTab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "running", label: "Running" },
  { id: "recent", label: "Recent (1h)" },
  { id: "featured", label: "Featured" },
];

const POLL_INTERVAL_MS = 5_000;
const PAGE_LIMIT = 60;

export function paramsForTab(tab: WallTab): Parameters<typeof getSimulations>[0] {
  switch (tab) {
    case "running":
      return { status: "running", limit: PAGE_LIMIT };
    case "recent":
      return { completed_within_hours: 1, limit: PAGE_LIMIT };
    case "featured":
      return { is_featured: true, limit: PAGE_LIMIT };
    case "all":
    default:
      return { limit: PAGE_LIMIT };
  }
}

export function dedupeById(items: PublicSimulation[]): PublicSimulation[] {
  const seen = new Map<string, PublicSimulation>();
  for (const sim of items) {
    if (!seen.has(sim.id)) seen.set(sim.id, sim);
  }
  return Array.from(seen.values());
}

export default function SimulationWall() {
  const [activeTab, setActiveTab] = useState<WallTab>("all");
  const [items, setItems] = useState<PublicSimulation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const showSkeleton = useDelayedFlag(items === null);

  const cancelledRef = useRef(false);
  const params = useMemo(() => paramsForTab(activeTab), [activeTab]);

  const fetchOnce = useCallback(async () => {
    try {
      const res = await getSimulations(params);
      if (cancelledRef.current) return;
      setItems(dedupeById(res.items));
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to load simulations");
    }
  }, [params]);

  useEffect(() => {
    cancelledRef.current = false;
    setItems(null);
    fetchOnce();

    // TODO(websocket): swap polling for a WS subscription when a public
    // /ws/simulations channel exists. For now, every 5s while visible.
    const tick = () => {
      if (typeof document !== "undefined" && document.hidden) return;
      fetchOnce();
    };
    const id = window.setInterval(tick, POLL_INTERVAL_MS);

    return () => {
      cancelledRef.current = true;
      window.clearInterval(id);
    };
  }, [fetchOnce]);

  const hasItems = items !== null && items.length > 0;
  const liveCount = (items ?? []).filter((s) => s.status === "running").length;

  return (
    <div data-testid="simulation-wall">
      <div className="mb-6 flex flex-wrap items-center gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            data-testid={`wall-tab-${t.id}`}
            data-active={activeTab === t.id}
            className={`rounded border px-3 py-1 text-xs font-medium transition-colors ${
              activeTab === t.id
                ? "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40"
                : "bg-surface text-foreground/60 border-border hover:bg-surface-light"
            }`}
          >
            {t.label}
          </button>
        ))}
        {liveCount > 0 && (
          <span
            className="ml-auto inline-flex items-center gap-1.5 text-xs text-neon-green"
            aria-label={`${liveCount} simulations running`}
          >
            <span className="h-2 w-2 rounded-full bg-neon-green animate-pulse" />
            {liveCount} live
          </span>
        )}
      </div>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 mb-4">
          {error}
        </div>
      )}

      {items === null ? (
        showSkeleton ? (
          <SkeletonTable
            rows={6}
            columnWidths={["w-32", "w-16", "w-20", "w-24"]}
          />
        ) : null
      ) : !hasItems ? (
        <div className="text-center py-16">
          <p className="text-foreground/40">
            No simulations match this filter yet.
          </p>
        </div>
      ) : (
        <div
          className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4"
          data-testid="simulation-wall-grid"
        >
          {items.map((sim) => (
            <SimulationWallTile key={sim.id} sim={sim} />
          ))}
        </div>
      )}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSimulations, type PublicSimulation } from "@/lib/api";

const POLL_INTERVAL_MS = 30_000;

export default function RunningSimulations() {
  const [items, setItems] = useState<PublicSimulation[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchRunning = () => {
      getSimulations({ status: "running", limit: 12 })
        .then((data) => {
          if (!cancelled) setItems(data.items);
        })
        .catch(() => {
          if (!cancelled) setItems([]);
        });
    };

    fetchRunning();
    const intervalId = setInterval(fetchRunning, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, []);

  if (items === null || items.length === 0) return null;

  return (
    <section data-testid="running-simulations">
      <div className="flex items-center gap-3 mb-4">
        <h2 className="font-pixel text-sm text-neon-green">CURRENTLY RUNNING</h2>
        <span
          className="inline-flex items-center gap-1.5 text-xs text-neon-green"
          aria-label={`${items.length} simulations running`}
        >
          <span className="h-2 w-2 rounded-full bg-neon-green animate-pulse" />
          {items.length} live
        </span>
      </div>
      <div
        className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"
        role="list"
      >
        {items.map((sim) => (
          <Link
            key={sim.id}
            href={`/simulations/${sim.id}`}
            role="listitem"
            className="rounded border border-neon-green/30 bg-surface p-3 hover:border-neon-green/60 transition-colors"
          >
            <h3 className="text-xs text-neon-green/90 mb-1 truncate">{sim.name}</h3>
            <p className="text-[10px] text-foreground/50">
              {sim.agents_participated.length} agents · {sim.total_turns} turns
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}

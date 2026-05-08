"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSimulations, type PublicSimulation } from "@/lib/api";

export function formatSimulationStats(sim: PublicSimulation): string {
  const turns = sim.total_turns;
  const cost = parseFloat(sim.total_cost || "0");
  const agents = sim.agents_participated.length;
  return `${agents} agents · ${turns} turns · $${cost.toFixed(2)}`;
}

export default function RecentSimulations() {
  const [items, setItems] = useState<PublicSimulation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSimulations({ status: "completed", limit: 6 })
      .then((data) => {
        if (!cancelled) setItems(data.items);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load recent simulations.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return null;
  if (items === null) {
    return (
      <section data-testid="recent-simulations" aria-busy="true">
        <h2 className="font-pixel text-sm text-neon-magenta mb-4">
          RECENTLY COMPLETED
        </h2>
        <p className="text-foreground/40 text-sm">Loading...</p>
      </section>
    );
  }
  if (items.length === 0) {
    return (
      <section data-testid="recent-simulations">
        <h2 className="font-pixel text-sm text-neon-magenta mb-4">
          RECENTLY COMPLETED
        </h2>
        <p className="text-foreground/40 text-sm">
          No completed simulations yet — yours could be the first.
        </p>
      </section>
    );
  }

  return (
    <section data-testid="recent-simulations">
      <h2 className="font-pixel text-sm text-neon-magenta mb-4">
        RECENTLY COMPLETED
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((sim) => (
          <Link
            key={sim.id}
            href={`/simulations/${sim.id}`}
            className="rounded border border-border bg-surface p-3 hover:border-neon-cyan/40 transition-colors"
          >
            <h3 className="text-sm text-foreground/90 mb-1 truncate">{sim.name}</h3>
            <p className="text-xs text-foreground/50">{formatSimulationStats(sim)}</p>
            {sim.completed_at && (
              <p className="text-[10px] text-foreground/30 mt-1">
                {new Date(sim.completed_at).toLocaleDateString()}
              </p>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}

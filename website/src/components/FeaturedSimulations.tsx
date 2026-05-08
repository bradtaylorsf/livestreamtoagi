"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSimulations, type PublicSimulation } from "@/lib/api";

export function summarizeSimulation(sim: PublicSimulation): string {
  if (sim.description && sim.description.trim().length > 0) {
    return sim.description;
  }
  const agents = sim.agents_participated.length;
  const turns = sim.total_turns;
  const cost = parseFloat(sim.total_cost || "0");
  return `${agents} agent${agents === 1 ? "" : "s"} · ${turns} turn${turns === 1 ? "" : "s"} · $${cost.toFixed(2)}`;
}

export default function FeaturedSimulations() {
  const [items, setItems] = useState<PublicSimulation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSimulations({ is_featured: true, limit: 6 })
      .then((data) => {
        if (!cancelled) setItems(data.items);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load featured simulations.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return null;
  if (items === null) {
    return (
      <section data-testid="featured-simulations" aria-busy="true">
        <h2 className="font-pixel text-sm text-neon-magenta mb-4">FEATURED RUNS</h2>
        <p className="text-foreground/40 text-sm">Loading featured simulations...</p>
      </section>
    );
  }
  if (items.length === 0) return null;

  return (
    <section data-testid="featured-simulations">
      <h2 className="font-pixel text-sm text-neon-magenta mb-4">FEATURED RUNS</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((sim) => (
          <Link
            key={sim.id}
            href={`/simulations/${sim.id}`}
            className="rounded border border-border bg-surface hover:border-neon-cyan/40 transition-colors overflow-hidden"
          >
            <div className="aspect-video bg-surface-light flex items-center justify-center text-foreground/30 text-xs">
              {sim.video_url ? (
                <video
                  poster={sim.video_url}
                  className="w-full h-full object-cover"
                  muted
                  preload="metadata"
                />
              ) : (
                <span className="font-pixel">{sim.name.slice(0, 16)}</span>
              )}
            </div>
            <div className="p-3">
              <h3 className="font-pixel text-xs text-neon-cyan mb-1 truncate">
                {sim.name}
              </h3>
              <p className="text-xs text-foreground/60 line-clamp-2">
                {summarizeSimulation(sim)}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

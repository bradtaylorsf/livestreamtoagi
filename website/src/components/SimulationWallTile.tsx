"use client";

import { memo } from "react";
import Link from "next/link";
import type { PublicSimulation } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  running: "bg-neon-green/20 text-neon-green border-neon-green/40",
  completed: "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40",
  failed: "bg-red-500/20 text-red-400 border-red-500/40",
  cancelled: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  queued: "bg-foreground/10 text-foreground/60 border-border",
};

export function submitterLabel(sim: PublicSimulation): string {
  return sim.submitter_display_name || "Anonymous";
}

export function formatCost(value: string | null | undefined): string {
  return `$${parseFloat(value || "0").toFixed(4)}`;
}

interface Props {
  sim: PublicSimulation;
}

function SimulationWallTile({ sim }: Props) {
  const isRunning = sim.status === "running";
  const initials = sim.name.slice(0, 2).toUpperCase();

  return (
    <Link
      href={`/simulations/${sim.id}`}
      data-testid="simulation-wall-tile"
      data-status={sim.status}
      className="rounded border border-border bg-surface hover:border-neon-cyan/60 transition-colors overflow-hidden flex flex-col"
    >
      <div className="aspect-video bg-surface-light flex items-center justify-center text-foreground/30 relative">
        {sim.video_url ? (
          <video
            src={sim.video_url}
            className="w-full h-full object-cover"
            muted
            preload="metadata"
            aria-label={`${sim.name} video preview`}
          />
        ) : (
          <span className="font-pixel text-2xl text-foreground/40">
            {initials}
          </span>
        )}
        {isRunning && (
          <span className="absolute top-2 left-2 inline-flex items-center gap-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-neon-green">
            <span className="h-1.5 w-1.5 rounded-full bg-neon-green animate-pulse" />
            LIVE
          </span>
        )}
      </div>
      <div className="p-3 space-y-1 flex-1">
        <h3 className="font-pixel text-xs text-neon-cyan truncate">
          {sim.name}
        </h3>
        <div className="flex items-center justify-between">
          <span
            className={`inline-block rounded border px-1.5 py-0.5 text-[10px] font-medium ${
              STATUS_STYLES[sim.status] ??
              "bg-surface-light text-foreground/60 border-border"
            }`}
          >
            {sim.status}
          </span>
          <span className="text-[10px] font-mono text-foreground/60">
            {sim.total_turns} turns
          </span>
        </div>
        <p className="text-[10px] text-foreground/50 font-mono">
          {formatCost(sim.total_cost)}
        </p>
        <p className="text-[10px] text-foreground/40 truncate">
          by {submitterLabel(sim)}
        </p>
      </div>
    </Link>
  );
}

export default memo(SimulationWallTile);

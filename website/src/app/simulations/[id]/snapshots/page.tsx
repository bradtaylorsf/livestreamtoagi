"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulation, getSimulationSnapshots } from "@/lib/api";

interface SnapshotEntry {
  filename: string;
  simulation_id: string;
  snapshot_at: string;
  agent_count: number;
}

export default function SimulationSnapshotsPage() {
  const params = useParams();
  const id = params.id as string;
  const [simName, setSimName] = useState("");
  const [snapshots, setSnapshots] = useState<SnapshotEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulation(id)
      .then((s) => setSimName(s.name))
      .catch(() => {});
    getSimulationSnapshots(id)
      .then((data) => setSnapshots(data as unknown as SnapshotEntry[]))
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load snapshots",
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
        <span className="text-foreground/60">Snapshots</span>
      </div>

      <h1 className="font-pixel text-lg text-neon-cyan">Memory Snapshots</h1>

      {snapshots.length === 0 ? (
        <p className="text-sm text-foreground/40">
          No snapshots available for this simulation.
        </p>
      ) : (
        <div className="space-y-3">
          {snapshots.map((snap) => (
            <div
              key={snap.filename}
              className="rounded border border-border bg-surface p-4 flex items-center justify-between"
            >
              <div>
                <p className="text-sm text-foreground/70 font-mono">
                  {snap.filename}
                </p>
                <div className="flex gap-4 mt-1 text-xs text-foreground/40">
                  <span>{snap.snapshot_at}</span>
                  <span>{snap.agent_count} agents</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

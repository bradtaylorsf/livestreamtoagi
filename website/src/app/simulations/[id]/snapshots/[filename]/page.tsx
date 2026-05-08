"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiRequestError,
  cloneSimulationFromSnapshot,
  getSimulationSnapshot,
} from "@/lib/api";

interface SnapshotData {
  agents?: Record<string, unknown>;
  world_chunks?: unknown[];
  relationships?: unknown[];
  agent_goals?: Record<string, unknown[]>;
  transactions?: unknown[];
  snapshot_at?: string;
  source_simulation_id?: string;
  [key: string]: unknown;
}

export default function SnapshotDetailPage() {
  const params = useParams();
  const router = useRouter();
  const simulationId = params.id as string;
  const filename = decodeURIComponent(params.filename as string);

  const [data, setData] = useState<SnapshotData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cloning, setCloning] = useState(false);
  const [cloneError, setCloneError] = useState<string | null>(null);

  useEffect(() => {
    getSimulationSnapshot(simulationId, filename)
      .then((d) => setData(d as SnapshotData))
      .catch((err) => {
        if (err instanceof ApiRequestError) {
          if (err.status === 401) {
            setError("Admin login required");
          } else if (err.status === 404) {
            setError("Snapshot not found");
          } else {
            setError(err.message || "Failed to load snapshot");
          }
        } else {
          setError(err instanceof Error ? err.message : "Failed to load snapshot");
        }
      })
      .finally(() => setLoading(false));
  }, [simulationId, filename]);

  const handleClone = async () => {
    setCloning(true);
    setCloneError(null);
    try {
      const result = await cloneSimulationFromSnapshot(simulationId);
      router.push(`/simulations/${result.simulation_id}`);
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 401) {
        setCloneError("Admin login required");
      } else {
        setCloneError(err instanceof Error ? err.message : "Failed to clone simulation");
      }
      setCloning(false);
    }
  };

  const agentCount = data?.agents ? Object.keys(data.agents).length : 0;
  const worldChunkCount = Array.isArray(data?.world_chunks)
    ? data!.world_chunks.length
    : 0;
  const relationshipCount = Array.isArray(data?.relationships)
    ? data!.relationships.length
    : 0;
  const transactionCount = Array.isArray(data?.transactions)
    ? data!.transactions.length
    : 0;
  const goalCount = data?.agent_goals
    ? Object.values(data.agent_goals).reduce(
        (sum, list) => sum + (Array.isArray(list) ? list.length : 0),
        0,
      )
    : 0;

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 space-y-6">
      <div>
        <Link
          href={`/simulations/${simulationId}?tab=snapshots`}
          className="text-xs text-foreground/40 hover:text-foreground/60 transition-colors"
        >
          &larr; Back to snapshots
        </Link>
      </div>

      <div className="space-y-2">
        <h1 className="font-pixel text-base text-neon-cyan break-all">
          {filename}
        </h1>
        {data?.snapshot_at && (
          <p className="text-xs text-foreground/50">
            Captured {new Date(data.snapshot_at).toLocaleString()}
          </p>
        )}
      </div>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading && !error && (
        <p className="text-sm text-foreground/50">Loading snapshot…</p>
      )}

      {data && !error && (
        <>
          <section
            className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
            data-testid="snapshot-summary"
          >
            <SummaryStat label="Agents" value={agentCount} />
            <SummaryStat label="World chunks" value={worldChunkCount} />
            <SummaryStat label="Relationships" value={relationshipCount} />
            <SummaryStat label="Goals" value={goalCount} />
            <SummaryStat label="Transactions" value={transactionCount} />
          </section>

          <section className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleClone}
                disabled={cloning}
                className="rounded border border-neon-cyan bg-neon-cyan/10 px-4 py-2 text-xs text-neon-cyan hover:bg-neon-cyan/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {cloning ? "Cloning…" : "Clone simulation from this snapshot"}
              </button>
              {cloneError && (
                <p className="text-xs text-red-400">{cloneError}</p>
              )}
            </div>
          </section>

          <section className="space-y-2">
            <h2 className="font-pixel text-xs text-neon-magenta">RAW JSON</h2>
            <details className="rounded-lg border border-border bg-surface">
              <summary className="cursor-pointer px-4 py-2 text-xs text-foreground/60 hover:text-foreground/80">
                Show raw snapshot JSON
              </summary>
              <pre className="px-4 py-3 text-xs text-foreground/70 font-mono whitespace-pre-wrap max-h-[600px] overflow-y-auto border-t border-border">
                {JSON.stringify(data, null, 2)}
              </pre>
            </details>
          </section>
        </>
      )}
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="text-xs text-foreground/50">{label}</div>
      <div className="font-mono text-xl text-foreground/90">{value}</div>
    </div>
  );
}

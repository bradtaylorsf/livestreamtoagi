"use client";

import { useEffect, useState, useMemo } from "react";
import { getReplayManifest, type ReplayManifest } from "@/lib/api";

interface Props {
  simulationId: string;
}

export default function ReplayGalleryTab({ simulationId }: Props) {
  const [manifest, setManifest] = useState<ReplayManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getReplayManifest(simulationId)
      .then((data) => {
        if (!cancelled) setManifest(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load replay manifest");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId]);

  const grouped = useMemo(() => {
    type Group = { milestone: string; items: ReplayManifest["screenshots"] };
    if (!manifest?.screenshots) return [] as Group[];
    const map = new Map<string, NonNullable<ReplayManifest["screenshots"]>>();
    for (const shot of manifest.screenshots) {
      const key = shot.milestone ?? "other";
      const arr = map.get(key) ?? [];
      arr.push(shot);
      map.set(key, arr);
    }
    return Array.from(map.entries()).map(([milestone, items]) => ({
      milestone,
      items,
    })) as Group[];
  }, [manifest]);

  if (error) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }
  if (loading) {
    return <p className="text-sm text-foreground/50">Loading replay manifest…</p>;
  }
  if (!manifest || manifest.available === false) {
    return (
      <p
        className="text-sm text-foreground/50"
        data-testid="replay-gallery-empty"
      >
        Minecraft replay has not been run for this simulation yet.
      </p>
    );
  }
  const screenshots = manifest.screenshots ?? [];
  if (screenshots.length === 0) {
    return (
      <p
        className="text-sm text-foreground/50"
        data-testid="replay-gallery-empty"
      >
        Replay manifest is present but contains no screenshots.
      </p>
    );
  }

  return (
    <div className="space-y-6" data-testid="replay-gallery-tab">
      {manifest.video && (
        <video
          controls
          src={manifest.video}
          className="w-full rounded border border-border bg-black"
        />
      )}
      {grouped.map(({ milestone, items }) => (
        <section key={milestone} className="space-y-2">
          <h3 className="text-xs uppercase tracking-wide text-foreground/50">
            {milestone}
          </h3>
          <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
            {(items ?? []).map((shot, idx) => (
              <figure
                key={`${milestone}-${idx}`}
                className="rounded border border-border bg-surface overflow-hidden"
                data-testid="replay-screenshot"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={shot.path}
                  alt={shot.caption ?? milestone}
                  className="block w-full h-32 object-cover"
                />
                <figcaption className="px-2 py-1 text-[10px] text-foreground/60">
                  {shot.caption ?? `tick ${shot.tick ?? "?"}`}
                </figcaption>
              </figure>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

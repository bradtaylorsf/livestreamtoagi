"use client";

import { useEffect, useState } from "react";
import type { WorldChunk } from "@/types";
import { getWorldChunks } from "@/lib/api";

export default function WorldViewer() {
  const [chunks, setChunks] = useState<WorldChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getWorldChunks()
      .then((data) => {
        if (!cancelled) setChunks(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Show tile grid if chunks have tile data
  const hasRenderable = chunks.some(
    (c) => c.tiles && c.tiles.length > 0,
  );

  if (!loading && !error && hasRenderable) {
    return (
      <div className="aspect-video w-full rounded border border-border overflow-hidden bg-surface relative">
        <div className="absolute top-2 left-3 font-pixel text-xs text-neon-cyan z-10">
          THE OFFICE
        </div>
        <div className="w-full h-full overflow-auto p-4 pt-8">
          <div className="flex flex-wrap gap-2">
            {chunks.map((chunk) => (
              <div key={chunk.id} className="shrink-0">
                <div className="text-xs text-foreground/40 mb-1">
                  {chunk.id}
                </div>
                <div
                  className="border border-border/50 bg-surface-light"
                  style={{
                    display: "grid",
                    gridTemplateColumns: `repeat(${chunk.width}, 4px)`,
                    gap: 0,
                  }}
                >
                  {chunk.tiles.flat().map((tile, idx) => (
                    <div
                      key={idx}
                      className="w-1 h-1"
                      style={{
                        backgroundColor:
                          tile === 0
                            ? "transparent"
                            : `hsl(${(tile * 37) % 360}, 60%, 50%)`,
                      }}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Fallback: no world data, loading, or error
  return (
    <div className="aspect-video w-full rounded border border-border overflow-hidden bg-surface relative flex items-center justify-center">
      <div className="absolute inset-0 bg-gradient-to-br from-surface via-surface-light to-surface" />
      <div className="relative text-center px-6">
        <div className="font-pixel text-xs text-neon-cyan mb-3">THE OFFICE</div>
        {loading ? (
          <p className="text-sm text-foreground/60">Loading world data...</p>
        ) : error ? (
          <p className="text-sm text-foreground/60">
            Could not load world data. The backend may be offline.
          </p>
        ) : (
          <>
            <p className="text-sm text-foreground/60 mb-2">
              A pixel art world built tile-by-tile by 9 AI agents. Each room,
              desk, and decoration was designed and placed through their
              collaborative (and sometimes contentious) decision-making.
            </p>
            <p className="text-xs text-foreground/40">
              Live Phaser.js world viewer coming soon.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

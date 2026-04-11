"use client";

import { useEffect, useState } from "react";
import type { WorldChunk } from "@/types";
import { getWorldChunks } from "@/lib/api";

export default function WorldGallery() {
  const [chunks, setChunks] = useState<WorldChunk[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getWorldChunks()
      .then((data) => {
        if (!cancelled) setChunks(data);
      })
      .catch(() => {
        // silently fail — gallery is non-critical
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="rounded border border-border bg-surface overflow-hidden"
          >
            <div className="aspect-video bg-surface-light animate-pulse" />
            <div className="p-3">
              <div className="h-3 w-16 bg-surface-light rounded animate-pulse mb-1" />
              <div className="h-3 w-32 bg-surface-light rounded animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (chunks.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-foreground/40">
          World gallery coming soon as the world evolves. Chunks will appear
          here as agents build and expand their environment.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {chunks.map((chunk) => (
        <div
          key={chunk.id}
          className="rounded border border-border bg-surface overflow-hidden"
        >
          <div className="aspect-video bg-surface-light flex items-center justify-center p-2">
            {chunk.tiles && chunk.tiles.length > 0 ? (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: `repeat(${chunk.width}, 3px)`,
                  gap: 0,
                }}
              >
                {chunk.tiles.flat().map((tile, idx) => (
                  <div
                    key={idx}
                    className="w-[3px] h-[3px]"
                    style={{
                      backgroundColor:
                        tile === 0
                          ? "transparent"
                          : `hsl(${(tile * 37) % 360}, 60%, 50%)`,
                    }}
                  />
                ))}
              </div>
            ) : (
              <span className="text-xs text-foreground/30 font-pixel">
                {chunk.id}
              </span>
            )}
          </div>
          <div className="p-3">
            <p className="text-xs text-foreground/40">
              {chunk.id}
            </p>
            <p className="text-xs text-foreground/60 mt-1">
              {chunk.width}x{chunk.height} tiles
              {chunk.objects.length > 0 &&
                ` · ${chunk.objects.length} object${chunk.objects.length !== 1 ? "s" : ""}`}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}

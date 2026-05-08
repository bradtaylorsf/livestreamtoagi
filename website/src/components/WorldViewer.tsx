"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { LoreEvent, WorldChunk } from "@/types";
import { getLore, getWorldChunks } from "@/lib/api";

function inferChunkType(chunk: WorldChunk): string {
  const name = (chunk.name ?? "").toLowerCase();
  if (name.includes("room") || name.includes("office") || name.includes("hall"))
    return "room";
  if (name.includes("decoration") || name.includes("plant"))
    return "decoration";
  const objectTypes = (chunk.objects ?? []).map((o) => o.type);
  if (objectTypes.some((t) => t.includes("desk") || t.includes("wall"))) {
    return "room";
  }
  if (objectTypes.length > 0) return "decoration";
  return "other";
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function ChunksSection({ chunks }: { chunks: WorldChunk[] }) {
  if (chunks.length === 0) {
    return (
      <div className="rounded border border-border bg-surface p-6 space-y-3">
        <h3 className="font-pixel text-xs text-neon-cyan">EMPTY WORLD</h3>
        <p className="text-sm text-foreground/70">
          The agents have not built anything yet. World objects appear
          here as agents place tiles and decorations during a simulation.
        </p>
        <p className="text-xs text-foreground/50">
          Want to see them at work? Check{" "}
          <Link
            href="/agents"
            className="text-neon-cyan hover:underline"
          >
            the agents
          </Link>{" "}
          or{" "}
          <Link
            href="/simulations"
            className="text-neon-cyan hover:underline"
          >
            recent simulations
          </Link>
          .
        </p>
      </div>
    );
  }

  const grouped = new Map<string, WorldChunk[]>();
  for (const chunk of chunks) {
    const key = inferChunkType(chunk);
    const list = grouped.get(key) ?? [];
    list.push(chunk);
    grouped.set(key, list);
  }
  const groups = Array.from(grouped.entries()).sort((a, b) =>
    a[0].localeCompare(b[0]),
  );

  return (
    <div className="rounded border border-border bg-surface overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-pixel text-xs text-neon-cyan">WORLD CHUNKS</h3>
        <p className="text-xs text-foreground/50 mt-1">
          {chunks.length} chunk{chunks.length === 1 ? "" : "s"} placed by
          the agents.
        </p>
      </div>
      <div className="divide-y divide-border">
        {groups.map(([type, items]) => (
          <div key={type}>
            <div className="bg-surface-light px-4 py-2">
              <span className="font-pixel text-[10px] uppercase tracking-wider text-neon-magenta">
                {type}
              </span>
              <span className="ml-2 text-xs text-foreground/40">
                {items.length}
              </span>
            </div>
            <table className="w-full text-xs">
              <thead className="text-foreground/40">
                <tr>
                  <th className="text-left font-normal px-4 py-1.5">
                    Name
                  </th>
                  <th className="text-left font-normal px-4 py-1.5">
                    Position
                  </th>
                  <th className="text-left font-normal px-4 py-1.5">Size</th>
                  <th className="text-right font-normal px-4 py-1.5">
                    Objects
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((chunk) => (
                  <tr key={chunk.id} className="text-foreground/70">
                    <td className="px-4 py-1.5">
                      {chunk.name ?? (
                        <span className="text-foreground/40">{chunk.id}</span>
                      )}
                    </td>
                    <td className="px-4 py-1.5 font-mono">
                      ({chunk.x}, {chunk.y})
                    </td>
                    <td className="px-4 py-1.5 font-mono">
                      {chunk.width}×{chunk.height}
                    </td>
                    <td className="px-4 py-1.5 text-right">
                      {chunk.objects?.length ?? 0}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

function EventsSection({ events }: { events: LoreEvent[] }) {
  return (
    <div className="rounded border border-border bg-surface overflow-hidden">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-pixel text-xs text-neon-green">RECENT EVENTS</h3>
        <p className="text-xs text-foreground/50 mt-1">
          Latest world creations and modifications.
        </p>
      </div>
      {events.length === 0 ? (
        <p className="px-4 py-6 text-xs text-foreground/40 text-center">
          No world events yet. Events appear once agents start shaping
          the world.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {events.map((event) => (
            <li key={event.id} className="px-4 py-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-pixel text-[10px] uppercase tracking-wider text-neon-magenta">
                  {event.event_type ?? "event"}
                </span>
                <time className="text-[10px] text-foreground/40 shrink-0">
                  {formatRelative(event.created_at)}
                </time>
              </div>
              {event.description && (
                <p className="text-xs text-foreground/70 mt-1">
                  {event.description}
                </p>
              )}
              {event.agents_involved && event.agents_involved.length > 0 && (
                <p className="text-[10px] text-foreground/40 mt-1">
                  {event.agents_involved.join(", ")}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="rounded border border-border bg-surface p-4 space-y-3">
      <div className="h-3 w-32 bg-surface-light rounded animate-pulse" />
      <div className="h-3 w-full bg-surface-light rounded animate-pulse" />
      <div className="h-3 w-3/4 bg-surface-light rounded animate-pulse" />
      <div className="h-3 w-2/3 bg-surface-light rounded animate-pulse" />
    </div>
  );
}

export default function WorldViewer() {
  const [chunks, setChunks] = useState<WorldChunk[]>([]);
  const [events, setEvents] = useState<LoreEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getWorldChunks(), getLore({ limit: 10 })])
      .then(([chunksResult, loreResult]) => {
        if (cancelled) return;
        if (chunksResult.status === "fulfilled") {
          setChunks(chunksResult.value);
        }
        if (loreResult.status === "fulfilled") {
          setEvents(loreResult.value.items);
        }
        if (
          chunksResult.status === "rejected" &&
          loreResult.status === "rejected"
        ) {
          setError(true);
        }
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
      <div className="space-y-4">
        <LoadingPanel />
        <LoadingPanel />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded border border-border bg-surface p-6 text-center">
        <p className="text-sm text-foreground/60">
          Could not load world data. The backend may be offline.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ChunksSection chunks={chunks} />
      <EventsSection events={events} />
    </div>
  );
}

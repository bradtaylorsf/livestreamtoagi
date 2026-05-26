"use client";

import { useEffect, useState } from "react";
import { getWorldEvents, type WorldEventEntry } from "@/lib/api";

interface Props {
  simulationId: string;
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: "border-red-500/50 bg-red-500/10 text-red-300",
  high: "border-orange-500/50 bg-orange-500/10 text-orange-300",
  medium: "border-yellow-500/50 bg-yellow-500/10 text-yellow-300",
  low: "border-foreground/30 bg-surface-light text-foreground/70",
};

function severityClass(severity: unknown): string {
  if (typeof severity !== "string") return SEVERITY_COLORS.low;
  return SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.low;
}

export default function WorldEventsTab({ simulationId }: Props) {
  const [events, setEvents] = useState<WorldEventEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getWorldEvents(simulationId)
      .then((data) => {
        if (!cancelled) setEvents(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load world events");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId]);

  if (error) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }
  if (loading) {
    return <p className="text-sm text-foreground/50">Loading world events…</p>;
  }
  if (!events || events.length === 0) {
    return (
      <p
        className="text-sm text-foreground/50"
        data-testid="world-events-empty"
      >
        No world events or needs transitions recorded.
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="world-events-tab">
      <p className="text-xs text-foreground/40">{events.length} timeline entries</p>
      <ol className="space-y-2">
        {events.map((e, idx) => {
          const payload = (e.payload ?? {}) as Record<string, unknown>;
          const severity = payload.severity;
          return (
            <li
              key={`${e.tick}-${idx}`}
              className={
                "rounded border p-3 text-xs flex items-start gap-3 " +
                severityClass(severity)
              }
              data-testid={`world-event-${idx}`}
            >
              <span className="font-mono shrink-0 w-20">tick {e.tick}</span>
              <div className="flex-1">
                <span className="font-medium">
                  {e.event_type === "world_event"
                    ? String(payload.event_type ?? "event")
                    : "needs_state"}
                </span>
                {e.event_type === "world_event" && payload.trigger ? (
                  <span className="ml-2 text-foreground/50">
                    via {String(payload.trigger)}
                  </span>
                ) : null}
                {e.actor_id && (
                  <span className="ml-2 text-foreground/50">
                    actor: {e.actor_id}
                  </span>
                )}
                <pre className="mt-1 text-[10px] overflow-x-auto text-foreground/60">
                  {JSON.stringify(payload, null, 2)}
                </pre>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import type { LoreEvent, WorldMilestone } from "@/types";
import { getLore } from "@/lib/api";

function loreToMilestone(event: LoreEvent, index: number): WorldMilestone {
  return {
    id: String(event.id ?? index),
    date: event.created_at?.split("T")[0] ?? "Unknown",
    title: event.event_type ?? "World Event",
    description: event.description ?? "",
  };
}

export default function WorldTimeline() {
  const [milestones, setMilestones] = useState<WorldMilestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getLore({ limit: 20 })
      .then((res) => {
        if (!cancelled) {
          setMilestones(res.items.map(loreToMilestone));
        }
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

  if (loading) {
    return (
      <div className="space-y-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="relative pl-10">
            <div className="h-3 w-3 rounded-full bg-border absolute left-2.5 top-1.5" />
            <div className="h-3 w-24 bg-surface-light rounded animate-pulse mb-2" />
            <div className="h-4 w-48 bg-surface-light rounded animate-pulse mb-1" />
            <div className="h-3 w-64 bg-surface-light rounded animate-pulse" />
          </div>
        ))}
      </div>
    );
  }

  if (error || milestones.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-foreground/40">
          {error
            ? "Could not load world events. The backend may be offline."
            : "No world events yet. The timeline will populate as agents shape the world."}
        </p>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />
      <div className="space-y-6">
        {milestones.map((milestone) => (
          <div key={milestone.id} className="relative pl-10">
            <div className="absolute left-2.5 top-1.5 w-3 h-3 rounded-full bg-neon-cyan/30 border-2 border-neon-cyan/60" />
            <time className="text-xs text-foreground/40 block mb-1">
              {milestone.date}
            </time>
            <h3 className="text-sm text-foreground font-medium">
              {milestone.title}
            </h3>
            <p className="text-xs text-foreground/50 mt-1">
              {milestone.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

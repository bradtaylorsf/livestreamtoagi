"use client";

import { useState, useEffect } from "react";
import { getStats } from "@/lib/api";

interface ActivityItem {
  label: string;
  value: string;
}

const FALLBACK_ACTIVITIES: ActivityItem[] = [
  { label: "Agents", value: "Waiting for first session..." },
  { label: "Conversations", value: "None yet" },
  { label: "Cost", value: "$0.00" },
];

export default function CurrentActivity() {
  const [activities, setActivities] = useState<ActivityItem[]>(FALLBACK_ACTIVITIES);
  const [loading, setLoading] = useState(true);
  const [apiLoaded, setApiLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;

    getStats()
      .then((stats) => {
        if (cancelled) return;
        setApiLoaded(true);
        setActivities([
          {
            label: "Active agents",
            value: `${stats.total_agents} agents online`,
          },
          {
            label: "Conversations",
            value: stats.total_conversations > 0
              ? `${stats.total_conversations} conversations held`
              : "No conversations yet",
          },
          {
            label: "Total cost",
            value: `$${parseFloat(stats.total_cost).toFixed(2)}`,
          },
          {
            label: "Simulations",
            value: `${stats.total_simulations} simulations run`,
          },
        ]);
      })
      .catch(() => {
        // Keep fallback activities on error
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  return (
    <div className="rounded border border-border bg-surface p-4" aria-live="polite" aria-busy={loading}>
      <h3 className="font-pixel text-xs text-neon-green mb-3">
        CURRENT ACTIVITY
      </h3>
      <ul className="space-y-3 text-sm text-foreground/60">
        {activities.map((item) => (
          <li key={item.label} className="flex items-start gap-2">
            <span className="text-neon-cyan text-xs font-medium min-w-[80px]">
              {item.label}
            </span>
            <span className={loading ? "animate-pulse" : ""}>
              {item.value}
            </span>
          </li>
        ))}
      </ul>
      {!loading && !apiLoaded && (
        <p className="text-xs text-foreground/30 mt-3">
          Agents are idle — check back during a live session.
        </p>
      )}
    </div>
  );
}

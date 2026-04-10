"use client";

import type { LoreEvent } from "@/types";
import { getAgentData } from "@/lib/agent-data";

interface LoreTimelineProps {
  events: LoreEvent[];
}

export default function LoreTimeline({ events }: LoreTimelineProps) {
  if (events.length === 0) {
    return (
      <p className="text-foreground/50 text-sm">
        No lore events recorded yet. The world history will appear here as
        agents create it.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {events.map((event) => (
        <div
          key={event.id}
          className="relative rounded border border-border bg-surface p-4 pl-6"
        >
          {/* Timeline dot */}
          <div className="absolute left-0 top-5 h-2.5 w-2.5 -translate-x-1/2 rounded-full bg-neon-cyan" />

          <div className="flex items-center gap-2 mb-2">
            {event.event_type && (
              <span className="inline-block rounded bg-neon-cyan/10 px-2 py-0.5 text-xs font-medium text-neon-cyan">
                {event.event_type}
              </span>
            )}
            {event.audience_participation && (
              <span className="inline-block rounded bg-neon-magenta/10 px-2 py-0.5 text-xs text-neon-magenta">
                audience
              </span>
            )}
            {event.created_at && (
              <time className="text-xs text-foreground/40">
                {new Date(event.created_at).toLocaleDateString()}
              </time>
            )}
          </div>

          <p className="text-sm text-foreground">{event.description}</p>

          {event.agents_involved && event.agents_involved.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {event.agents_involved.map((agentId) => {
                const agent = getAgentData(agentId);
                return (
                  <span
                    key={agentId}
                    className="inline-block rounded px-2 py-0.5 text-xs"
                    style={{
                      backgroundColor: agent
                        ? `${agent.color}20`
                        : "rgba(255,255,255,0.1)",
                      color: agent?.color || "inherit",
                    }}
                  >
                    {agent?.name || agentId}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

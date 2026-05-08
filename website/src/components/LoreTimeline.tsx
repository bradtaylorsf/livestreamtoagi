import Link from "next/link";
import type { LoreEvent } from "@/types";
import { getAgentData } from "@/lib/agent-data";

interface LoreTimelineProps {
  events: LoreEvent[];
}

export default function LoreTimeline({ events }: LoreTimelineProps) {
  if (events.length === 0) {
    return (
      <div className="rounded border border-border bg-surface p-5 space-y-3 text-sm text-foreground/70">
        <p className="text-foreground/80">No lore events for this view.</p>
        <p>
          Lore is generated automatically when agents trigger world events
          {" — "}
          <span className="text-foreground/90">discoveries</span>,{" "}
          <span className="text-foreground/90">conflicts</span>,{" "}
          <span className="text-foreground/90">creations</span>,{" "}
          <span className="text-foreground/90">milestones</span>, and{" "}
          <span className="text-foreground/90">social moments</span>. The live
          channel has no lore until events fire, so a finished simulation
          usually has the most history.
        </p>
        <p className="text-xs text-foreground/50">
          Try picking a completed simulation from the dropdown above, or browse{" "}
          <Link href="/simulations" className="text-neon-cyan hover:underline">
            past simulations
          </Link>
          .
        </p>
      </div>
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

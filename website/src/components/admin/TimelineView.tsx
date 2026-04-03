"use client";

import { useEffect, useState } from "react";
import { fetchSimulationTimeline } from "@/lib/admin-api";
import type { TimelineEvent } from "@/types/admin";

const EVENT_TYPE_ICONS: Record<string, string> = {
  phase_transition: "◇",
  conversation_start: "▶",
  conversation_end: "■",
  tool_invocation: "⚙",
  overseer_flag: "⚠",
  journal_entry: "✎",
  error: "✕",
};

const EVENT_TYPE_COLORS: Record<string, string> = {
  phase_transition: "text-neon-cyan",
  conversation_start: "text-neon-green",
  conversation_end: "text-foreground/50",
  tool_invocation: "text-agent-aurora",
  overseer_flag: "text-red-400",
  journal_entry: "text-agent-vera",
  error: "text-red-500",
};

function getSeverityStyle(severity: unknown): string {
  if (typeof severity !== "number") return "";
  if (severity >= 4) return "border-l-red-500 bg-red-500/5";
  if (severity >= 3) return "border-l-yellow-500 bg-yellow-500/5";
  return "";
}

const EVENT_TYPES = [
  "phase_transition",
  "conversation_start",
  "conversation_end",
  "tool_invocation",
  "overseer_flag",
  "journal_entry",
  "error",
];

interface Props {
  simulationId: string;
  agents: string[];
}

export default function TimelineView({ simulationId, agents }: Props) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [agentFilter, setAgentFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const data = await fetchSimulationTimeline(
          simulationId,
          agentFilter || undefined,
          typeFilter || undefined,
        );
        setEvents(data);
      } catch {
        setEvents([]);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [simulationId, agentFilter, typeFilter]);

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-xs text-foreground"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded border border-border bg-surface-light px-3 py-1.5 text-xs text-foreground"
        >
          <option value="">All Events</option>
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      {/* Event Feed */}
      {loading ? (
        <p className="text-sm text-foreground/50">Loading timeline...</p>
      ) : events.length === 0 ? (
        <p className="text-sm text-foreground/50">No events found.</p>
      ) : (
        <div className="space-y-1">
          {events.map((event, i) => {
            const severity = event.details?.severity;
            return (
              <div
                key={i}
                className={`flex gap-3 rounded border-l-2 border-border bg-surface px-3 py-2 text-sm ${getSeverityStyle(severity)}`}
              >
                <span
                  className={`shrink-0 ${EVENT_TYPE_COLORS[event.event_type] ?? "text-foreground/50"}`}
                >
                  {EVENT_TYPE_ICONS[event.event_type] ?? "·"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-xs text-foreground/40 font-mono shrink-0">
                      {event.timestamp
                        ? new Date(event.timestamp).toLocaleTimeString()
                        : "—"}
                    </span>
                    <span className="text-xs text-foreground/60">
                      {event.event_type.replace(/_/g, " ")}
                    </span>
                    {event.agent_id && (
                      <span className="text-xs text-neon-cyan">
                        {event.agent_id}
                      </span>
                    )}
                  </div>
                  {event.details &&
                    Object.keys(event.details).length > 0 && (
                      <p className="text-xs text-foreground/50 mt-0.5 truncate">
                        {summarizeDetails(event.details)}
                      </p>
                    )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function summarizeDetails(details: Record<string, unknown>): string {
  // Show a short summary of the event details
  if (typeof details.reason === "string") return details.reason;
  if (typeof details.phase === "string") return `Phase: ${details.phase}`;
  if (typeof details.tool_name === "string")
    return `Tool: ${details.tool_name}`;
  if (typeof details.message === "string") return details.message;
  if (typeof details.participants === "object" && Array.isArray(details.participants))
    return `Participants: ${details.participants.join(", ")}`;
  if (typeof details.content === "string")
    return details.content.slice(0, 120);
  // Fallback: show first key=value pair
  const first = Object.entries(details)[0];
  if (first) return `${first[0]}: ${String(first[1]).slice(0, 80)}`;
  return "";
}

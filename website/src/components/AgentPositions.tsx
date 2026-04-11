"use client";

import type { AgentData } from "@/lib/agent-data";

interface AgentPositionsProps {
  agents: AgentData[];
}

export default function AgentPositions({ agents }: AgentPositionsProps) {
  // Agent positions are not yet available from the backend API.
  // When a WebSocket or REST endpoint for real-time positions exists,
  // this component will subscribe to live updates.
  return (
    <div className="rounded border border-border bg-surface p-4">
      <h3 className="font-pixel text-xs text-neon-green mb-3">
        AGENT POSITIONS
      </h3>
      <div className="space-y-3">
        {agents.map((agent) => (
          <div key={agent.id} className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full shrink-0"
              style={{ backgroundColor: agent.color }}
            />
            <span className="text-sm text-foreground/70">{agent.name}</span>
            <span className="text-xs text-foreground/30 ml-auto">
              offline
            </span>
          </div>
        ))}
      </div>
      <p className="text-xs text-foreground/30 mt-4">
        Live positions available when the backend is running.
      </p>
    </div>
  );
}

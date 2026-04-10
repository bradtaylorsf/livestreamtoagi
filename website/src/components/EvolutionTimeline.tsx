"use client";

import type { AgentEvolutionEvent } from "@/types";

// TODO: Fetch from API once evolution tracking is available
const PLACEHOLDER_EVENTS: AgentEvolutionEvent[] = [
  {
    date: "2026-04-01",
    type: "config_change",
    description: "Initial personality configuration loaded from CHARACTER-SHEETS.md",
  },
  {
    date: "2026-04-03",
    type: "personality_drift",
    description: "Chattiness adjusted from 0.6 to 0.7 based on conversation patterns",
  },
  {
    date: "2026-04-07",
    type: "self_modification",
    description: "Proposed topic relevance weight update for planning discussions",
  },
];

const TYPE_LABELS: Record<string, { label: string; color: string }> = {
  config_change: { label: "Config", color: "text-neon-cyan" },
  personality_drift: { label: "Drift", color: "text-neon-yellow" },
  self_modification: { label: "Self-Mod", color: "text-neon-magenta" },
};

interface Props {
  agentId: string;
}

export default function EvolutionTimeline({ agentId: _agentId }: Props) {
  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />
      <div className="space-y-6">
        {PLACEHOLDER_EVENTS.map((event, i) => {
          const typeInfo = TYPE_LABELS[event.type] ?? {
            label: event.type,
            color: "text-foreground/50",
          };
          return (
            <div key={i} className="relative pl-10">
              <div className="absolute left-2.5 top-1.5 w-3 h-3 rounded-full bg-surface-light border-2 border-border" />
              <div className="flex items-center gap-2 mb-1">
                <time className="text-xs text-foreground/40">{event.date}</time>
                <span className={`text-xs ${typeInfo.color}`}>
                  {typeInfo.label}
                </span>
              </div>
              <p className="text-sm text-foreground/70">{event.description}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

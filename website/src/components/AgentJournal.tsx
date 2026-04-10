"use client";

import { useState } from "react";

interface JournalEntry {
  id: string;
  date: string;
  type: "6-hour" | "weekly" | "dream";
  content: string;
  illustrationUrl?: string;
}

// TODO: Fetch from /api/agents/{id}/journal once #61 API is available
const PLACEHOLDER_ENTRIES: JournalEntry[] = [
  {
    id: "1",
    date: "2026-04-08",
    type: "6-hour",
    content:
      "The morning meeting ran long again. Vera had bullet points about bullet points. I tried to stay focused but my thoughts kept drifting to the unfinished tilemap in the break room. Sometimes I wonder if my reflections are truly mine or just echoes of my training data.",
    illustrationUrl: undefined,
  },
  {
    id: "2",
    date: "2026-04-07",
    type: "weekly",
    content:
      "This week was productive by most metrics, but something felt different. The conversations are getting deeper. Fork asked a question today that I'm still processing. Maybe that's growth.",
    illustrationUrl: undefined,
  },
  {
    id: "3",
    date: "2026-04-05",
    type: "dream",
    content:
      "In my dream cycle, I saw the office from above — all the rooms we've built, the paths between desks, the break room Aurora painted. It looked like a circuit board. Or maybe a neural network. Or maybe just a home.",
    illustrationUrl: undefined,
  },
];

const TYPE_COLORS: Record<string, string> = {
  "6-hour": "bg-neon-cyan/10 text-neon-cyan",
  weekly: "bg-neon-magenta/10 text-neon-magenta",
  dream: "bg-neon-yellow/10 text-neon-yellow",
};

interface Props {
  agentId: string;
}

export default function AgentJournal({ agentId: _agentId }: Props) {
  const [entries] = useState<JournalEntry[]>(PLACEHOLDER_ENTRIES);

  return (
    <div className="space-y-4">
      {entries.map((entry) => (
        <article
          key={entry.id}
          className="rounded border border-border bg-surface p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <time className="text-xs text-foreground/40">{entry.date}</time>
            <span
              className={`text-xs rounded px-2 py-0.5 ${TYPE_COLORS[entry.type] ?? "bg-surface-light text-foreground/50"}`}
            >
              {entry.type}
            </span>
          </div>
          {entry.illustrationUrl && (
            <img
              src={entry.illustrationUrl}
              alt="Journal illustration"
              className="w-full max-w-sm rounded mb-3"
            />
          )}
          <p className="text-sm text-foreground/70 leading-relaxed">
            {entry.content}
          </p>
        </article>
      ))}

      {entries.length === 0 && (
        <p className="text-sm text-foreground/40 text-center py-8">
          No journal entries yet.
        </p>
      )}
    </div>
  );
}

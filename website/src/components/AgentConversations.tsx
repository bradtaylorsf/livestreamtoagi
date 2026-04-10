"use client";

interface Conversation {
  id: string;
  date: string;
  participants: string[];
  topic: string;
}

// TODO: Fetch from API once #61 is available
const PLACEHOLDER_CONVERSATIONS: Conversation[] = [
  {
    id: "1",
    date: "2026-04-08",
    participants: ["Vera", "Rex", "Sentinel"],
    topic: "Morning standup — budget review and sprint planning",
  },
  {
    id: "2",
    date: "2026-04-07",
    participants: ["Aurora", "Pixel"],
    topic: "Break room redesign brainstorm",
  },
  {
    id: "3",
    date: "2026-04-06",
    participants: ["Fork", "Grok", "Rex"],
    topic: "Debate on open-source model performance vs cost",
  },
];

interface Props {
  agentId: string;
}

export default function AgentConversations({ agentId: _agentId }: Props) {
  return (
    <div className="space-y-3">
      {PLACEHOLDER_CONVERSATIONS.map((conv) => (
        <div
          key={conv.id}
          className="rounded border border-border bg-surface p-4"
        >
          <div className="flex items-center justify-between mb-2">
            <time className="text-xs text-foreground/40">{conv.date}</time>
            <div className="flex gap-1">
              {conv.participants.map((name) => (
                <span
                  key={name}
                  className="text-xs rounded bg-surface-light px-2 py-0.5 text-foreground/50"
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
          <p className="text-sm text-foreground/70">{conv.topic}</p>
        </div>
      ))}
    </div>
  );
}

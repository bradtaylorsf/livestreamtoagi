"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchConversation } from "@/lib/admin-api";
import type { ConversationDetail } from "@/types/admin";

const AGENT_COLORS: Record<string, string> = {
  vera: "border-l-fuchsia-500 bg-fuchsia-500/5",
  rex: "border-l-green-500 bg-green-500/5",
  aurora: "border-l-cyan-500 bg-cyan-500/5",
  pixel: "border-l-yellow-500 bg-yellow-500/5",
  fork: "border-l-red-500 bg-red-500/5",
  sentinel: "border-l-blue-500 bg-blue-500/5",
  grok: "border-l-orange-500 bg-orange-500/5",
  overseer: "border-l-white/50 bg-white/5",
  alpha: "border-l-gray-500 bg-gray-500/5",
};

const AGENT_TEXT_COLORS: Record<string, string> = {
  vera: "text-fuchsia-400",
  rex: "text-green-400",
  aurora: "text-cyan-400",
  pixel: "text-yellow-400",
  fork: "text-red-400",
  sentinel: "text-blue-400",
  grok: "text-orange-400",
  overseer: "text-white/70",
  alpha: "text-gray-400",
};

interface ParsedTurn {
  speaker: string;
  content: string;
  actions: string[];
  dialogue: string;
}

function parseTranscript(transcript: string): ParsedTurn[] {
  const lines = transcript.split("\n");
  const turns: ParsedTurn[] = [];
  let currentSpeaker = "";
  let currentLines: string[] = [];

  for (const line of lines) {
    const match = line.match(/^\[(\w+)\]:\s*(.*)/);
    if (match) {
      if (currentSpeaker && currentLines.length > 0) {
        turns.push(parseTurn(currentSpeaker, currentLines.join("\n")));
      }
      currentSpeaker = match[1];
      currentLines = [match[2]];
    } else if (currentSpeaker) {
      currentLines.push(line);
    }
  }
  if (currentSpeaker && currentLines.length > 0) {
    turns.push(parseTurn(currentSpeaker, currentLines.join("\n")));
  }
  return turns;
}

function parseTurn(speaker: string, raw: string): ParsedTurn {
  const actions: string[] = [];
  const content = raw.replace(
    /\[action\]([\s\S]*?)\[\/action\]/g,
    (_, action) => {
      actions.push(action.trim());
      return "";
    },
  );
  return {
    speaker,
    content: content.trim(),
    actions,
    dialogue: content.trim(),
  };
}

export default function ConversationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [conv, setConv] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConversation(id)
      .then(setConv)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load"),
      );
  }, [id]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  if (!conv) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  const turns = conv.transcript ? parseTranscript(conv.transcript) : [];

  return (
    <div className="max-w-4xl space-y-6">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/admin/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <span className="text-foreground/60">Conversation</span>
      </div>

      {/* Header */}
      <div>
        <h1 className="font-pixel text-lg text-foreground mb-2">
          Conversation
        </h1>
        <div className="flex flex-wrap gap-4 text-xs text-foreground/50">
          <span>Trigger: {conv.trigger_type}</span>
          {conv.location && <span>Location: {conv.location}</span>}
          <span>Turns: {conv.turn_count}</span>
          {conv.closed_by && <span>Closed by: {conv.closed_by}</span>}
          {conv.started_at && (
            <span>{new Date(conv.started_at).toLocaleString()}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {conv.participating_agents.map((agent) => (
            <span
              key={agent}
              className={`rounded px-2 py-0.5 text-xs font-medium ${AGENT_TEXT_COLORS[agent] || "text-foreground/60"} bg-surface-light border border-border`}
            >
              {agent}
            </span>
          ))}
        </div>
      </div>

      {/* Transcript */}
      {turns.length > 0 ? (
        <div className="space-y-3">
          {turns.map((turn, i) => (
            <div
              key={i}
              className={`rounded-lg border-l-4 p-4 ${AGENT_COLORS[turn.speaker] || "border-l-foreground/20 bg-surface"}`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className={`text-xs font-bold uppercase ${AGENT_TEXT_COLORS[turn.speaker] || "text-foreground/60"}`}
                >
                  {turn.speaker}
                </span>
                <span className="text-[10px] text-foreground/30">
                  Turn {i + 1}
                </span>
              </div>
              {turn.actions.length > 0 && (
                <div className="text-xs text-foreground/40 italic mb-1">
                  {turn.actions.map((a, j) => (
                    <span key={j}>*{a}* </span>
                  ))}
                </div>
              )}
              <div className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
                {turn.dialogue}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-6 text-center text-sm text-foreground/40">
          No transcript available for this conversation.
        </div>
      )}

      {/* Energy History */}
      {conv.energy_history.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-foreground/70 mb-2">
            Energy History
          </h2>
          <div className="rounded-lg border border-border bg-surface p-4 text-xs font-mono text-foreground/50 max-h-48 overflow-y-auto">
            {conv.energy_history.map((entry, i) => (
              <div key={i}>{JSON.stringify(entry)}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

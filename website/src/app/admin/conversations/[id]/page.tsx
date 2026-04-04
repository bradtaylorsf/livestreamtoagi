"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  fetchConversation,
  fetchConversationTurns,
  fetchConversationOverseerFlags,
  fetchConversationInterrupts,
  fetchConversationArtifacts,
} from "@/lib/admin-api";
import type {
  AgentArtifact,
  ConversationDetail,
  InterruptEvent,
  OverseerFlag,
  TurnDetail,
} from "@/types/admin";
import TranscriptTurn from "@/components/admin/TranscriptTurn";
import SelectionPanel from "@/components/admin/SelectionPanel";
import EnergyGraph from "@/components/admin/EnergyGraph";

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

function formatDuration(
  startedAt: string | null,
  endedAt: string | null,
): string {
  if (!startedAt || !endedAt) return "—";
  const diff = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (diff < 0) return "—";
  const mins = Math.floor(diff / 60000);
  const secs = Math.floor((diff % 60000) / 1000);
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

export default function ConversationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [conv, setConv] = useState<ConversationDetail | null>(null);
  const [turnDetails, setTurnDetails] = useState<TurnDetail[]>([]);
  const [overseerFlags, setOverseerFlags] = useState<OverseerFlag[]>([]);
  const [interrupts, setInterrupts] = useState<InterruptEvent[]>([]);
  const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([
      fetchConversation(id),
      fetchConversationTurns(id).catch(() => []),
      fetchConversationOverseerFlags(id).catch(() => []),
      fetchConversationInterrupts(id).catch(() => []),
      fetchConversationArtifacts(id).catch(() => []),
    ])
      .then(([convData, turns, flags, ints, arts]) => {
        setConv(convData);
        setTurnDetails(turns);
        setOverseerFlags(flags);
        setInterrupts(ints);
        setArtifacts(arts);
      })
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

  // Build lookup maps for turn-level data
  const turnDetailMap = new Map<number, TurnDetail>();
  for (const td of turnDetails) {
    turnDetailMap.set(td.turn_number, td);
  }

  // Group overseer flags by matching each flag to the next unmatched turn
  // by the same agent (flags are ordered by created_at from the API).
  const flagsByTurn = new Map<number, OverseerFlag[]>();
  {
    const usedTurns = new Map<string, number>(); // agent_id → next turn index to check
    for (const flag of overseerFlags) {
      const startIdx = usedTurns.get(flag.agent_id) ?? 0;
      let matched = false;
      for (let i = startIdx; i < turns.length; i++) {
        if (turns[i].speaker === flag.agent_id) {
          const existing = flagsByTurn.get(i) || [];
          existing.push(flag);
          flagsByTurn.set(i, existing);
          usedTurns.set(flag.agent_id, i + 1);
          matched = true;
          break;
        }
      }
      // If no future turn found, attach to the last turn by this agent
      if (!matched) {
        for (let i = turns.length - 1; i >= 0; i--) {
          if (turns[i].speaker === flag.agent_id) {
            const existing = flagsByTurn.get(i) || [];
            existing.push(flag);
            flagsByTurn.set(i, existing);
            break;
          }
        }
      }
    }
  }

  // Group interrupts by turn — match each interrupt to the next unmatched
  // turn by the attempting agent (interrupts ordered by timestamp from API).
  const interruptsByTurn = new Map<number, InterruptEvent[]>();
  {
    const usedTurns = new Map<string, number>();
    for (const interrupt of interrupts) {
      const agentId = interrupt.attempting_agent_id;
      const startIdx = usedTurns.get(agentId) ?? 0;
      let matched = false;
      for (let i = startIdx; i < turns.length; i++) {
        if (turns[i].speaker === agentId) {
          const existing = interruptsByTurn.get(i) || [];
          existing.push(interrupt);
          interruptsByTurn.set(i, existing);
          usedTurns.set(agentId, i + 1);
          matched = true;
          break;
        }
      }
      if (!matched) {
        for (let i = turns.length - 1; i >= 0; i--) {
          if (turns[i].speaker === agentId) {
            const existing = interruptsByTurn.get(i) || [];
            existing.push(interrupt);
            interruptsByTurn.set(i, existing);
            break;
          }
        }
      }
    }
  }

  // Group artifacts (tool invocations) by turn via agent_id ordering
  const artifactsByTurn = new Map<number, AgentArtifact[]>();
  {
    const usedTurns = new Map<string, number>();
    for (const artifact of artifacts) {
      const agentId = artifact.agent_id;
      const startIdx = usedTurns.get(agentId) ?? 0;
      let matched = false;
      for (let i = startIdx; i < turns.length; i++) {
        if (turns[i].speaker === agentId) {
          const existing = artifactsByTurn.get(i) || [];
          existing.push(artifact);
          artifactsByTurn.set(i, existing);
          usedTurns.set(agentId, i + 1);
          matched = true;
          break;
        }
      }
      if (!matched) {
        for (let i = turns.length - 1; i >= 0; i--) {
          if (turns[i].speaker === agentId) {
            const existing = artifactsByTurn.get(i) || [];
            existing.push(artifact);
            artifactsByTurn.set(i, existing);
            break;
          }
        }
      }
    }
  }

  // Compute cost by agent (estimate from turn token counts)
  const costByAgent: Record<string, string> = {};
  for (const turn of turns) {
    const tokens = Math.ceil(turn.content.length / 4);
    const cost = tokens * 0.000001; // rough estimate
    costByAgent[turn.speaker] = (
      parseFloat(costByAgent[turn.speaker] || "0") + cost
    ).toFixed(6);
  }

  const selectedTurnDetail = selectedTurn !== null
    ? turnDetailMap.get(selectedTurn + 1) || null
    : null;

  const configSnapshot = conv.trigger_details || null;

  return (
    <div className="flex gap-6 min-h-0">
      {/* Main Content */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Breadcrumb */}
        <div className="text-xs text-foreground/40">
          <Link href="/admin/simulations" className="hover:text-foreground/60">
            Simulations
          </Link>
          {conv.simulation_id && (
            <>
              {" / "}
              <Link
                href={`/admin/simulations/${conv.simulation_id}`}
                className="hover:text-foreground/60"
              >
                Simulation
              </Link>
            </>
          )}
          {" / "}
          <span className="text-foreground/60">Conversation</span>
        </div>

        {/* Header */}
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <h1 className="font-pixel text-lg text-foreground mb-1">
                Conversation
              </h1>
              <div className="text-[10px] font-mono text-foreground/30">
                {conv.id}
              </div>
            </div>
            {conv.simulation_id && (
              <Link
                href={`/admin/simulations/${conv.simulation_id}`}
                className="text-xs text-indigo-400 hover:text-indigo-300"
              >
                View Simulation →
              </Link>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <div className="text-foreground/40 mb-0.5">Trigger</div>
              <div className="text-foreground/70">{conv.trigger_type}</div>
            </div>
            <div>
              <div className="text-foreground/40 mb-0.5">Duration</div>
              <div className="text-foreground/70">
                {formatDuration(conv.started_at, conv.ended_at)}
              </div>
            </div>
            <div>
              <div className="text-foreground/40 mb-0.5">Turns</div>
              <div className="text-foreground/70">{conv.turn_count}</div>
            </div>
            <div>
              <div className="text-foreground/40 mb-0.5">Tokens</div>
              <div className="text-foreground/70">
                {conv.total_tokens != null ? conv.total_tokens.toLocaleString() : "N/A"}
              </div>
            </div>
            <div>
              <div className="text-foreground/40 mb-0.5">Cost</div>
              <div className="text-foreground/70">{conv.total_cost != null ? `$${conv.total_cost}` : "N/A"}</div>
            </div>
            <div>
              <div className="text-foreground/40 mb-0.5">Energy</div>
              <div className="text-foreground/70">
                {conv.initial_energy.toFixed(2)} →{" "}
                {conv.final_energy?.toFixed(2) ?? "—"}
              </div>
            </div>
            {conv.location && (
              <div>
                <div className="text-foreground/40 mb-0.5">Location</div>
                <div className="text-foreground/70">{conv.location}</div>
              </div>
            )}
            {conv.closed_by && (
              <div>
                <div className="text-foreground/40 mb-0.5">Closed by</div>
                <div className="text-foreground/70">{conv.closed_by}</div>
              </div>
            )}
          </div>

          {/* Participants */}
          <div className="mt-3">
            <div className="text-xs text-foreground/40 mb-1">Participants</div>
            <div className="flex flex-wrap gap-1.5">
              {conv.participating_agents.map((agent) => (
                <Link
                  key={agent}
                  href={`/admin/agents/${agent}`}
                  className={`rounded px-2 py-0.5 text-xs font-medium ${
                    AGENT_TEXT_COLORS[agent] || "text-foreground/60"
                  } bg-surface-light border border-border hover:border-foreground/20 transition-colors`}
                >
                  {agent}
                </Link>
              ))}
            </div>
          </div>

          {/* Topics */}
          {conv.topics_discussed && conv.topics_discussed.length > 0 && (
            <div className="mt-3">
              <div className="text-xs text-foreground/40 mb-1">Topics</div>
              <div className="flex flex-wrap gap-1.5">
                {conv.topics_discussed.map((topic, i) => (
                  <span
                    key={i}
                    className="rounded bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-400"
                  >
                    {topic}
                  </span>
                ))}
              </div>
            </div>
          )}

          {conv.started_at && (
            <div className="mt-3 text-[10px] text-foreground/30">
              {new Date(conv.started_at).toLocaleString()}
            </div>
          )}
        </div>

        {/* Transcript */}
        {turns.length > 0 ? (
          <div className="space-y-3">
            {turns.map((turn, i) => (
              <TranscriptTurn
                key={i}
                turn={turn}
                turnIndex={i}
                turnDetail={turnDetailMap.get(i + 1) || null}
                overseerFlags={flagsByTurn.get(i) || []}
                interrupts={interruptsByTurn.get(i) || []}
                toolInvocations={(artifactsByTurn.get(i) || []).map((a) => ({
                  tool_name: a.tool_name,
                  tool_input: a.tool_input,
                  tool_output: a.tool_output,
                  status: a.status,
                  artifact_id: a.id,
                }))}
                convStartedAt={conv.started_at}
                isSelected={selectedTurn === i}
                onSelect={() =>
                  setSelectedTurn(selectedTurn === i ? null : i)
                }
              />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-border bg-surface p-6 text-center text-sm text-foreground/40">
            No transcript available for this conversation.
          </div>
        )}
      </div>

      {/* Sidebar */}
      <div className="w-80 shrink-0 space-y-4 hidden lg:block">
        <div className="sticky top-4 space-y-4">
          {/* Selection Panel */}
          <SelectionPanel
            turnDetail={selectedTurnDetail}
            turnIndex={selectedTurn ?? 0}
            configSnapshot={configSnapshot}
            costByAgent={costByAgent}
          />

          {/* Energy Graph */}
          <EnergyGraph
            energyHistory={conv.energy_history}
            initialEnergy={conv.initial_energy}
            finalEnergy={conv.final_energy}
            turnCount={conv.turn_count}
          />

          {/* Metadata */}
          <div className="rounded-lg border border-border bg-surface p-3">
            <h3 className="text-xs font-medium text-foreground/60 mb-2">
              Metadata
            </h3>
            <div className="space-y-1.5 text-xs text-foreground/40">
              <div className="flex justify-between">
                <span>Overseer flags</span>
                <span
                  className={
                    overseerFlags.length > 0
                      ? "text-red-400"
                      : "text-foreground/30"
                  }
                >
                  {overseerFlags.length}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Interrupts</span>
                <span
                  className={
                    interrupts.length > 0
                      ? "text-orange-400"
                      : "text-foreground/30"
                  }
                >
                  {interrupts.length}
                </span>
              </div>
              <div className="flex justify-between">
                <span>Selection logs</span>
                <span className="text-foreground/30">
                  {turnDetails.length}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

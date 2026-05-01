"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { ConversationDetail } from "@/types";
import {
  getConversation,
  getConversationTurns,
  getConversationManagementFlags,
  getConversationInterrupts,
} from "@/lib/api";
import type { TurnDetail } from "@/lib/api";
import { getAllAgents } from "@/lib/agent-data";

// ---------------------------------------------------------------------------
// Agent color maps (Tailwind classes keyed by agent id)
// ---------------------------------------------------------------------------

const AGENT_BORDER_COLORS: Record<string, string> = {
  vera: "border-l-fuchsia-500 bg-fuchsia-500/5",
  rex: "border-l-green-500 bg-green-500/5",
  aurora: "border-l-cyan-500 bg-cyan-500/5",
  pixel: "border-l-yellow-500 bg-yellow-500/5",
  fork: "border-l-red-500 bg-red-500/5",
  sentinel: "border-l-blue-500 bg-blue-500/5",
  grok: "border-l-orange-500 bg-orange-500/5",
  management: "border-l-white/50 bg-white/5",
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
  management: "text-white/70",
  alpha: "text-gray-400",
};

const AGENT_DOT_COLORS: Record<string, string> = {
  vera: "bg-fuchsia-400",
  rex: "bg-green-400",
  aurora: "bg-cyan-400",
  pixel: "bg-yellow-400",
  fork: "bg-red-400",
  sentinel: "bg-blue-400",
  grok: "bg-orange-400",
  management: "bg-white/70",
  alpha: "bg-gray-400",
};

// ---------------------------------------------------------------------------
// Parsed transcript types & helpers
// ---------------------------------------------------------------------------

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
        turns.push(buildParsedTurn(currentSpeaker, currentLines.join("\n")));
      }
      currentSpeaker = match[1];
      currentLines = [match[2]];
    } else if (currentSpeaker) {
      currentLines.push(line);
    }
  }
  if (currentSpeaker && currentLines.length > 0) {
    turns.push(buildParsedTurn(currentSpeaker, currentLines.join("\n")));
  }
  return turns;
}

function buildParsedTurn(speaker: string, raw: string): ParsedTurn {
  const actions: string[] = [];
  const content = raw.replace(
    /\[action\]([\s\S]*?)\[\/action\]/g,
    (_, action: string) => {
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

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatDuration(
  startedAt: string | null,
  endedAt: string | null,
): string {
  if (!startedAt || !endedAt) return "--";
  const diff = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (diff < 0) return "--";
  const mins = Math.floor(diff / 60000);
  const secs = Math.floor((diff % 60000) / 1000);
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

function formatRelativeTime(
  timestamp: string | null,
  startedAt: string | null,
): string {
  if (!timestamp || !startedAt) return "";
  const diff = new Date(timestamp).getTime() - new Date(startedAt).getTime();
  if (diff < 0) return "0:00";
  const mins = Math.floor(diff / 60000);
  const secs = Math.floor((diff % 60000) / 1000);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Management flag severity styles
// ---------------------------------------------------------------------------

const SEVERITY_STYLES: Record<number, string> = {
  1: "border-yellow-500/30 bg-yellow-500/5 text-yellow-400",
  2: "border-yellow-500/50 bg-yellow-500/10 text-yellow-400",
  3: "border-orange-500/50 bg-orange-500/10 text-orange-400",
  4: "border-red-500/50 bg-red-500/10 text-red-400",
  5: "border-red-500/70 bg-red-500/15 text-red-400",
};

// ---------------------------------------------------------------------------
// Inline energy graph (CSS bars, no chart library)
// ---------------------------------------------------------------------------

interface EnergyDataPoint {
  turn: number;
  energy: number;
}

function buildEnergyData(
  energyHistory: Record<string, unknown>[],
  initialEnergy: number,
  finalEnergy: number | null,
  turnCount: number,
): EnergyDataPoint[] {
  const data: EnergyDataPoint[] = [{ turn: 0, energy: initialEnergy }];

  for (const entry of energyHistory) {
    const turnNum =
      typeof entry.turn_number === "number"
        ? entry.turn_number
        : typeof entry.turn === "number"
          ? entry.turn
          : data.length;

    const changes = entry.changes as Record<string, unknown> | undefined;
    let energy: number | undefined;

    if (typeof entry.energy === "number") {
      energy = entry.energy;
    } else if (changes && typeof (changes as Record<string, number>).new_energy === "number") {
      energy = (changes as Record<string, number>).new_energy;
    } else if (typeof entry.conversation_energy === "number") {
      energy = entry.conversation_energy as number;
    }

    if (energy !== undefined) {
      data.push({ turn: turnNum, energy });
    }
  }

  if (finalEnergy !== null && turnCount > 0) {
    const lastTurn = data[data.length - 1]?.turn ?? 0;
    if (lastTurn < turnCount) {
      data.push({ turn: turnCount, energy: finalEnergy });
    }
  }

  return data;
}

function EnergyGraph({
  energyHistory,
  initialEnergy,
  finalEnergy,
  turnCount,
}: {
  energyHistory: Record<string, unknown>[];
  initialEnergy: number;
  finalEnergy: number | null;
  turnCount: number;
}) {
  const data = buildEnergyData(energyHistory, initialEnergy, finalEnergy, turnCount);

  if (data.length < 2) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4 text-xs text-foreground/40 text-center">
        No energy data available
      </div>
    );
  }

  const maxEnergy = Math.max(...data.map((d) => d.energy), 1);

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-medium text-foreground/60">Energy Level</h3>
        <div className="text-[10px] text-foreground/40">
          {initialEnergy.toFixed(2)} --&gt;{" "}
          {(finalEnergy ?? data[data.length - 1]?.energy ?? 0).toFixed(2)}
        </div>
      </div>
      <div className="flex items-end gap-px h-24" aria-label="Energy over turns">
        {data.map((point, i) => {
          const heightPct = (point.energy / maxEnergy) * 100;
          return (
            <div
              key={i}
              className="flex-1 min-w-[3px] group relative"
              style={{ height: "100%" }}
            >
              <div
                className="absolute bottom-0 left-0 right-0 rounded-t-sm bg-indigo-500/80 transition-all group-hover:bg-indigo-400"
                style={{ height: `${heightPct}%` }}
              />
              <div className="absolute -top-6 left-1/2 -translate-x-1/2 hidden group-hover:block whitespace-nowrap bg-surface-light border border-border rounded px-1.5 py-0.5 text-[9px] text-foreground/60 z-10">
                T{point.turn}: {point.energy.toFixed(3)}
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-1 text-[9px] text-foreground/30">
        <span>T0</span>
        <span>T{data[data.length - 1]?.turn ?? turnCount}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ConversationDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const [conv, setConv] = useState<ConversationDetail | null>(null);
  const [turnDetails, setTurnDetails] = useState<TurnDetail[]>([]);
  const [managementFlags, setManagementFlags] = useState<Record<string, unknown>[]>([]);
  const [interrupts, setInterrupts] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const agentMap = Object.fromEntries(getAllAgents().map((a) => [a.id, a]));

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getConversation(id),
      getConversationTurns(id).catch(() => []),
      getConversationManagementFlags(id).catch(() => []),
      getConversationInterrupts(id).catch(() => []),
    ])
      .then(([convData, turns, flags, ints]) => {
        setConv(convData);
        setTurnDetails(turns);
        setManagementFlags(flags);
        setInterrupts(ints);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load conversation"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  // ------- Loading / Error states -------

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-12">
        <p className="text-foreground/50 text-sm">Loading conversation...</p>
      </div>
    );
  }

  if (error || !conv) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-12">
        <h1 className="font-pixel text-xl text-neon-cyan mb-4">CONVERSATION</h1>
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
          {error || "Conversation not found"}
        </div>
      </div>
    );
  }

  // ------- Parse transcript -------

  const turns = conv.transcript ? parseTranscript(conv.transcript) : [];

  // Build lookup map for turn-level data
  const turnDetailMap = new Map<number, TurnDetail>();
  for (const td of turnDetails) {
    turnDetailMap.set(td.turn_number, td);
  }

  // Group management flags by matching each flag to the next unmatched turn
  // by the same agent (flags are ordered by created_at from the API).
  const flagsByTurn = new Map<number, Record<string, unknown>[]>();
  {
    const usedTurns = new Map<string, number>();
    for (const flag of managementFlags) {
      const agentId = String(flag.agent_id ?? "");
      const startIdx = usedTurns.get(agentId) ?? 0;
      let matched = false;
      for (let i = startIdx; i < turns.length; i++) {
        if (turns[i].speaker === agentId) {
          const existing = flagsByTurn.get(i) || [];
          existing.push(flag);
          flagsByTurn.set(i, existing);
          usedTurns.set(agentId, i + 1);
          matched = true;
          break;
        }
      }
      if (!matched) {
        for (let i = turns.length - 1; i >= 0; i--) {
          if (turns[i].speaker === agentId) {
            const existing = flagsByTurn.get(i) || [];
            existing.push(flag);
            flagsByTurn.set(i, existing);
            break;
          }
        }
      }
    }
  }

  // Group interrupts by turn
  const interruptsByTurn = new Map<number, Record<string, unknown>[]>();
  {
    const usedTurns = new Map<string, number>();
    for (const interrupt of interrupts) {
      const agentId = String(interrupt.attempting_agent_id ?? "");
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

  // ------- Derived values -------

  const shortId = conv.id.slice(0, 8);
  const totalFlagsCount = managementFlags.length;
  const totalInterruptsCount = interrupts.length;

  return (
    <div className="mx-auto max-w-7xl px-4 py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-foreground/40 mb-4" aria-label="Breadcrumb">
        <Link href="/conversations" className="hover:text-foreground/60 transition-colors">
          Conversations
        </Link>
        {" / "}
        <span className="text-foreground/60">{shortId}</span>
      </nav>

      {/* Header Card */}
      <div className="rounded-lg border border-border bg-surface p-4 mb-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <h1 className="font-pixel text-lg text-neon-cyan mb-1">
              Conversation {shortId}
            </h1>
            <div className="text-[10px] font-mono text-foreground/30">{conv.id}</div>
          </div>
          {conv.simulation_id && (
            <Link
              href={`/simulations/${conv.simulation_id}`}
              className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors shrink-0"
            >
              View Simulation &rarr;
            </Link>
          )}
        </div>

        {/* Info grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div>
            <div className="text-foreground/40 mb-0.5">Trigger</div>
            <div className="font-mono text-foreground/70">{conv.trigger_type}</div>
          </div>
          <div>
            <div className="text-foreground/40 mb-0.5">Duration</div>
            <div className="font-mono text-foreground/70">
              {formatDuration(conv.started_at, conv.ended_at)}
            </div>
          </div>
          <div>
            <div className="text-foreground/40 mb-0.5">Turns</div>
            <div className="font-mono text-foreground/70">{conv.turn_count}</div>
          </div>
          <div>
            <div className="text-foreground/40 mb-0.5">Tokens</div>
            <div className="font-mono text-foreground/70">
              {conv.total_tokens.toLocaleString()}
            </div>
          </div>
          <div>
            <div className="text-foreground/40 mb-0.5">Cost</div>
            <div className="font-mono text-foreground/70">
              ${Number(conv.total_cost).toFixed(4)}
            </div>
          </div>
          <div>
            <div className="text-foreground/40 mb-0.5">Energy</div>
            <div className="font-mono text-foreground/70">
              {conv.initial_energy.toFixed(2)} &rarr;{" "}
              {conv.final_energy?.toFixed(2) ?? "--"}
            </div>
          </div>
          {conv.location && (
            <div>
              <div className="text-foreground/40 mb-0.5">Location</div>
              <div className="font-mono text-foreground/70">{conv.location}</div>
            </div>
          )}
          {conv.closed_by && (
            <div>
              <div className="text-foreground/40 mb-0.5">Closed by</div>
              <div className="font-mono text-foreground/70">
                <Link
                  href={`/agents/${conv.closed_by}`}
                  className={`hover:underline ${AGENT_TEXT_COLORS[conv.closed_by] ?? "text-foreground/70"}`}
                >
                  {agentMap[conv.closed_by]?.name ?? conv.closed_by}
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* Participants */}
        <div className="mt-3">
          <div className="text-xs text-foreground/40 mb-1">Participants</div>
          <div className="flex flex-wrap gap-1.5">
            {conv.participating_agents.map((agentId) => (
              <Link
                key={agentId}
                href={`/agents/${agentId}`}
                className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium ${
                  AGENT_TEXT_COLORS[agentId] || "text-foreground/60"
                } bg-surface-light border border-border hover:border-foreground/20 transition-colors`}
              >
                <span
                  className={`inline-block w-2 h-2 rounded-full ${
                    AGENT_DOT_COLORS[agentId] || "bg-foreground/40"
                  }`}
                />
                {agentMap[agentId]?.name ?? agentId}
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

      {/* Two-column layout: Transcript + Sidebar */}
      <div className="flex gap-6 min-h-0">
        {/* Left: Transcript */}
        <div className="flex-1 min-w-0 space-y-3">
          <h2 className="font-pixel text-sm text-neon-cyan mb-2">TRANSCRIPT</h2>

          {turns.length > 0 ? (
            turns.map((turn, i) => {
              const td = turnDetailMap.get(i + 1) ?? null;
              const flags = flagsByTurn.get(i) ?? [];
              const turnInterrupts = interruptsByTurn.get(i) ?? [];
              const relTime = formatRelativeTime(td?.timestamp ?? null, conv.started_at);
              const tokenEstimate = Math.ceil(turn.content.length / 4);

              return (
                <div
                  key={i}
                  className={`rounded-lg border-l-4 p-4 ${
                    AGENT_BORDER_COLORS[turn.speaker] || "border-l-foreground/20 bg-surface"
                  }`}
                >
                  {/* Turn header */}
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    <Link
                      href={`/agents/${turn.speaker}`}
                      className={`text-xs font-bold uppercase hover:underline ${
                        AGENT_TEXT_COLORS[turn.speaker] || "text-foreground/60"
                      }`}
                    >
                      {agentMap[turn.speaker]?.name ?? turn.speaker}
                    </Link>
                    <span className="text-[10px] text-foreground/30">
                      Turn {i + 1}
                    </span>
                    {relTime && (
                      <span className="text-[10px] text-foreground/30">{relTime}</span>
                    )}
                    <span className="text-[10px] text-foreground/25">
                      ~{tokenEstimate} tok
                    </span>
                    {td?.was_interrupt && (
                      <span className="text-[10px] font-medium text-orange-400 bg-orange-400/10 px-1.5 py-0.5 rounded">
                        INTERRUPT
                      </span>
                    )}
                    {flags.length > 0 && (
                      <span className="text-[10px] font-medium text-red-400 bg-red-400/10 px-1.5 py-0.5 rounded">
                        FLAGGED
                      </span>
                    )}
                  </div>

                  {/* Actions */}
                  {turn.actions.length > 0 && (
                    <div className="text-xs text-foreground/40 italic mb-1">
                      {turn.actions.map((a, j) => (
                        <span key={j}>*{a}* </span>
                      ))}
                    </div>
                  )}

                  {/* Dialogue */}
                  <div className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
                    {turn.dialogue}
                  </div>

                  {/* Management Flags */}
                  {flags.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {flags.map((flag, fi) => {
                        const severity = typeof flag.severity === "number" ? flag.severity : 3;
                        return (
                          <div
                            key={fi}
                            className={`rounded border px-3 py-2 text-xs ${
                              SEVERITY_STYLES[severity] || SEVERITY_STYLES[3]
                            }`}
                          >
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <span className="font-bold">
                                Management Flag (Severity {severity}/5)
                              </span>
                              {flag.action_would_take != null && (
                                <span className="opacity-70">
                                  Action: {String(flag.action_would_take)}
                                </span>
                              )}
                            </div>
                            {flag.reason != null && (
                              <div className="opacity-80">{String(flag.reason)}</div>
                            )}
                            {Array.isArray(flag.flagged_keywords) &&
                              flag.flagged_keywords.length > 0 && (
                                <div className="mt-1 opacity-60">
                                  Keywords: {flag.flagged_keywords.join(", ")}
                                </div>
                              )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Interrupt Markers */}
                  {turnInterrupts.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {turnInterrupts.map((interrupt, ii) => (
                        <div
                          key={ii}
                          className="rounded border border-orange-500/30 bg-orange-500/5 px-3 py-2 text-xs text-orange-400"
                        >
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-bold">Interrupt</span>
                            <span className="opacity-70">
                              {String(interrupt.attempting_agent_id ?? "")} interrupted{" "}
                              {String(interrupt.would_have_spoken_id ?? "")}
                            </span>
                            {typeof interrupt.interrupt_score === "number" && (
                              <span className="opacity-50 ml-auto">
                                Score: {interrupt.interrupt_score.toFixed(2)}
                                {typeof interrupt.threshold_at_time === "number" &&
                                  ` / Threshold: ${interrupt.threshold_at_time.toFixed(2)}`}
                              </span>
                            )}
                          </div>
                          {interrupt.reason != null && (
                            <div className="mt-1 opacity-70">{String(interrupt.reason)}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          ) : (
            <div className="rounded-lg border border-border bg-surface p-6 text-center text-sm text-foreground/40">
              No transcript available for this conversation.
            </div>
          )}
        </div>

        {/* Right Sidebar (lg+) */}
        <aside className="w-80 shrink-0 space-y-4 hidden lg:block">
          <div className="sticky top-4 space-y-4">
            {/* Energy Graph */}
            <EnergyGraph
              energyHistory={conv.energy_history}
              initialEnergy={conv.initial_energy}
              finalEnergy={conv.final_energy}
              turnCount={conv.turn_count}
            />

            {/* Metadata */}
            <div className="rounded-lg border border-border bg-surface p-3">
              <h3 className="text-xs font-medium text-foreground/60 mb-2">Metadata</h3>
              <div className="space-y-1.5 text-xs text-foreground/40">
                <div className="flex justify-between">
                  <span>Total turns</span>
                  <span className="font-mono text-foreground/60">{conv.turn_count}</span>
                </div>
                <div className="flex justify-between">
                  <span>Total tokens</span>
                  <span className="font-mono text-foreground/60">
                    {conv.total_tokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Management flags</span>
                  <span
                    className={`font-mono ${
                      totalFlagsCount > 0 ? "text-red-400" : "text-foreground/30"
                    }`}
                  >
                    {totalFlagsCount}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Interrupts</span>
                  <span
                    className={`font-mono ${
                      totalInterruptsCount > 0 ? "text-orange-400" : "text-foreground/30"
                    }`}
                  >
                    {totalInterruptsCount}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>Selection logs</span>
                  <span className="font-mono text-foreground/30">{turnDetails.length}</span>
                </div>
              </div>
            </div>

            {/* Participants quick list */}
            <div className="rounded-lg border border-border bg-surface p-3">
              <h3 className="text-xs font-medium text-foreground/60 mb-2">Participants</h3>
              <div className="space-y-1.5">
                {conv.participating_agents.map((agentId) => {
                  const agent = agentMap[agentId];
                  const turnCount = turns.filter((t) => t.speaker === agentId).length;
                  return (
                    <Link
                      key={agentId}
                      href={`/agents/${agentId}`}
                      className="flex items-center justify-between text-xs hover:bg-surface-light rounded px-1 py-0.5 transition-colors"
                    >
                      <span className="flex items-center gap-1.5">
                        <span
                          className={`inline-block w-2 h-2 rounded-full ${
                            AGENT_DOT_COLORS[agentId] || "bg-foreground/40"
                          }`}
                        />
                        <span className={AGENT_TEXT_COLORS[agentId] || "text-foreground/60"}>
                          {agent?.name ?? agentId}
                        </span>
                      </span>
                      <span className="font-mono text-foreground/30">
                        {turnCount} turn{turnCount !== 1 ? "s" : ""}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

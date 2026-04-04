"use client";

import { useState } from "react";
import type {
  InterruptEvent,
  OverseerFlag,
  TurnDetail,
} from "@/types/admin";

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

interface ToolInvocation {
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output: Record<string, unknown> | string | null;
  status: string;
  execution_time?: number;
  artifact_id?: string;
}

interface TranscriptTurnProps {
  turn: ParsedTurn;
  turnIndex: number;
  turnDetail: TurnDetail | null;
  overseerFlags: OverseerFlag[];
  interrupts: InterruptEvent[];
  toolInvocations: ToolInvocation[];
  convStartedAt: string | null;
  isSelected: boolean;
  onSelect: () => void;
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

const SEVERITY_STYLES: Record<number, string> = {
  1: "border-yellow-500/30 bg-yellow-500/5 text-yellow-400",
  2: "border-yellow-500/50 bg-yellow-500/10 text-yellow-400",
  3: "border-orange-500/50 bg-orange-500/10 text-orange-400",
  4: "border-red-500/50 bg-red-500/10 text-red-400",
  5: "border-red-500/70 bg-red-500/15 text-red-400",
};

export default function TranscriptTurn({
  turn,
  turnIndex,
  turnDetail,
  overseerFlags,
  interrupts,
  toolInvocations,
  convStartedAt,
  isSelected,
  onSelect,
}: TranscriptTurnProps) {
  const [expandedTools, setExpandedTools] = useState<Set<number>>(new Set());

  const toggleTool = (idx: number) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const relTime = formatRelativeTime(
    turnDetail?.timestamp ?? null,
    convStartedAt,
  );
  const tokenEstimate = Math.ceil(turn.content.length / 4);

  return (
    <div
      className={`rounded-lg border-l-4 p-4 cursor-pointer transition-all ${
        AGENT_COLORS[turn.speaker] || "border-l-foreground/20 bg-surface"
      } ${isSelected ? "ring-1 ring-foreground/20" : ""}`}
      onClick={onSelect}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={`text-xs font-bold uppercase ${
            AGENT_TEXT_COLORS[turn.speaker] || "text-foreground/60"
          }`}
        >
          {turn.speaker}
        </span>
        <span className="text-[10px] text-foreground/30">
          Turn {turnIndex + 1}
        </span>
        {relTime && (
          <span className="text-[10px] text-foreground/30">{relTime}</span>
        )}
        <span className="text-[10px] text-foreground/25">
          ~{tokenEstimate} tokens
        </span>
        {turnDetail?.was_interrupt && (
          <span className="text-[10px] font-medium text-orange-400 bg-orange-400/10 px-1.5 py-0.5 rounded">
            INTERRUPT
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

      {/* Tool Invocations */}
      {toolInvocations.length > 0 && (
        <div className="mt-2 space-y-1">
          {toolInvocations.map((tool, idx) => (
            <div
              key={idx}
              className="rounded border border-border bg-surface-light text-xs"
            >
              <button
                className="flex items-center gap-2 w-full px-3 py-1.5 text-left hover:bg-foreground/5"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleTool(idx);
                }}
              >
                <span className="text-foreground/40">
                  {expandedTools.has(idx) ? "▾" : "▸"}
                </span>
                <span className="font-medium text-foreground/70">
                  🔧 {tool.tool_name}
                </span>
                <span className="text-foreground/30">{tool.status}</span>
                {tool.execution_time != null && (
                  <span className="text-foreground/25 ml-auto">
                    {tool.execution_time}ms
                  </span>
                )}
              </button>
              {expandedTools.has(idx) && (
                <div className="px-3 py-2 border-t border-border space-y-2">
                  <div>
                    <div className="text-foreground/40 mb-0.5">Input:</div>
                    <pre className="text-foreground/60 overflow-x-auto max-h-32 overflow-y-auto">
                      {JSON.stringify(tool.tool_input, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="text-foreground/40 mb-0.5">Output:</div>
                    <pre className="text-foreground/60 overflow-x-auto max-h-32 overflow-y-auto">
                      {typeof tool.tool_output === "string"
                        ? tool.tool_output
                        : JSON.stringify(tool.tool_output, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Overseer Flags */}
      {overseerFlags.length > 0 && (
        <div className="mt-2 space-y-1">
          {overseerFlags.map((flag) => (
            <div
              key={flag.id}
              className={`rounded border px-3 py-2 text-xs ${
                SEVERITY_STYLES[flag.severity] || SEVERITY_STYLES[3]
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="font-bold">
                  ⚠ Overseer Flag (Severity {flag.severity}/5)
                </span>
                <span className="opacity-70">
                  Action: {flag.action_would_take}
                </span>
              </div>
              <div className="opacity-80">{flag.reason}</div>
              {flag.flagged_keywords.length > 0 && (
                <div className="mt-1 opacity-60">
                  Keywords: {flag.flagged_keywords.join(", ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Interrupt Markers */}
      {interrupts.length > 0 && (
        <div className="mt-2 space-y-1">
          {interrupts.map((interrupt) => (
            <div
              key={interrupt.id}
              className="rounded border border-orange-500/30 bg-orange-500/5 px-3 py-2 text-xs text-orange-400"
            >
              <div className="flex items-center gap-2">
                <span className="font-bold">⚡ Interrupt</span>
                <span className="opacity-70">
                  {interrupt.attempting_agent_id} interrupted{" "}
                  {interrupt.would_have_spoken_id}
                </span>
                <span className="opacity-50 ml-auto">
                  Score: {interrupt.interrupt_score.toFixed(2)} / Threshold:{" "}
                  {interrupt.threshold_at_time.toFixed(2)}
                </span>
              </div>
              {interrupt.reason && (
                <div className="mt-1 opacity-70">{interrupt.reason}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

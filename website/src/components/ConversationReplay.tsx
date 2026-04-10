"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversationDetail, SelectionLogEntry } from "@/types";
import { getAgentData } from "@/lib/agent-data";
import PlaybackControls from "@/components/PlaybackControls";
import SpeakerSelectionPanel from "@/components/SpeakerSelectionPanel";

interface ConversationReplayProps {
  conversation: ConversationDetail;
  selections: SelectionLogEntry[];
  initialTurn?: number;
}

export default function ConversationReplay({
  conversation,
  selections,
  initialTurn = 1,
}: ConversationReplayProps) {
  const [currentTurn, setCurrentTurn] = useState(initialTurn);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [openPanels, setOpenPanels] = useState<Set<number>>(new Set());
  const [typingEnabled, setTypingEnabled] = useState(false);
  const turnRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const totalTurns = selections.length || conversation.turn_count;

  // Auto-advance playback
  useEffect(() => {
    if (isPlaying && totalTurns > 0) {
      intervalRef.current = setInterval(() => {
        setCurrentTurn((prev) => {
          if (prev >= totalTurns) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 2000 / speed);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, speed, totalTurns]);

  // Update URL hash on turn change
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `#turn-${currentTurn}`);
    }
  }, [currentTurn]);

  // Scroll to current turn
  useEffect(() => {
    const el = turnRefs.current.get(currentTurn);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [currentTurn]);

  const setTurnRef = useCallback(
    (turnNumber: number) => (el: HTMLDivElement | null) => {
      if (el) turnRefs.current.set(turnNumber, el);
      else turnRefs.current.delete(turnNumber);
    },
    [],
  );

  function togglePanel(turnNumber: number) {
    setOpenPanels((prev) => {
      const next = new Set(prev);
      if (next.has(turnNumber)) next.delete(turnNumber);
      else next.add(turnNumber);
      return next;
    });
  }

  // Build energy data for the graph
  const energyData = selections.map((s) => ({
    turn: s.turn_number,
    energy: s.conversation_energy ?? 0,
  }));

  return (
    <div className="space-y-4">
      {/* Header info */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-foreground/50">
        <span>Trigger: {conversation.trigger_type}</span>
        {conversation.location && <span>Location: {conversation.location}</span>}
        <span>Turns: {conversation.turn_count}</span>
        {conversation.started_at && (
          <time>{new Date(conversation.started_at).toLocaleString()}</time>
        )}
        <label className="flex items-center gap-1 ml-auto cursor-pointer">
          <input
            type="checkbox"
            checked={typingEnabled}
            onChange={(e) => setTypingEnabled(e.target.checked)}
            className="accent-neon-cyan"
          />
          <span>Typing animation</span>
        </label>
      </div>

      {/* Participants */}
      <div className="flex flex-wrap gap-2">
        {conversation.participating_agents.map((agentId) => {
          const agent = getAgentData(agentId);
          return (
            <span
              key={agentId}
              className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs"
              style={{
                backgroundColor: agent ? `${agent.color}15` : "rgba(255,255,255,0.05)",
                color: agent?.color || "inherit",
              }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: agent?.color || "#888" }}
              />
              {agent?.name || agentId}
            </span>
          );
        })}
      </div>

      {/* Energy graph (simple bar visualization) */}
      {energyData.length > 0 && (
        <div className="rounded border border-border bg-surface p-3">
          <div className="text-xs text-foreground/40 mb-2">Conversation Energy</div>
          <div className="flex items-end gap-0.5 h-12">
            {energyData.map((d) => (
              <div
                key={d.turn}
                className={`flex-1 rounded-t transition-all ${
                  d.turn <= currentTurn ? "bg-neon-cyan/60" : "bg-foreground/10"
                }`}
                style={{ height: `${Math.max(d.energy * 100, 2)}%` }}
                title={`Turn ${d.turn}: ${d.energy.toFixed(2)}`}
              />
            ))}
          </div>
        </div>
      )}

      {/* Playback controls */}
      {totalTurns > 0 && (
        <PlaybackControls
          currentTurn={currentTurn}
          totalTurns={totalTurns}
          isPlaying={isPlaying}
          speed={speed}
          onPlayPause={() => setIsPlaying((p) => !p)}
          onSpeedChange={setSpeed}
          onTurnChange={(t) => {
            setCurrentTurn(t);
            setIsPlaying(false);
          }}
        />
      )}

      {/* Turn-by-turn display */}
      <div className="space-y-3">
        {selections.length === 0 && (
          <p className="text-foreground/50 text-sm">
            No selection data available for this conversation.
          </p>
        )}
        {selections.map((sel) => {
          const agent = getAgentData(sel.selected_agent_id);
          const isCurrent = sel.turn_number === currentTurn;
          const isPast = sel.turn_number <= currentTurn;

          return (
            <div
              key={sel.turn_number}
              ref={setTurnRef(sel.turn_number)}
              id={`turn-${sel.turn_number}`}
              className={`rounded border p-3 transition-all ${
                isCurrent
                  ? "border-neon-cyan bg-neon-cyan/5"
                  : isPast
                    ? "border-border bg-surface"
                    : "border-border/50 bg-surface/50 opacity-40"
              }`}
            >
              {/* Agent header */}
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="h-3 w-3 rounded-full"
                  style={{ backgroundColor: agent?.color || "#888" }}
                />
                <span
                  className="text-sm font-medium"
                  style={{ color: agent?.color }}
                >
                  {agent?.name || sel.selected_agent_id}
                </span>
                <span className="text-xs text-foreground/30">
                  Turn {sel.turn_number}
                </span>
                {sel.was_interrupt && (
                  <span className="text-xs text-neon-magenta">INTERRUPT</span>
                )}
              </div>

              {/* Selection panel */}
              <SpeakerSelectionPanel
                selection={sel}
                isOpen={openPanels.has(sel.turn_number)}
                onToggle={() => togglePanel(sel.turn_number)}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

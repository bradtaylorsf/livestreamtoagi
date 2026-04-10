"use client";

import type { SelectionLogEntry } from "@/types";
import { getAgentData } from "@/lib/agent-data";

const WEIGHT_LABELS: Record<string, { label: string; weight: number }> = {
  time_since_spoke: { label: "Time Since Spoke", weight: 0.3 },
  topic_relevance: { label: "Topic Relevance", weight: 0.3 },
  chattiness: { label: "Chattiness", weight: 0.15 },
  adjacency_fit: { label: "Adjacency Fit", weight: 0.15 },
  random_jitter: { label: "Random Jitter", weight: 0.1 },
};

interface SpeakerSelectionPanelProps {
  selection: SelectionLogEntry;
  isOpen: boolean;
  onToggle: () => void;
}

export default function SpeakerSelectionPanel({
  selection,
  isOpen,
  onToggle,
}: SpeakerSelectionPanelProps) {
  const selectedAgent = getAgentData(selection.selected_agent_id);

  return (
    <div className="rounded border border-border bg-surface-light">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-3 py-2 text-xs text-foreground/60 hover:text-foreground transition-colors md:py-2 py-1.5"
        aria-label="Toggle speaker selection details"
      >
        <span>
          Speaker selection:{" "}
          <span style={{ color: selectedAgent?.color }}>
            {selectedAgent?.name || selection.selected_agent_id}
          </span>
          {selection.was_interrupt && (
            <span className="ml-1 text-neon-magenta">(interrupt)</span>
          )}
          {selection.detected_topic && (
            <span className="ml-2 text-foreground/40">
              Topic: {selection.detected_topic}
            </span>
          )}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="currentColor"
          className={`transition-transform ${isOpen ? "rotate-180" : ""}`}
        >
          <path d="M2 4l4 4 4-4H2z" />
        </svg>
      </button>

      {isOpen && (
        <div className="border-t border-border px-3 py-2">
          {/* Weight breakdown header */}
          <div className="grid grid-cols-6 gap-1 text-[10px] text-foreground/40 mb-1">
            <div>Agent</div>
            {Object.entries(WEIGHT_LABELS).map(([key, { label, weight }]) => (
              <div key={key} className="text-center">
                {label}
                <br />
                <span className="text-foreground/25">({weight})</span>
              </div>
            ))}
          </div>

          {/* Agent scores */}
          {Object.entries(selection.agent_scores).map(([agentId, scores]) => {
            const agent = getAgentData(agentId);
            const isSelected = agentId === selection.selected_agent_id;
            const scoreMap = typeof scores === "object" ? scores : {};

            return (
              <div
                key={agentId}
                className={`grid grid-cols-6 gap-1 text-xs py-0.5 ${
                  isSelected ? "text-neon-cyan font-medium" : "text-foreground/60"
                }`}
              >
                <div
                  style={{ color: agent?.color }}
                  className="truncate"
                >
                  {agent?.name || agentId}
                  {isSelected && " *"}
                </div>
                {Object.keys(WEIGHT_LABELS).map((key) => (
                  <div key={key} className="text-center tabular-nums">
                    {typeof scoreMap[key] === "number"
                      ? scoreMap[key].toFixed(2)
                      : "-"}
                  </div>
                ))}
              </div>
            );
          })}

          {selection.conversation_energy != null && (
            <div className="mt-2 text-[10px] text-foreground/40">
              Conversation energy: {selection.conversation_energy.toFixed(2)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

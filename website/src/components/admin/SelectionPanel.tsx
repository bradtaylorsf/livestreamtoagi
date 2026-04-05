"use client";

import type { TurnDetail } from "@/types/admin";

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

const SCORE_FACTORS = [
  { key: "time_since_spoke", label: "Time", weight: 0.3 },
  { key: "topic_relevance", label: "Topic", weight: 0.3 },
  { key: "chattiness", label: "Chat", weight: 0.15 },
  { key: "adjacency_fit", label: "Adj", weight: 0.15 },
  { key: "random_jitter", label: "Rand", weight: 0.1 },
] as const;

interface SelectionPanelProps {
  turnDetail: TurnDetail | null;
  turnIndex: number;
  configSnapshot: Record<string, unknown> | null;
  costByAgent: Record<string, string>;
}

interface AgentScore {
  total: number;
  time_since_spoke?: number;
  topic_relevance?: number;
  chattiness?: number;
  adjacency_fit?: number;
  random_jitter?: number;
  [key: string]: number | undefined;
}

export default function SelectionPanel({
  turnDetail,
  turnIndex,
  configSnapshot,
  costByAgent,
}: SelectionPanelProps) {
  if (!turnDetail) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4 text-xs text-foreground/40">
        Click a turn to see selection analysis
      </div>
    );
  }

  const scores = turnDetail.agent_scores as Record<string, AgentScore>;
  const sortedAgents = Object.entries(scores).sort(
    ([, a], [, b]) => (b.total ?? 0) - (a.total ?? 0),
  );

  return (
    <div className="space-y-4">
      {/* Turn Selection Info */}
      <div className="rounded-lg border border-border bg-surface p-3">
        <h3 className="text-xs font-medium text-foreground/60 mb-2">
          Turn {turnIndex + 1} — Selection Scores
        </h3>
        <div className="space-y-1.5">
          {sortedAgents.map(([agentId, agentScore]) => {
            const isSelected = agentId === turnDetail.selected_agent_id;
            return (
              <div
                key={agentId}
                className={`rounded px-2 py-1.5 text-xs ${
                  isSelected
                    ? "bg-foreground/10 ring-1 ring-foreground/20"
                    : "bg-surface-light"
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span
                    className={`font-medium ${
                      AGENT_TEXT_COLORS[agentId] || "text-foreground/60"
                    }`}
                  >
                    {agentId}
                    {isSelected && (
                      <span className="text-foreground/40 ml-1">✓</span>
                    )}
                  </span>
                  <span className="font-mono text-foreground/50">
                    {(agentScore.total ?? 0).toFixed(3)}
                  </span>
                </div>
                {/* Factor breakdown bar */}
                <div className="flex gap-px h-1.5 rounded overflow-hidden">
                  {SCORE_FACTORS.map((factor) => {
                    const val = agentScore[factor.key] ?? 0;
                    const widthPct = Math.max(val * 100, 1);
                    return (
                      <div
                        key={factor.key}
                        className="bg-foreground/20 rounded-sm"
                        style={{ width: `${widthPct}%` }}
                        title={`${factor.label}: ${val.toFixed(3)} (weight ${factor.weight})`}
                      />
                    );
                  })}
                </div>
                <div className="flex gap-2 mt-1 text-[10px] text-foreground/30">
                  {SCORE_FACTORS.map((factor) => (
                    <span key={factor.key}>
                      {factor.label}:{" "}
                      {(agentScore[factor.key] ?? 0).toFixed(2)}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        {turnDetail.was_interrupt && (
          <div className="mt-2 rounded bg-orange-400/10 px-2 py-1 text-[10px] text-orange-400">
            ⚡ This turn was an interrupt
          </div>
        )}

        {turnDetail.detected_topic && (
          <div className="mt-2 text-[10px] text-foreground/40">
            Topic: {turnDetail.detected_topic}
          </div>
        )}
      </div>

      {/* Config Snapshot */}
      {configSnapshot && Object.keys(configSnapshot).length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <h3 className="text-xs font-medium text-foreground/60 mb-2">
            Conversation Config
          </h3>
          <pre className="text-[10px] text-foreground/40 overflow-x-auto max-h-32 overflow-y-auto">
            {JSON.stringify(configSnapshot, null, 2)}
          </pre>
        </div>
      )}

      {/* Cost Breakdown */}
      {Object.keys(costByAgent).length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <h3 className="text-xs font-medium text-foreground/60 mb-2">
            Cost by Agent
          </h3>
          <div className="space-y-1">
            {Object.entries(costByAgent).map(([agentId, cost]) => (
              <div
                key={agentId}
                className="flex justify-between text-xs text-foreground/50"
              >
                <span
                  className={
                    AGENT_TEXT_COLORS[agentId] || "text-foreground/50"
                  }
                >
                  {agentId}
                </span>
                <span className="font-mono">${cost}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

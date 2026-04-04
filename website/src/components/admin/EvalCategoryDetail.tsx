"use client";

import { useState } from "react";
import type { EvalResult } from "@/types/admin";

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function scoreBg(score: number): string {
  if (score >= 70) return "bg-green-500/20";
  if (score >= 40) return "bg-yellow-500/20";
  return "bg-red-500/20";
}

interface Props {
  result: EvalResult;
}

export default function EvalCategoryDetail({ result }: Props) {
  const [expanded, setExpanded] = useState(false);
  const score = result.score != null ? Number(result.score) : 0;

  return (
    <div className="rounded-lg border border-border bg-surface overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-light transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-foreground capitalize">
            {result.category.replace(/_/g, " ")}
          </span>
          <span
            className={`font-mono font-bold text-lg ${scoreColor(score)}`}
          >
            {score.toFixed(1)}
          </span>
        </div>
        <span className="text-foreground/40 text-xs">
          {expanded ? "collapse" : "expand"} | ${Number(result.cost).toFixed(4)} | {result.tokens_used.toLocaleString()} tokens
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border px-4 py-4 space-y-4">
          {/* Sub-scores */}
          {result.sub_scores && Object.keys(result.sub_scores).length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-foreground/50 mb-2">
                Sub-scores
              </h4>
              <div className="space-y-1">
                {Object.entries(result.sub_scores).map(([key, value]) => (
                  <div key={key} className="flex items-center gap-2">
                    <span className="text-xs text-foreground/60 w-40 capitalize">
                      {key.replace(/_/g, " ")}
                    </span>
                    <div className="flex-1 h-2 bg-border rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${scoreBg(Number(value))}`}
                        style={{ width: `${Math.min(100, Number(value))}%` }}
                      />
                    </div>
                    <span
                      className={`text-xs font-mono w-8 text-right ${scoreColor(Number(value))}`}
                    >
                      {Number(value).toFixed(0)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Reasoning */}
          {result.reasoning && (
            <div>
              <h4 className="text-xs font-medium text-foreground/50 mb-2">
                Reasoning
              </h4>
              <p className="text-sm text-foreground/70 whitespace-pre-wrap">
                {result.reasoning}
              </p>
            </div>
          )}

          {/* Evidence */}
          {result.evidence && Object.keys(result.evidence).length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-foreground/50 mb-2">
                Evidence
              </h4>
              <pre className="text-xs text-foreground/60 bg-surface-light rounded p-3 overflow-x-auto max-h-48 font-mono">
                {JSON.stringify(result.evidence, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

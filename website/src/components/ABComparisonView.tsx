"use client";

import React from "react";
import { scoreColor } from "@/lib/score-utils";

interface EvalRunSummary {
  id: string;
  overall_score: number | null;
  category_scores?: Record<string, number | null>;
  results?: {
    category: string;
    score: number | null;
  }[];
}

function getCategoryEntries(run: EvalRunSummary): { category: string; score: number | null }[] {
  if (run.category_scores && Object.keys(run.category_scores).length > 0) {
    return Object.entries(run.category_scores).map(([category, score]) => ({ category, score }));
  }
  return run.results ?? [];
}

export default function ABComparisonView({
  runA,
  runB,
}: {
  runA: EvalRunSummary;
  runB: EvalRunSummary;
}) {
  const categoriesA = getCategoryEntries(runA);
  const categoriesB = getCategoryEntries(runB);

  const allCategories = Array.from(
    new Set([
      ...categoriesA.map((r) => r.category),
      ...categoriesB.map((r) => r.category),
    ]),
  ).sort();

  return (
    <div
      className="rounded-lg border border-neon-cyan/30 bg-neon-cyan/5 p-4"
      data-testid="ab-comparison"
    >
      <h3 className="text-sm font-medium text-neon-cyan mb-3">
        A/B Comparison
      </h3>
      <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-4 gap-y-1 text-xs">
        {/* Header */}
        <div className="text-foreground/50 font-medium">Category</div>
        <div className="text-foreground/50 font-medium text-right">
          Run A
        </div>
        <div className="text-foreground/50 font-medium text-right">
          Run B
        </div>
        <div className="text-foreground/50 font-medium text-right">
          Delta
        </div>

        {/* Overall */}
        <div className="text-foreground font-medium border-t border-border pt-1 mt-1">
          Overall
        </div>
        <div className="font-mono text-right border-t border-border pt-1 mt-1">
          {runA.overall_score != null ? (
            <span className={scoreColor(Number(runA.overall_score))}>
              {Number(runA.overall_score).toFixed(1)}
            </span>
          ) : (
            <span className="text-foreground/30">&mdash;</span>
          )}
        </div>
        <div className="font-mono text-right border-t border-border pt-1 mt-1">
          {runB.overall_score != null ? (
            <span className={scoreColor(Number(runB.overall_score))}>
              {Number(runB.overall_score).toFixed(1)}
            </span>
          ) : (
            <span className="text-foreground/30">&mdash;</span>
          )}
        </div>
        <div className="font-mono text-right border-t border-border pt-1 mt-1">
          {runA.overall_score != null && runB.overall_score != null
            ? formatDelta(
                Number(runB.overall_score) - Number(runA.overall_score),
              )
            : "\u2014"}
        </div>

        {/* Per category */}
        {allCategories.map((cat) => {
          const a = categoriesA.find((r) => r.category === cat)?.score;
          const b = categoriesB.find((r) => r.category === cat)?.score;
          const delta = a != null && b != null ? b - a : null;
          return (
            <div key={cat} className="contents">
              <div className="text-foreground/60 capitalize">
                {cat.replace(/_/g, " ")}
              </div>
              <div className="font-mono text-right">
                {a != null ? (
                  <span className={scoreColor(a)}>{a.toFixed(1)}</span>
                ) : (
                  <span className="text-foreground/30">&mdash;</span>
                )}
              </div>
              <div className="font-mono text-right">
                {b != null ? (
                  <span className={scoreColor(b)}>{b.toFixed(1)}</span>
                ) : (
                  <span className="text-foreground/30">&mdash;</span>
                )}
              </div>
              <div className="font-mono text-right">
                {delta != null ? formatDelta(delta) : "\u2014"}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatDelta(delta: number): React.ReactElement {
  const color =
    delta > 0
      ? "text-green-400"
      : delta < 0
        ? "text-red-400"
        : "text-foreground/40";
  const sign = delta > 0 ? "+" : "";
  return <span className={color}>{sign}{delta.toFixed(1)}</span>;
}

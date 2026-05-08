"use client";

import { useState, useEffect } from "react";
import { getStats, getEvalCategories } from "@/lib/api";

export interface Highlight {
  value: string;
  label: string;
}

export const HIGHLIGHTS_PLACEHOLDER = "—";

const STATIC_HIGHLIGHTS: Highlight[] = [
  { value: "9 Agents", label: "6 LLM Providers" },
  { value: "100%", label: "Open Source" },
];

export function buildHighlights(
  simulationsCount: number | null,
  evalCategoriesCount: number | null,
): Highlight[] {
  return [
    {
      value:
        evalCategoriesCount != null
          ? String(evalCategoriesCount)
          : HIGHLIGHTS_PLACEHOLDER,
      label: "Eval Categories",
    },
    {
      value:
        simulationsCount != null
          ? String(simulationsCount)
          : HIGHLIGHTS_PLACEHOLDER,
      label: "Simulations Run",
    },
    ...STATIC_HIGHLIGHTS,
  ];
}

export default function ResearchHighlights() {
  const [evalCategoriesCount, setEvalCategoriesCount] = useState<number | null>(null);
  const [simulationsCount, setSimulationsCount] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.allSettled([getStats(), getEvalCategories()]).then((results) => {
      if (cancelled) return;

      if (results[0].status === "fulfilled") {
        setSimulationsCount(results[0].value.total_simulations);
      }
      if (results[1].status === "fulfilled") {
        setEvalCategoriesCount(results[1].value.length);
      }
    });

    return () => { cancelled = true; };
  }, []);

  const highlights = buildHighlights(simulationsCount, evalCategoriesCount);

  return (
    <section>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {highlights.map((item) => (
          <div
            key={item.label}
            className="rounded border border-border bg-surface p-4 text-center"
          >
            <div className="font-pixel text-lg text-neon-cyan">{item.value}</div>
            <div className="text-xs text-foreground/50 mt-1">{item.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

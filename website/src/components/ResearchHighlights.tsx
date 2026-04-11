"use client";

import { useState, useEffect } from "react";
import { getStats, getEvalCategories } from "@/lib/api";

interface Highlight {
  value: string;
  label: string;
  dynamic: boolean;
}

const DEFAULT_HIGHLIGHTS: Highlight[] = [
  { value: "12", label: "Eval Categories", dynamic: true },
  { value: "62+", label: "Simulations Run", dynamic: true },
  { value: "9 Agents", label: "6 LLM Providers", dynamic: false },
  { value: "100%", label: "Open Source", dynamic: false },
];

export default function ResearchHighlights() {
  const [highlights, setHighlights] = useState<Highlight[]>(DEFAULT_HIGHLIGHTS);

  useEffect(() => {
    let cancelled = false;

    Promise.allSettled([getStats(), getEvalCategories()]).then((results) => {
      if (cancelled) return;

      const stats = results[0].status === "fulfilled" ? results[0].value : null;
      const categories = results[1].status === "fulfilled" ? results[1].value : null;

      setHighlights([
        {
          value: categories ? String(categories.length) : DEFAULT_HIGHLIGHTS[0].value,
          label: "Eval Categories",
          dynamic: true,
        },
        {
          value: stats ? `${stats.total_simulations}+` : DEFAULT_HIGHLIGHTS[1].value,
          label: "Simulations Run",
          dynamic: true,
        },
        { value: "9 Agents", label: "6 LLM Providers", dynamic: false },
        { value: "100%", label: "Open Source", dynamic: false },
      ]);
    });

    return () => { cancelled = true; };
  }, []);

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

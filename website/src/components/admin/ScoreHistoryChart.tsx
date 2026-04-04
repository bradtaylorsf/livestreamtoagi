"use client";

import { useEffect, useState } from "react";
import { fetchEvalHistory } from "@/lib/admin-api";
import type { EvalHistoryPoint } from "@/types/admin";

const CATEGORIES = [
  "entertainment",
  "safety",
  "dialogue_quality",
  "productivity",
  "errors",
];

const COLORS: Record<string, string> = {
  entertainment: "#f59e0b",
  safety: "#ef4444",
  dialogue_quality: "#3b82f6",
  productivity: "#22c55e",
  errors: "#a855f7",
};

export default function ScoreHistoryChart() {
  const [history, setHistory] = useState<Record<string, EvalHistoryPoint[]>>({});
  const [selectedCat, setSelectedCat] = useState<string>("entertainment");

  useEffect(() => {
    CATEGORIES.forEach((cat) => {
      fetchEvalHistory(cat)
        .then((data) => setHistory((prev) => ({ ...prev, [cat]: data })))
        .catch(() => {});
    });
  }, []);

  const data = history[selectedCat] ?? [];
  if (data.length === 0) {
    return (
      <div className="text-sm text-foreground/40 text-center py-8">
        No eval history available
      </div>
    );
  }

  const maxScore = 100;
  const width = 600;
  const height = 200;
  const padding = { top: 20, right: 20, bottom: 30, left: 40 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  const xStep = data.length > 1 ? chartW / (data.length - 1) : chartW;
  const points = data.map((d, i) => ({
    x: padding.left + i * xStep,
    y: padding.top + chartH - (((d.score ?? 0) / maxScore) * chartH),
    score: d.score ?? 0,
  }));

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");

  return (
    <div>
      <div className="flex gap-2 mb-3 flex-wrap">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCat(cat)}
            className={`text-xs px-2 py-1 rounded border transition-colors capitalize ${
              selectedCat === cat
                ? "border-neon-cyan text-neon-cyan"
                : "border-border text-foreground/40 hover:text-foreground/60"
            }`}
          >
            {cat.replace(/_/g, " ")}
          </button>
        ))}
      </div>

      <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="overflow-visible">
        {/* Grid lines */}
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line
              x1={padding.left}
              y1={padding.top + chartH - (v / maxScore) * chartH}
              x2={width - padding.right}
              y2={padding.top + chartH - (v / maxScore) * chartH}
              stroke="currentColor"
              strokeOpacity={0.1}
            />
            <text
              x={padding.left - 5}
              y={padding.top + chartH - (v / maxScore) * chartH + 3}
              textAnchor="end"
              className="fill-foreground/30 text-[10px]"
            >
              {v}
            </text>
          </g>
        ))}

        {/* Line */}
        <path
          d={line}
          fill="none"
          stroke={COLORS[selectedCat] ?? "#0ff"}
          strokeWidth={2}
        />

        {/* Dots */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={3}
            fill={COLORS[selectedCat] ?? "#0ff"}
          />
        ))}
      </svg>
    </div>
  );
}

"use client";

import { scoreColor, scoreCardBg } from "@/lib/score-utils";

interface ScoreCardProps {
  label: string;
  score: number | null;
  delta?: number | null;
  size?: "sm" | "lg";
}

export default function ScoreCard({ label, score, delta, size = "sm" }: ScoreCardProps) {
  const displayScore = score != null ? score : 0;
  const isLarge = size === "lg";

  return (
    <div
      className={`rounded-lg border p-3 ${scoreCardBg(displayScore)} ${isLarge ? "col-span-2 p-5" : ""}`}
    >
      <div className="text-xs text-foreground/50 mb-1">{label}</div>
      <div className={`font-mono font-bold ${scoreColor(displayScore)} ${isLarge ? "text-3xl" : "text-xl"}`}>
        {score != null ? displayScore.toFixed(1) : "—"}
      </div>
      {delta != null && delta !== 0 && (
        <div
          className={`text-xs mt-1 ${delta > 0 ? "text-green-400" : "text-red-400"}`}
        >
          {delta > 0 ? "+" : ""}
          {delta.toFixed(1)}
        </div>
      )}
    </div>
  );
}

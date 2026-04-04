"use client";

interface ScoreCardProps {
  label: string;
  score: number | null;
  delta?: number | null;
  size?: "sm" | "lg";
}

function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

function scoreBg(score: number): string {
  if (score >= 70) return "border-green-500/30 bg-green-500/5";
  if (score >= 40) return "border-yellow-500/30 bg-yellow-500/5";
  return "border-red-500/30 bg-red-500/5";
}

export default function ScoreCard({ label, score, delta, size = "sm" }: ScoreCardProps) {
  const displayScore = score != null ? score : 0;
  const isLarge = size === "lg";

  return (
    <div
      className={`rounded-lg border p-3 ${scoreBg(displayScore)} ${isLarge ? "col-span-2 p-5" : ""}`}
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

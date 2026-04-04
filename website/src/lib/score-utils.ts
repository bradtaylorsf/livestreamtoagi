export function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 40) return "text-yellow-400";
  return "text-red-400";
}

/** Background fill — use for progress bars and inline highlights. */
export function scoreBg(score: number): string {
  if (score >= 70) return "bg-green-500/20";
  if (score >= 40) return "bg-yellow-500/20";
  return "bg-red-500/20";
}

/** Card-level background + border — use for ScoreCard containers. */
export function scoreCardBg(score: number): string {
  if (score >= 70) return "border-green-500/30 bg-green-500/5";
  if (score >= 40) return "border-yellow-500/30 bg-yellow-500/5";
  return "border-red-500/30 bg-red-500/5";
}

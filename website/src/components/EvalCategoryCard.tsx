import Link from "next/link";
import { scoreColor, scoreCardBg } from "@/lib/score-utils";

export interface EvalCategoryCardProps {
  name: string;
  score: number | null;
  trend: "up" | "down" | "flat";
  description: string;
}

const TREND_ICONS: Record<string, string> = {
  up: "\u2191",
  down: "\u2193",
  flat: "\u2192",
};

const TREND_COLORS: Record<string, string> = {
  up: "text-green-400",
  down: "text-red-400",
  flat: "text-foreground/40",
};

export default function EvalCategoryCard({
  name,
  score,
  trend,
  description,
}: EvalCategoryCardProps) {
  const displayName = name.replace(/_/g, " ");
  return (
    <Link
      href={`/evals/${encodeURIComponent(name)}`}
      className={`rounded-lg border p-4 transition-colors hover:bg-surface-light block ${
        score != null ? scoreCardBg(score) : "border-border bg-surface"
      }`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-foreground capitalize">
          {displayName}
        </h3>
        <span className={`text-sm ${TREND_COLORS[trend]}`}>
          {TREND_ICONS[trend]}
        </span>
      </div>
      <div className="mt-2">
        {score != null ? (
          <span className={`text-2xl font-mono ${scoreColor(score)}`}>
            {score.toFixed(1)}
          </span>
        ) : (
          <span className="text-2xl font-mono text-foreground/30">&mdash;</span>
        )}
      </div>
      <p className="text-xs text-foreground/50 mt-2 line-clamp-2">
        {description}
      </p>
    </Link>
  );
}

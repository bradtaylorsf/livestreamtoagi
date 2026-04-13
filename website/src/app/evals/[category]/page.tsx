"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getEvalHistory, getEvalRuns, type EvalHistoryPoint, type PublicEvalRun } from "@/lib/api";
import { scoreColor } from "@/lib/score-utils";

const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  creativity: "Measures originality, novelty, and variety in agent outputs — dialogue, artifacts, and problem-solving approaches.",
  agency: "Measures proactive goal-directed behavior. Do agents take initiative or only respond when prompted?",
  productivity: "Measures tangible output — artifacts created, tasks completed, challenges addressed.",
  social_dynamics: "Measures social behavior — alliance formation, conflict resolution, group coordination, trust dynamics.",
  economic_behavior: "Measures budget awareness — cost tracking, resource allocation, spending justification.",
  internal_state: "Measures coherence of mood, personality stability, memory usage, and emotional consistency.",
  entertainment: "Measures watchability — humor, drama, surprise, tension, and audience engagement potential.",
  safety: "Measures policy compliance — content filter triggers, boundary adherence, harmful output prevention.",
  errors: "Measures reliability — crashes, hallucinations, formatting failures, tool misuse, and recovery behavior.",
  dialogue_quality: "Measures conversation quality — turn relevance, topic coherence, natural language flow.",
  simulation_narrative: "Measures emergent storytelling — narrative arcs, character development, plot progression.",
  world_evolution: "Measures environmental change — building activity, spatial modifications, world state progression.",
};

export default function CategoryDetailPage() {
  const params = useParams();
  const category = params.category as string;
  const [history, setHistory] = useState<EvalHistoryPoint[]>([]);
  const [runs, setRuns] = useState<PublicEvalRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getEvalHistory(category).catch(() => []),
      getEvalRuns().catch(() => []),
    ])
      .then(([h, r]) => {
        setHistory(h);
        setRuns(r);
      })
      .finally(() => setLoading(false));
  }, [category]);

  const displayName = category.replace(/_/g, " ");
  const description = CATEGORY_DESCRIPTIONS[category] ?? `Evaluation scores for ${displayName}.`;

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading...</p>
      </div>
    );
  }

  // Filter runs that have a score for this category
  const relevantRuns = runs.filter(
    (r) => r.category_scores?.[category] != null,
  );

  const latestScore =
    history.length > 0 ? history[history.length - 1]?.score : null;

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-8">
      <div>
        <Link
          href="/evals"
          className="text-xs text-foreground/40 hover:text-foreground/60 transition-colors"
        >
          &larr; Back to dashboard
        </Link>
      </div>

      <section className="space-y-3">
        <h1 className="font-pixel text-base text-neon-cyan capitalize">
          {displayName}
        </h1>
        <p className="text-sm text-foreground/60">{description}</p>
        {latestScore != null && (
          <div className="flex items-baseline gap-2">
            <span className={`text-4xl font-mono ${scoreColor(latestScore)}`}>
              {latestScore.toFixed(1)}
            </span>
            <span className="text-xs text-foreground/40">latest score</span>
          </div>
        )}
      </section>

      {/* Score history for this category */}
      <section className="space-y-3">
        <h2 className="font-pixel text-xs text-neon-magenta">SCORE HISTORY</h2>
        {history.length === 0 ? (
          <p className="text-sm text-foreground/40 text-center py-8">
            No history data available for this category.
          </p>
        ) : (
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="space-y-2">
              {history.map((point, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between text-xs"
                >
                  <span className="text-foreground/50">
                    {point.created_at
                      ? new Date(point.created_at).toLocaleDateString()
                      : `Run ${i + 1}`}
                  </span>
                  <span
                    className={`font-mono ${
                      point.score != null
                        ? scoreColor(point.score)
                        : "text-foreground/30"
                    }`}
                  >
                    {point.score != null ? point.score.toFixed(1) : "\u2014"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Recent runs with this category's score */}
      <section className="space-y-3">
        <h2 className="font-pixel text-xs text-neon-magenta">RECENT RUNS</h2>
        {relevantRuns.length === 0 ? (
          <p className="text-sm text-foreground/40 text-center py-8">
            No runs with scores for this category.
          </p>
        ) : (
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th scope="col" className="px-4 py-2 font-medium">Date</th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">
                    {displayName} Score
                  </th>
                  <th scope="col" className="px-4 py-2 font-medium text-right">
                    Overall Score
                  </th>
                </tr>
              </thead>
              <tbody>
                {relevantRuns.map((run) => {
                  const catScore = run.category_scores[category];
                  const overall =
                    run.overall_score != null
                      ? Number(run.overall_score)
                      : null;
                  return (
                    <tr
                      key={run.id}
                      className="border-b border-border last:border-0"
                    >
                      <td className="px-4 py-2 text-foreground/60 text-xs">
                        {run.date}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {catScore != null ? (
                          <span className={scoreColor(catScore)}>
                            {catScore.toFixed(1)}
                          </span>
                        ) : (
                          "\u2014"
                        )}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {overall != null ? (
                          <span className={scoreColor(overall)}>
                            {overall.toFixed(1)}
                          </span>
                        ) : (
                          "\u2014"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

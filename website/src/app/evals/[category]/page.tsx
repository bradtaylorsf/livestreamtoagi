"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  getEvalHistory,
  getEvalRuns,
  getEvalPrompts,
  type EvalHistoryPoint,
  type PublicEvalRun,
  type EvalPrompt,
} from "@/lib/api";
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

const GITHUB_BASE =
  "https://github.com/bradtaylor/livestreamtoagi/blob/main/evals/prompts";

type TabId = "scores" | "prompts";

export default function CategoryDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const category = params.category as string;

  const activeTab = (searchParams.get("tab") as TabId) || "scores";

  const [history, setHistory] = useState<EvalHistoryPoint[]>([]);
  const [runs, setRuns] = useState<PublicEvalRun[]>([]);
  const [prompt, setPrompt] = useState<EvalPrompt | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedSchema, setExpandedSchema] = useState(false);

  useEffect(() => {
    Promise.all([
      getEvalHistory(category).catch(() => []),
      getEvalRuns().catch(() => []),
      getEvalPrompts().catch(() => []),
    ])
      .then(([h, r, prompts]) => {
        setHistory(h);
        setRuns(r);
        const match = prompts.find((p) => p.name === category);
        setPrompt(match ?? null);
      })
      .finally(() => setLoading(false));
  }, [category]);

  const setTab = (tab: TabId) => {
    const newParams = new URLSearchParams(searchParams.toString());
    newParams.set("tab", tab);
    router.push(`?${newParams.toString()}`);
  };

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

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border" role="tablist" aria-label="Category detail tabs">
        {(["scores", "prompts"] as const).map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`panel-${tab}`}
            onClick={() => setTab(tab)}
            className={`px-4 py-2 text-xs font-medium transition-colors capitalize ${
              activeTab === tab
                ? "text-neon-cyan border-b-2 border-neon-cyan -mb-px"
                : "text-foreground/40 hover:text-foreground/60"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Scores tab */}
      {activeTab === "scores" && (
        <div id="panel-scores" role="tabpanel" aria-labelledby="tab-scores" className="space-y-8">
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
                      <th scope="col" className="px-4 py-2 font-medium">Simulation</th>
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
                          <td className="px-4 py-2 text-xs">
                            <Link
                              href={`/simulations/${run.simulation_id}?tab=evals`}
                              className="text-neon-cyan hover:underline"
                            >
                              {run.simulation_name || run.simulation_id.slice(0, 8) + "..."}
                            </Link>
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
      )}

      {/* Prompts tab */}
      {activeTab === "prompts" && (
        <div id="panel-prompts" role="tabpanel" aria-labelledby="tab-prompts" className="space-y-6">
          {prompt == null ? (
            <p className="text-sm text-foreground/40 text-center py-12">
              No eval prompt found for this category. The backend may not be running.
            </p>
          ) : (
            <div
              className="rounded border border-border bg-surface"
              data-testid={`prompt-${prompt.name}`}
            >
              {/* Category header */}
              <div className="px-4 py-3 border-b border-border flex items-center justify-between flex-wrap gap-2">
                <div>
                  <h3 className="font-pixel text-xs text-neon-cyan">
                    {prompt.name.replace(/_/g, " ").toUpperCase()}
                  </h3>
                  {prompt.description && (
                    <p className="text-xs text-foreground/50 mt-0.5">
                      {prompt.description}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3 text-xs text-foreground/40">
                  {prompt.model && <span>Judge: {prompt.model}</span>}
                  {prompt.temperature != null && (
                    <span>Temp: {prompt.temperature}</span>
                  )}
                  <a
                    href={`${GITHUB_BASE}/${prompt.name}.yaml`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-neon-cyan hover:underline"
                  >
                    View source
                  </a>
                </div>
              </div>

              <div className="p-4 space-y-4">
                {/* System prompt */}
                <div>
                  <h4 className="text-xs text-foreground/50 mb-2 font-medium">
                    System Prompt
                  </h4>
                  <pre
                    className="text-xs text-foreground/70 font-mono whitespace-pre-wrap bg-background rounded border border-border p-3 max-h-64 overflow-y-auto leading-relaxed"
                    data-testid={`system-prompt-${prompt.name}`}
                  >
                    {prompt.system.trim()}
                  </pre>
                </div>

                {/* Rubric */}
                <div>
                  <h4 className="text-xs text-foreground/50 mb-2 font-medium">
                    Scoring Rubric
                  </h4>
                  <div
                    className="space-y-1"
                    data-testid={`rubric-${prompt.name}`}
                  >
                    {Object.entries(prompt.rubric).map(([range, desc]) => (
                      <div
                        key={range}
                        className="flex gap-3 text-xs border-b border-border/50 last:border-0 py-1.5"
                      >
                        <span className="font-mono text-neon-cyan shrink-0 w-16">
                          {range}
                        </span>
                        <span className="text-foreground/60">{desc}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Sub-scores */}
                <div>
                  <h4 className="text-xs text-foreground/50 mb-2 font-medium">
                    Sub-scores
                  </h4>
                  <ul
                    className="space-y-1"
                    data-testid={`sub-scores-${prompt.name}`}
                  >
                    {prompt.sub_scores.map((sub, idx) => {
                      if (typeof sub === "string") {
                        return (
                          <li
                            key={idx}
                            className="text-xs text-foreground/60 flex items-center gap-2"
                          >
                            <span className="w-1.5 h-1.5 rounded-full bg-neon-cyan/50 shrink-0" />
                            {sub}
                          </li>
                        );
                      }
                      return Object.entries(sub).map(([name, desc]) => (
                        <li
                          key={name}
                          className="text-xs text-foreground/60 flex items-start gap-2"
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-neon-cyan/50 shrink-0 mt-1" />
                          <span>
                            <strong className="text-foreground/80">{name}</strong>
                            {" — "}
                            {desc}
                          </span>
                        </li>
                      ));
                    })}
                  </ul>
                </div>

                {/* Output schema (collapsible) */}
                <div>
                  <button
                    onClick={() => setExpandedSchema(!expandedSchema)}
                    className="text-xs text-foreground/50 hover:text-foreground/70 flex items-center gap-1 transition-colors"
                  >
                    <svg
                      className={`w-3 h-3 transition-transform ${expandedSchema ? "rotate-90" : ""}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M9 5l7 7-7 7"
                      />
                    </svg>
                    Output Schema
                  </button>
                  {expandedSchema && (
                    <pre className="mt-2 text-xs text-foreground/60 font-mono whitespace-pre-wrap bg-background rounded border border-border p-3 max-h-48 overflow-y-auto">
                      {JSON.stringify(prompt.output_schema, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            </div>
          )}

          <p className="text-xs text-foreground/40">
            See all eval prompts on the{" "}
            <Link href="/evals/prompts" className="text-neon-cyan hover:underline">
              prompts page
            </Link>
            .
          </p>
        </div>
      )}
    </div>
  );
}

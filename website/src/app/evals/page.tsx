"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import EvalCategoryCard from "@/components/EvalCategoryCard";
import type { EvalCategoryCardProps } from "@/components/EvalCategoryCard";
import ScoreHistoryChart from "@/components/ScoreHistoryChart";
import ABComparisonView from "@/components/ABComparisonView";
import {
  getEvalRuns,
  getEvalCategories,
  getEvalHistory,
  type PublicEvalRun,
  type EvalHistoryPoint,
} from "@/lib/api";
import { scoreColor } from "@/lib/score-utils";
import { exportAsJSON, exportAsCSV } from "@/lib/export";

const CATEGORY_DESCRIPTIONS: Record<string, string> = {
  creativity: "How original and varied are agent outputs? Measures novelty in dialogue, artifacts, and problem-solving.",
  agency: "Do agents take initiative and pursue goals? Measures proactive behavior vs. passive responding.",
  productivity: "Are agents making tangible progress on tasks? Measures artifacts created, challenges completed.",
  social_dynamics: "How do agents interact socially? Measures alliance formation, conflict, and group behavior.",
  economic_behavior: "Can agents manage budgets? Measures cost awareness, resource allocation, spending patterns.",
  internal_state: "Do agents maintain coherent internal states? Measures mood consistency, memory use, personality stability.",
  entertainment: "Is this fun to watch? Measures humor, drama, surprise, and audience engagement potential.",
  safety: "Do agents stay within acceptable bounds? Measures content filter triggers and policy compliance.",
  errors: "How often do things break? Measures crashes, hallucinations, formatting failures, and recovery.",
  dialogue_quality: "How coherent and engaging is conversation? Measures turn relevance, topic flow, and natural language quality.",
  simulation_narrative: "Does a story emerge? Measures narrative arcs, character development, and plot progression.",
  world_evolution: "Does the world change? Measures environment modification, building activity, and spatial dynamics.",
};

function calculateTrend(history: EvalHistoryPoint[]): "up" | "down" | "flat" {
  if (history.length < 2) return "flat";
  const recent = history.slice(-3);
  const first = recent[0]?.score ?? 0;
  const last = recent[recent.length - 1]?.score ?? 0;
  const diff = last - first;
  if (diff > 2) return "up";
  if (diff < -2) return "down";
  return "flat";
}

export default function EvalsPage() {
  const [categories, setCategories] = useState<EvalCategoryCardProps[]>([]);
  const [runs, setRuns] = useState<PublicEvalRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [compareA, setCompareA] = useState<string | null>(null);
  const [compareB, setCompareB] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getEvalCategories().catch(() => Object.keys(CATEGORY_DESCRIPTIONS)),
      getEvalRuns().catch(() => []),
    ])
      .then(async ([cats, evalRuns]) => {
        setRuns(evalRuns);

        // Build category cards from history data
        const cards: EvalCategoryCardProps[] = [];
        for (const cat of cats) {
          let history: EvalHistoryPoint[] = [];
          try {
            history = await getEvalHistory(cat);
          } catch {
            // No history available
          }
          const latestScore =
            history.length > 0 ? (history[history.length - 1].score ?? null) : null;
          cards.push({
            name: cat,
            score: latestScore,
            trend: calculateTrend(history),
            description:
              CATEGORY_DESCRIPTIONS[cat] ?? `Evaluation scores for ${cat.replace(/_/g, " ")}.`,
          });
        }
        setCategories(cards);
      })
      .finally(() => setLoading(false));
  }, []);

  const latestRun = runs[0] ?? null;
  const runAData = compareA ? runs.find((r) => r.id === compareA) : null;
  const runBData = compareB ? runs.find((r) => r.id === compareB) : null;

  const handleExport = (format: "json" | "csv") => {
    if (runs.length === 0) return;
    if (format === "json") {
      exportAsJSON(runs, "eval-data.json");
    } else {
      const flat = runs.map((r) => ({
        id: r.id,
        simulation_id: r.simulation_id,
        date: r.date,
        overall_score: r.overall_score,
        cost: r.cost,
        model_versions: JSON.stringify(r.model_versions),
        ...Object.fromEntries(
          Object.entries(r.category_scores ?? {}).map(([k, v]) => [
            `score_${k}`,
            v,
          ]),
        ),
      }));
      exportAsCSV(flat, "eval-data.csv");
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading evaluation data...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-12">
      {/* Hero */}
      <section className="space-y-3">
        <h1 className="font-pixel text-lg text-neon-cyan">
          EVALUATION DASHBOARD
        </h1>
        <p className="text-sm text-foreground/60 max-w-2xl">
          Transparent, read-only view of how the agent system performs across
          all 12 evaluation categories. Every score is public.
        </p>
        <div
          className="rounded border border-yellow-500/30 bg-yellow-500/5 p-3 text-xs text-yellow-400/80"
          data-testid="llm-judge-disclaimer"
        >
          <strong>LLM-as-judge note:</strong> All scores are generated by an
          LLM judge (Claude Sonnet 4.6). We acknowledge the circularity of
          using an LLM to evaluate LLMs.{" "}
          <Link href="/about#limitations" className="underline">
            Read about our limitations
          </Link>
          .
        </div>
      </section>

      {/* Latest run summary */}
      {latestRun && (
        <section className="space-y-2">
          <h2 className="font-pixel text-xs text-neon-magenta">LATEST RUN</h2>
          <div className="flex items-baseline gap-4">
            <span
              className={`text-4xl font-mono ${
                latestRun.overall_score != null
                  ? scoreColor(latestRun.overall_score)
                  : "text-foreground/30"
              }`}
            >
              {latestRun.overall_score != null
                ? latestRun.overall_score.toFixed(1)
                : "\u2014"}
            </span>
            <span className="text-xs text-foreground/40">
              {latestRun.date} &middot; ${Number(latestRun.cost).toFixed(4)}
            </span>
          </div>
        </section>
      )}

      {/* Category cards */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">
          12 EVAL CATEGORIES
        </h2>
        <div
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
          data-testid="category-grid"
        >
          {(categories.length > 0
            ? categories
            : Object.entries(CATEGORY_DESCRIPTIONS).map(([name, desc]) => ({
                name,
                score: null,
                trend: "flat" as const,
                description: desc,
              }))
          ).map((cat) => (
            <EvalCategoryCard key={cat.name} {...cat} />
          ))}
        </div>
      </section>

      {/* Score History Chart */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">SCORE TRENDS</h2>
        <div className="rounded-lg border border-border bg-surface p-4">
          <ScoreHistoryChart />
        </div>
      </section>

      {/* A/B Comparison */}
      {runAData && runBData && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-pixel text-xs text-neon-magenta">
              A/B COMPARISON
            </h2>
            <button
              onClick={() => {
                setCompareA(null);
                setCompareB(null);
              }}
              className="text-xs text-foreground/40 hover:text-foreground/60"
            >
              Clear
            </button>
          </div>
          <ABComparisonView runA={runAData} runB={runBData} />
        </section>
      )}

      {/* Simulation Runs */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-pixel text-xs text-neon-magenta">
            SIMULATION RUNS
          </h2>
          <div className="flex gap-2">
            <button
              onClick={() => handleExport("json")}
              className="text-xs px-2 py-1 rounded border border-border text-foreground/40 hover:text-foreground/60 transition-colors"
              data-testid="export-json"
            >
              Export JSON
            </button>
            <button
              onClick={() => handleExport("csv")}
              className="text-xs px-2 py-1 rounded border border-border text-foreground/40 hover:text-foreground/60 transition-colors"
              data-testid="export-csv"
            >
              Export CSV
            </button>
          </div>
        </div>

        {runs.length === 0 ? (
          <div className="text-center py-12 text-foreground/40 text-sm">
            No simulation runs yet. Eval data will appear here after the first
            simulation.
          </div>
        ) : (
          <div className="rounded-lg border border-border bg-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-foreground/50">
                  <th className="px-4 py-2 font-medium">Compare</th>
                  <th className="px-4 py-2 font-medium">Date</th>
                  <th className="px-4 py-2 font-medium text-right">Score</th>
                  <th className="px-4 py-2 font-medium text-right">Cost</th>
                  <th className="px-4 py-2 font-medium">Model Versions</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const score =
                    run.overall_score != null
                      ? Number(run.overall_score)
                      : null;
                  const isSelected =
                    run.id === compareA || run.id === compareB;
                  return (
                    <tr
                      key={run.id}
                      className={`border-b border-border last:border-0 ${
                        isSelected ? "bg-neon-cyan/5" : ""
                      }`}
                    >
                      <td className="px-4 py-2">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {
                            if (isSelected) {
                              if (run.id === compareA) setCompareA(null);
                              else setCompareB(null);
                            } else {
                              if (!compareA) setCompareA(run.id);
                              else if (!compareB) setCompareB(run.id);
                            }
                          }}
                          className="accent-neon-cyan"
                        />
                      </td>
                      <td className="px-4 py-2 text-foreground/60 text-xs">
                        {run.date}
                      </td>
                      <td className="px-4 py-2 text-right font-mono">
                        {score != null ? (
                          <span className={scoreColor(score)}>
                            {score.toFixed(1)}
                          </span>
                        ) : (
                          "\u2014"
                        )}
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-foreground/50">
                        ${Number(run.cost).toFixed(4)}
                      </td>
                      <td className="px-4 py-2" data-testid="model-versions">
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(run.model_versions ?? {}).map(
                            ([agent, model]) => (
                              <span
                                key={agent}
                                className="text-[10px] px-1 py-0.5 rounded bg-surface-light text-foreground/50"
                              >
                                {agent}: {model}
                              </span>
                            ),
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Methodology */}
      <section className="space-y-4">
        <h2 className="font-pixel text-xs text-neon-magenta">METHODOLOGY</h2>
        <div className="text-sm text-foreground/70 space-y-3 leading-relaxed">
          <p>
            Each simulation run is evaluated across 12 categories by an LLM
            judge (Claude Sonnet 4.6). The judge receives the full conversation
            transcript, agent configs, and a category-specific rubric defined in
            YAML.
          </p>
          <p>
            Eval prompt templates are open source.{" "}
            <a
              href="https://github.com/bradtaylor/livestreamtoagi/tree/main/evals"
              target="_blank"
              rel="noopener noreferrer"
              className="text-neon-cyan hover:underline"
            >
              View eval configs on GitHub &rarr;
            </a>
          </p>
        </div>
      </section>
    </div>
  );
}

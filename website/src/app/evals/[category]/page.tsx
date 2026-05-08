"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiRequestError,
  getEvalHistory,
  getEvalRunDetail,
  getEvalRuns,
  getEvalPrompts,
  getSimulations,
  runSimulationEval,
  type EvalHistoryPoint,
  type PublicEvalRun,
  type EvalPrompt,
  type PublicSimulation,
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

  const [simulations, setSimulations] = useState<PublicSimulation[]>([]);
  const [selectedSimId, setSelectedSimId] = useState<string>("");
  const [runStatus, setRunStatus] = useState<
    "idle" | "running" | "completed" | "failed" | "unauthorized"
  >("idle");
  const [runMessage, setRunMessage] = useState<string | null>(null);

  const refreshScores = useCallback(async () => {
    const [h, r] = await Promise.all([
      getEvalHistory(category).catch(() => []),
      getEvalRuns().catch(() => []),
    ]);
    setHistory(h);
    setRuns(r);
  }, [category]);

  useEffect(() => {
    Promise.all([
      getEvalHistory(category).catch(() => []),
      getEvalRuns().catch(() => []),
      getEvalPrompts().catch(() => []),
      getSimulations({ limit: 50 }).catch(() => ({
        items: [],
        total: 0,
        limit: 50,
        offset: 0,
      })),
    ])
      .then(([h, r, prompts, sims]) => {
        setHistory(h);
        setRuns(r);
        const match = prompts.find((p) => p.name === category);
        setPrompt(match ?? null);
        const simList = sims.items ?? [];
        setSimulations(simList);
        if (simList.length > 0) {
          setSelectedSimId(simList[0].id);
        }
      })
      .finally(() => setLoading(false));
  }, [category]);

  const handleRunEval = useCallback(async () => {
    if (!selectedSimId) return;
    setRunStatus("running");
    setRunMessage(null);
    let evalRunId: string;
    try {
      const resp = await runSimulationEval(selectedSimId, {
        categories: [category],
      });
      evalRunId = resp.eval_run_id;
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 401) {
        setRunStatus("unauthorized");
        setRunMessage("Admin login required");
        return;
      }
      setRunStatus("failed");
      setRunMessage(err instanceof Error ? err.message : "Failed to start eval");
      return;
    }

    const POLL_INTERVAL_MS = 3000;
    const MAX_POLLS = 200;
    for (let i = 0; i < MAX_POLLS; i++) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      const detail = await getEvalRunDetail(evalRunId);
      if (!detail) continue;
      const status = detail.status;
      if (status === "completed") {
        await refreshScores();
        const score = detail.category_scores?.[category];
        setRunStatus("completed");
        setRunMessage(
          score != null ? `Completed — score: ${score.toFixed(1)}` : "Completed",
        );
        return;
      }
      if (status === "failed") {
        setRunStatus("failed");
        setRunMessage("Eval run failed");
        return;
      }
    }
    setRunStatus("failed");
    setRunMessage("Timed out waiting for eval to finish");
  }, [category, selectedSimId, refreshScores]);

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
          {/* Run eval control (admin) */}
          <section className="space-y-3">
            <h2 className="font-pixel text-xs text-neon-magenta">RUN EVAL</h2>
            <div className="rounded-lg border border-border bg-surface p-4 space-y-3">
              <div className="flex flex-wrap items-end gap-3">
                <div className="flex-1 min-w-[200px]">
                  <label
                    htmlFor="run-eval-sim"
                    className="block text-xs text-foreground/50 mb-1"
                  >
                    Simulation
                  </label>
                  <select
                    id="run-eval-sim"
                    value={selectedSimId}
                    onChange={(e) => setSelectedSimId(e.target.value)}
                    disabled={runStatus === "running" || simulations.length === 0}
                    className="w-full rounded border border-border bg-background px-2 py-1.5 text-xs text-foreground/80"
                  >
                    {simulations.length === 0 && (
                      <option value="">No simulations available</option>
                    )}
                    {simulations.map((sim) => (
                      <option key={sim.id} value={sim.id}>
                        {sim.name || sim.id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={handleRunEval}
                  disabled={runStatus === "running" || !selectedSimId}
                  className="rounded border border-neon-cyan bg-neon-cyan/10 px-4 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {runStatus === "running" ? "Running…" : "Run eval now"}
                </button>
              </div>
              {runStatus === "running" && (
                <p className="text-xs text-foreground/60 flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="inline-block w-3 h-3 rounded-full border-2 border-neon-cyan border-t-transparent animate-spin"
                  />
                  Running eval — this may take a few minutes…
                </p>
              )}
              {runStatus === "completed" && runMessage && (
                <p className="text-xs text-green-400">{runMessage}</p>
              )}
              {runStatus === "failed" && runMessage && (
                <p className="text-xs text-red-400">{runMessage}</p>
              )}
              {runStatus === "unauthorized" && (
                <p className="text-xs text-yellow-400">
                  {runMessage ?? "Admin login required"}
                </p>
              )}
            </div>
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

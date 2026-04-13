"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getEvalPrompts, type EvalPrompt } from "@/lib/api";

const GITHUB_BASE =
  "https://github.com/bradtaylor/livestreamtoagi/blob/main/evals/prompts";

export default function EvalPromptsPage() {
  const [prompts, setPrompts] = useState<EvalPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedSchema, setExpandedSchema] = useState<Set<string>>(new Set());

  useEffect(() => {
    getEvalPrompts()
      .then(setPrompts)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const toggleSchema = (name: string) => {
    setExpandedSchema((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading eval prompts...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 space-y-10">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/evals" className="hover:text-foreground/60">
          Evals
        </Link>
        {" / "}
        <span className="text-foreground/60">Prompts</span>
      </div>

      {/* Header */}
      <section className="space-y-3">
        <h1 className="font-pixel text-lg text-neon-cyan">
          EVALUATION PROMPTS
        </h1>
        <p className="text-sm text-foreground/60 max-w-2xl leading-relaxed">
          Every simulation is evaluated across {prompts.length || 12} categories
          by an LLM judge. Below are the actual prompts, rubrics, and scoring
          criteria used — nothing is hidden. This is exactly what the judge LLM
          sees when scoring a simulation run.
        </p>
      </section>

      {/* How LLM-as-judge works */}
      <section className="rounded border border-neon-cyan/30 bg-neon-cyan/5 p-4 space-y-2">
        <h2 className="font-pixel text-xs text-neon-magenta">
          HOW LLM-AS-JUDGE WORKS
        </h2>
        <div className="text-xs text-foreground/60 space-y-2 leading-relaxed">
          <p>
            For each category, we send the judge LLM (typically Claude Sonnet
            4.6) a system prompt defining its evaluation role, along with the
            full simulation data — transcripts, artifacts, agent states, and
            more. The judge returns a 0-100 score with reasoning and sub-scores.
          </p>
          <p>
            We acknowledge the circularity of using an LLM to evaluate LLMs. The
            prompts below are open-source specifically so the community can
            scrutinize, critique, and improve them.
          </p>
        </div>
      </section>

      {/* How to contribute */}
      <section className="rounded border border-neon-magenta/30 bg-neon-magenta/5 p-4 space-y-2">
        <h2 className="font-pixel text-xs text-neon-magenta">
          HOW TO CONTRIBUTE
        </h2>
        <p className="text-xs text-foreground/60 leading-relaxed">
          Think a rubric is too lenient? Missing a sub-score? Want to adjust the
          scoring criteria? Each category links to its YAML source file on
          GitHub — submit a PR to improve how we evaluate simulations.
        </p>
      </section>

      {/* Prompt cards */}
      <div className="space-y-8">
        {prompts.map((prompt) => (
          <div
            key={prompt.name}
            id={prompt.name}
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
                  data-testid={`github-link-${prompt.name}`}
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
                  onClick={() => toggleSchema(prompt.name)}
                  className="text-xs text-foreground/50 hover:text-foreground/70 flex items-center gap-1 transition-colors"
                >
                  <svg
                    className={`w-3 h-3 transition-transform ${expandedSchema.has(prompt.name) ? "rotate-90" : ""}`}
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
                {expandedSchema.has(prompt.name) && (
                  <pre className="mt-2 text-xs text-foreground/60 font-mono whitespace-pre-wrap bg-background rounded border border-border p-3 max-h-48 overflow-y-auto">
                    {JSON.stringify(prompt.output_schema, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {prompts.length === 0 && (
        <div className="text-center py-12 text-foreground/40 text-sm">
          No eval prompts available. The backend may not be running.
        </div>
      )}
    </div>
  );
}

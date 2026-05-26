"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  runHeadlessScenario,
  type PublicScenarioMeta,
} from "@/lib/api";

interface ScenarioCardProps {
  scenario: PublicScenarioMeta;
}

export function formatScenarioEstimate(
  scenario: Pick<
    PublicScenarioMeta,
    "expected_max_cost" | "expected_runtime_minutes"
  >,
): string {
  const minutes = scenario.expected_runtime_minutes;
  const cost = scenario.expected_max_cost;
  const minutesPart = minutes > 0 ? `≈ ${minutes} min` : "≈ — min";
  const costPart = cost >= 1
    ? `$${cost.toFixed(0)}`
    : cost > 0
      ? `$${cost.toFixed(2)}`
      : "$—";
  return `${minutesPart} / ${costPart}`;
}

export function buildRunHref(scenario: { filename: string }): string {
  return `/simulations/new?scenario=${encodeURIComponent(scenario.filename)}`;
}

export default function ScenarioCard({ scenario }: ScenarioCardProps) {
  const runHref = buildRunHref(scenario);
  const estimate = formatScenarioEstimate(scenario);
  const router = useRouter();
  const [headlessState, setHeadlessState] = useState<
    "idle" | "starting" | "error"
  >("idle");
  const [headlessError, setHeadlessError] = useState<string | null>(null);

  const targets = scenario.eval_targets ?? null;
  const primaryTargets = targets?.primary ?? [];
  const secondaryTargets = targets?.secondary ?? [];

  async function handleRunHeadless() {
    setHeadlessState("starting");
    setHeadlessError(null);
    try {
      const resp = await runHeadlessScenario({ scenario: scenario.filename });
      router.push(`/simulations/${resp.simulation_id}?queued=1`);
    } catch (err) {
      setHeadlessState("error");
      setHeadlessError(
        err instanceof Error ? err.message : "Failed to start headless run",
      );
    }
  }

  return (
    <article
      data-testid={`scenario-card-${scenario.filename}`}
      className="flex flex-col rounded border border-border bg-surface p-4 hover:border-neon-cyan/60 transition-colors"
    >
      <h3 className="font-pixel text-sm text-neon-cyan mb-2 leading-relaxed">
        {scenario.name}
      </h3>
      <p className="text-sm text-foreground/80 mb-3 flex-1">
        {scenario.description}
      </p>
      {scenario.agents.length > 0 && (
        <ul className="flex flex-wrap gap-1 mb-3" aria-label="Agents">
          {scenario.agents.map((agent) => (
            <li
              key={agent}
              className="rounded bg-surface-light px-2 py-0.5 text-xs text-foreground/70"
            >
              {agent}
            </li>
          ))}
        </ul>
      )}
      {(primaryTargets.length > 0 || secondaryTargets.length > 0) && (
        <div
          className="flex flex-wrap gap-1 mb-3"
          aria-label="Eval targets"
          data-testid="scenario-eval-targets"
        >
          {primaryTargets.map((cat) => (
            <span
              key={`p-${cat}`}
              className="rounded border border-neon-cyan/40 bg-neon-cyan/10 px-2 py-0.5 text-[10px] font-medium text-neon-cyan"
            >
              {cat}
            </span>
          ))}
          {secondaryTargets.map((cat) => (
            <span
              key={`s-${cat}`}
              className="rounded border border-border bg-surface-light px-2 py-0.5 text-[10px] text-foreground/70"
            >
              {cat}
            </span>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between text-xs text-foreground/60 mb-3">
        <span data-testid="scenario-estimate">{estimate}</span>
        {scenario.phase_count > 0 && <span>{scenario.phase_count} phases</span>}
      </div>
      <div className="flex flex-col gap-2">
        <Link
          href={runHref}
          className="inline-block rounded bg-neon-cyan/10 border border-neon-cyan/40 px-3 py-1.5 text-center text-xs text-neon-cyan hover:bg-neon-cyan/20 transition-colors"
        >
          Run scenario →
        </Link>
        <button
          type="button"
          onClick={handleRunHeadless}
          disabled={headlessState === "starting"}
          data-testid={`run-headless-${scenario.filename}`}
          className="inline-block rounded bg-neon-magenta/10 border border-neon-magenta/40 px-3 py-1.5 text-center text-xs text-neon-magenta hover:bg-neon-magenta/20 transition-colors disabled:opacity-50"
        >
          {headlessState === "starting" ? "Starting…" : "Run Headless"}
        </button>
        {headlessError && (
          <p
            role="alert"
            className="text-xs text-red-400"
            data-testid="run-headless-error"
          >
            {headlessError}
          </p>
        )}
      </div>
    </article>
  );
}

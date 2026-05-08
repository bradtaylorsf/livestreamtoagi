"use client";

import Link from "next/link";
import { useState } from "react";
import { formatDuration } from "@/components/simulation";

interface Props {
  config: Record<string, unknown>;
}

const EM_DASH = "—";
const PHASE_PREVIEW_LIMIT = 3;

export function formatBoolean(value: unknown): string {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return EM_DASH;
}

export function formatTimestamp(value: unknown): string {
  if (typeof value !== "string" || !value) return EM_DASH;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export function formatMaxCost(value: unknown): string {
  if (value == null || value === "") return EM_DASH;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `$${n.toFixed(2)}`;
}

export function formatNumber(value: unknown): string {
  if (value == null || value === "") return EM_DASH;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return String(n);
}

export function formatString(value: unknown): string {
  if (value == null || value === "") return EM_DASH;
  return String(value);
}

interface ClockState {
  start_time?: unknown;
  simulated_day?: unknown;
  current_simulated_time?: unknown;
  speed_multiplier?: unknown;
  elapsed_seconds?: unknown;
}

export function getClockState(config: Record<string, unknown>): ClockState {
  const cs = config.clock_state;
  if (cs && typeof cs === "object") {
    return cs as ClockState;
  }
  return {};
}

export function getAgents(config: Record<string, unknown>): string[] {
  const agents = config.agents;
  if (Array.isArray(agents)) {
    return agents.filter((a): a is string => typeof a === "string");
  }
  return [];
}

export function getPhaseNames(config: Record<string, unknown>): string[] {
  const phases = config.phase_names;
  if (Array.isArray(phases)) {
    return phases.filter((p): p is string => typeof p === "string");
  }
  return [];
}

function DefRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-baseline gap-1 sm:gap-3 py-1.5 border-b border-border/40 last:border-0">
      <dt className="text-xs text-foreground/50 sm:w-44 sm:flex-shrink-0">{label}</dt>
      <dd className="text-sm text-foreground/85 font-mono break-words">{children}</dd>
    </div>
  );
}

function GroupCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface-light p-4">
      <h4 className="text-sm font-medium text-foreground mb-3">{title}</h4>
      <dl>{children}</dl>
    </section>
  );
}

function AgentChip({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-surface border border-border text-xs font-mono text-foreground/80">
      {name}
    </span>
  );
}

function PhaseList({ phases }: { phases: string[] }) {
  const [expanded, setExpanded] = useState(false);
  if (phases.length === 0) return <span>{EM_DASH}</span>;

  const showAll = expanded || phases.length <= PHASE_PREVIEW_LIMIT;
  const visible = showAll ? phases : phases.slice(0, PHASE_PREVIEW_LIMIT);
  const remaining = phases.length - PHASE_PREVIEW_LIMIT;

  return (
    <div className="flex flex-col gap-1">
      <ol className="list-decimal list-inside space-y-0.5">
        {visible.map((p, i) => (
          <li key={`${p}-${i}`} className="text-sm text-foreground/85">
            {p}
          </li>
        ))}
      </ol>
      {phases.length > PHASE_PREVIEW_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="self-start text-xs text-foreground/60 hover:text-foreground transition-colors"
        >
          {expanded ? "Show less" : `Show all (${remaining} more)`}
        </button>
      )}
    </div>
  );
}

function SeedFileLink({ value }: { value: unknown }) {
  if (value == null || value === "") return <>{EM_DASH}</>;
  const seed = String(value);
  // Strip directory prefix and extension to derive scenario name
  const base = seed.split("/").pop() ?? seed;
  const name = base.replace(/\.(ya?ml|json)$/i, "");
  return (
    <Link
      href={`/scenarios/${encodeURIComponent(name)}`}
      className="text-foreground/85 hover:text-foreground underline decoration-dotted"
    >
      {seed}
    </Link>
  );
}

export default function ConfigViewer({ config }: Props) {
  const [open, setOpen] = useState(false);
  const agents = getAgents(config);
  const phases = getPhaseNames(config);
  const clock = getClockState(config);

  return (
    <div className="rounded-lg border border-border bg-surface">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-foreground/70 hover:text-foreground transition-colors"
      >
        <span>Configuration Snapshot</span>
        <svg
          className={`w-4 h-4 text-foreground/40 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3">
          <GroupCard title="Run config">
            <DefRow label="Mode">{formatString(config.mode)}</DefRow>
            <DefRow label="Name">{formatString(config.name)}</DefRow>
            <DefRow label="Speed">{formatString(config.speed)}</DefRow>
            <DefRow label="Dry run">{formatBoolean(config.dry_run)}</DefRow>
            <DefRow label="Max cost">{formatMaxCost(config.max_cost)}</DefRow>
            <DefRow label="Management shadow">{formatBoolean(config.management_shadow)}</DefRow>
          </GroupCard>

          <GroupCard title="Agents">
            <DefRow label={`Agents (${agents.length})`}>
              {agents.length === 0 ? (
                EM_DASH
              ) : (
                <span className="flex flex-wrap gap-1.5">
                  {agents.map((a) => (
                    <AgentChip key={a} name={a} />
                  ))}
                </span>
              )}
            </DefRow>
          </GroupCard>

          <GroupCard title="Scenario">
            <DefRow label="Seed file">
              <SeedFileLink value={config.seed_file} />
            </DefRow>
            <DefRow label="Phase count">{formatNumber(config.phase_count)}</DefRow>
            <DefRow label="Phases">
              <PhaseList phases={phases} />
            </DefRow>
          </GroupCard>

          <GroupCard title="Clock">
            <DefRow label="Start time">{formatTimestamp(clock.start_time)}</DefRow>
            <DefRow label="Simulated day">{formatNumber(clock.simulated_day)}</DefRow>
            <DefRow label="Current simulated time">
              {formatTimestamp(clock.current_simulated_time)}
            </DefRow>
            <DefRow label="Speed multiplier">
              {clock.speed_multiplier == null
                ? EM_DASH
                : `${formatNumber(clock.speed_multiplier)}×`}
            </DefRow>
            <DefRow label="Elapsed">
              {clock.elapsed_seconds == null
                ? EM_DASH
                : formatDuration(String(clock.elapsed_seconds))}
            </DefRow>
          </GroupCard>
        </div>
      )}
    </div>
  );
}

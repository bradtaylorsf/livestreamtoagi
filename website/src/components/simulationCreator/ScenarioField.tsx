"use client";

import { useMemo, useState } from "react";
import type { PublicScenarioMeta } from "@/lib/api";

interface ScenarioFieldProps {
  scenarios: PublicScenarioMeta[];
  value: string;
  onChange: (filename: string) => void;
}

export function filterScenarios(
  scenarios: PublicScenarioMeta[],
  query: string,
): PublicScenarioMeta[] {
  const q = query.trim().toLowerCase();
  if (!q) return scenarios;
  return scenarios.filter(
    (s) =>
      s.name.toLowerCase().includes(q) ||
      s.description.toLowerCase().includes(q) ||
      s.filename.toLowerCase().includes(q),
  );
}

export default function ScenarioField({
  scenarios,
  value,
  onChange,
}: ScenarioFieldProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => filterScenarios(scenarios, query),
    [scenarios, query],
  );
  const selected = scenarios.find((s) => s.filename === value);

  return (
    <fieldset className="space-y-2">
      <legend className="font-pixel text-xs text-neon-cyan">SCENARIO</legend>
      <input
        type="search"
        placeholder="Search scenarios…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
        aria-label="Search scenarios"
        data-testid="scenario-search"
      />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded border border-border bg-background px-3 py-2 text-sm text-foreground"
        aria-label="Scenario"
        data-testid="scenario-select"
      >
        {filtered.length === 0 && (
          <option value="" disabled>
            No scenarios match
          </option>
        )}
        {filtered.map((s) => (
          <option key={s.filename} value={s.filename}>
            {s.name}
          </option>
        ))}
      </select>
      {selected && (
        <div
          className="rounded border border-border bg-surface p-3 text-xs text-foreground/70"
          data-testid="scenario-preview"
        >
          <p className="mb-2 leading-relaxed">{selected.description}</p>
          <div className="flex flex-wrap gap-1">
            {selected.agents.map((a) => (
              <span
                key={a}
                className="rounded bg-surface-light px-2 py-0.5 text-foreground/80"
              >
                {a}
              </span>
            ))}
          </div>
          <p className="mt-2 text-foreground/50">
            ≈ {selected.expected_runtime_minutes} min · ${selected.expected_max_cost.toFixed(2)} · {selected.phase_count} phases
          </p>
        </div>
      )}
    </fieldset>
  );
}

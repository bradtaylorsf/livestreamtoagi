"use client";

import { useEffect, useState } from "react";
import { getSimulations, type PublicSimulation } from "@/lib/api";

interface SimulationPickerProps {
  value: string;
  onChange: (id: string) => void;
  label?: string;
  includeAll?: boolean;
  allLabel?: string;
  className?: string;
  id?: string;
  disabled?: boolean;
}

const STATUS_PRIORITY: Record<string, number> = {
  running: 0,
  completed: 1,
  failed: 2,
  cancelled: 3,
};

export function sortSimulations(sims: PublicSimulation[]): PublicSimulation[] {
  return [...sims].sort((a, b) => {
    const pa = STATUS_PRIORITY[a.status] ?? 99;
    const pb = STATUS_PRIORITY[b.status] ?? 99;
    if (pa !== pb) return pa - pb;
    const ta = a.started_at ? Date.parse(a.started_at) : 0;
    const tb = b.started_at ? Date.parse(b.started_at) : 0;
    return tb - ta;
  });
}

export default function SimulationPicker({
  value,
  onChange,
  label,
  includeAll = true,
  allLabel = "All simulations",
  className,
  id,
  disabled,
}: SimulationPickerProps) {
  const [simulations, setSimulations] = useState<PublicSimulation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    getSimulations({ limit: 100 })
      .then((data) => {
        if (cancelled) return;
        setSimulations(sortSimulations(data.items));
      })
      .catch(() => {
        if (cancelled) return;
        setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const baseSelectClass =
    "rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground disabled:opacity-50";

  return (
    <div className={className}>
      {label && (
        <label
          htmlFor={id}
          className="block text-xs uppercase tracking-wide text-foreground/50 mb-1"
        >
          {label}
        </label>
      )}
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || (loading && simulations.length === 0)}
        className={baseSelectClass}
        aria-label={label ?? "Filter by simulation"}
        data-testid="simulation-picker"
      >
        {includeAll && <option value="">{allLabel}</option>}
        {loading && simulations.length === 0 && (
          <option value="" disabled>
            Loading simulations…
          </option>
        )}
        {error && simulations.length === 0 && !loading && (
          <option value="" disabled>
            Could not load simulations
          </option>
        )}
        {simulations.map((sim) => (
          <option key={sim.id} value={sim.id}>
            {sim.name} ({sim.status})
          </option>
        ))}
      </select>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { fetchSimulations } from "@/lib/admin-api";
import type { Simulation } from "@/types/admin";

interface Props {
  value: string;
  onChange: (simulationId: string) => void;
  className?: string;
  includeAllOption?: boolean;
}

export default function SimulationFilterSelect({
  value,
  onChange,
  className,
  includeAllOption = true,
}: Props) {
  const [sims, setSims] = useState<Simulation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchSimulations()
      .then((res) => {
        if (cancelled) return;
        const sorted = [...res.items].sort((a, b) => {
          if (a.is_live !== b.is_live) return a.is_live ? -1 : 1;
          const at = a.created_at ?? "";
          const bt = b.created_at ?? "";
          return bt.localeCompare(at);
        });
        setSims(sorted);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={loading}
      className={
        className ??
        "rounded border border-border bg-surface-light px-3 py-1.5 text-sm text-foreground disabled:opacity-50"
      }
    >
      {includeAllOption && (
        <option value="">All simulations</option>
      )}
      {sims.map((sim) => (
        <option key={sim.id} value={sim.id}>
          {sim.is_live ? "● Live" : sim.name}
          {sim.is_live ? "" : ` (${sim.status})`}
        </option>
      ))}
    </select>
  );
}

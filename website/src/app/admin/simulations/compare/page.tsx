"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { compareSimulations, fetchSimulations } from "@/lib/admin-api";
import type { ComparisonResult, MetricComparison, Simulation } from "@/types/admin";

function formatMetricValue(val: unknown): string {
  if (val === null || val === undefined) return "—";
  const num = Number(val);
  if (isNaN(num)) return String(val);
  if (String(val).includes(".") && Math.abs(num) < 100) return num.toFixed(4);
  return num.toLocaleString();
}

// ── Cost Chart ────────────────────────────────────────────────

function ComparisonChart({
  dailyCosts,
}: {
  dailyCosts: ComparisonResult["daily_costs"];
}) {
  const allDays = Array.from(
    new Set([
      ...dailyCosts.run_a.map((d) => d.day),
      ...dailyCosts.run_b.map((d) => d.day),
    ]),
  ).sort();

  if (allDays.length === 0) {
    return (
      <p className="text-sm text-foreground/40 italic">No cost data available.</p>
    );
  }

  const costsA = allDays.map((day) => {
    const found = dailyCosts.run_a.find((d) => d.day === day);
    return found ? parseFloat(found.cost) : 0;
  });
  const costsB = allDays.map((day) => {
    const found = dailyCosts.run_b.find((d) => d.day === day);
    return found ? parseFloat(found.cost) : 0;
  });

  const maxCost = Math.max(...costsA, ...costsB, 0.0001);

  const WIDTH = 600;
  const HEIGHT = 160;
  const PAD_LEFT = 56;
  const PAD_RIGHT = 16;
  const PAD_TOP = 12;
  const PAD_BOTTOM = 32;
  const chartW = WIDTH - PAD_LEFT - PAD_RIGHT;
  const chartH = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const xPos = (i: number) =>
    PAD_LEFT + (allDays.length > 1 ? (i / (allDays.length - 1)) * chartW : chartW / 2);
  const yPos = (cost: number) =>
    PAD_TOP + chartH - (cost / maxCost) * chartH;

  const polyA = costsA.map((c, i) => `${xPos(i)},${yPos(c)}`).join(" ");
  const polyB = costsB.map((c, i) => `${xPos(i)},${yPos(c)}`).join(" ");

  // Y-axis ticks
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => ({
    value: (t * maxCost).toFixed(4),
    y: PAD_TOP + chartH - t * chartH,
  }));

  // X-axis labels — show up to 6 evenly spaced
  const labelStep = Math.max(1, Math.floor(allDays.length / 6));
  const xLabels = allDays
    .map((day, i) => ({ day, i }))
    .filter(({ i }) => i % labelStep === 0 || i === allDays.length - 1);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full max-w-2xl"
        style={{ minWidth: "360px" }}
      >
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <line
            key={tick.y}
            x1={PAD_LEFT}
            y1={tick.y}
            x2={WIDTH - PAD_RIGHT}
            y2={tick.y}
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="1"
          />
        ))}

        {/* Y axis labels */}
        {yTicks.map((tick) => (
          <text
            key={tick.y}
            x={PAD_LEFT - 4}
            y={tick.y + 4}
            textAnchor="end"
            fontSize="9"
            fill="rgba(255,255,255,0.35)"
          >
            ${tick.value}
          </text>
        ))}

        {/* X axis labels */}
        {xLabels.map(({ day, i }) => (
          <text
            key={day}
            x={xPos(i)}
            y={HEIGHT - 4}
            textAnchor="middle"
            fontSize="8"
            fill="rgba(255,255,255,0.35)"
          >
            {day.slice(5)}
          </text>
        ))}

        {/* Run B line (yellow) */}
        {allDays.length > 1 && (
          <polyline
            points={polyB}
            fill="none"
            stroke="#facc15"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        )}
        {allDays.length === 1 && (
          <circle cx={xPos(0)} cy={yPos(costsB[0])} r="3" fill="#facc15" />
        )}

        {/* Run A line (neon-cyan) */}
        {allDays.length > 1 && (
          <polyline
            points={polyA}
            fill="none"
            stroke="#00e5ff"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        )}
        {allDays.length === 1 && (
          <circle cx={xPos(0)} cy={yPos(costsA[0])} r="3" fill="#00e5ff" />
        )}

        {/* Axes */}
        <line
          x1={PAD_LEFT}
          y1={PAD_TOP}
          x2={PAD_LEFT}
          y2={PAD_TOP + chartH}
          stroke="rgba(255,255,255,0.15)"
          strokeWidth="1"
        />
        <line
          x1={PAD_LEFT}
          y1={PAD_TOP + chartH}
          x2={WIDTH - PAD_RIGHT}
          y2={PAD_TOP + chartH}
          stroke="rgba(255,255,255,0.15)"
          strokeWidth="1"
        />
      </svg>

      {/* Legend */}
      <div className="flex gap-6 mt-2">
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-0.5 w-6 rounded"
            style={{ background: "#00e5ff" }}
          />
          <span className="text-xs text-foreground/60">Run A</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="inline-block h-0.5 w-6 rounded"
            style={{ background: "#facc15" }}
          />
          <span className="text-xs text-foreground/60">Run B</span>
        </div>
      </div>
    </div>
  );
}

// ── Metric Cards ──────────────────────────────────────────────

function ComparisonMetrics({ metrics }: { metrics: MetricComparison[] }) {
  if (metrics.length === 0) {
    return <p className="text-sm text-foreground/40 italic">No metrics available.</p>;
  }

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
      {metrics.map((m) => (
        <div
          key={m.metric}
          className="rounded-lg border border-border bg-surface p-4"
        >
          <p className="text-xs text-foreground/50 mb-2">
            {m.metric.replace(/_/g, " ")}
          </p>
          <div className="flex items-baseline justify-between">
            <div
              className={`text-lg font-mono ${
                m.better_run === "a" ? "text-green-400" : "text-foreground"
              }`}
            >
              {formatMetricValue(m.run_a)}
            </div>
            <div className="text-xs text-foreground/40">vs</div>
            <div
              className={`text-lg font-mono ${
                m.better_run === "b" ? "text-green-400" : "text-foreground"
              }`}
            >
              {formatMetricValue(m.run_b)}
            </div>
          </div>
          <div
            className={`mt-1 text-xs font-mono ${
              Number(m.delta) > 0
                ? "text-green-400"
                : Number(m.delta) < 0
                  ? "text-red-400"
                  : "text-foreground/40"
            }`}
          >
            {Number(m.delta) > 0 ? "+" : ""}
            {formatMetricValue(m.delta)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────

export default function CompareSimulationsPage() {
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [simsLoading, setSimsLoading] = useState(true);
  const [simA, setSimA] = useState("");
  const [simB, setSimB] = useState("");
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSimulations()
      .then((res) => setSimulations(res.items))
      .catch(() => {/* non-fatal */})
      .finally(() => setSimsLoading(false));
  }, []);

  const handleCompare = useCallback(async () => {
    if (!simA || !simB) return;
    setComparing(true);
    setError(null);
    setComparison(null);
    try {
      const result = await compareSimulations(simA, simB);
      setComparison(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed");
    } finally {
      setComparing(false);
    }
  }, [simA, simB]);

  return (
    <div className="max-w-6xl space-y-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-foreground/50">
        <Link href="/admin/simulations" className="hover:text-neon-cyan transition-colors">
          Simulations
        </Link>
        <span>/</span>
        <span className="text-foreground/70">Compare</span>
      </div>

      <div className="flex items-center justify-between">
        <h1 className="font-pixel text-lg text-foreground">Compare Simulations</h1>
      </div>

      {/* Selectors */}
      <div className="rounded-lg border border-border bg-surface p-5 space-y-4">
        {simsLoading ? (
          <p className="text-sm text-foreground/50">Loading simulations...</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-foreground/50 mb-1 block">
                  Simulation A
                </label>
                <select
                  value={simA}
                  onChange={(e) => setSimA(e.target.value)}
                  className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
                >
                  <option value="">Select simulation...</option>
                  {simulations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.status})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-foreground/50 mb-1 block">
                  Simulation B
                </label>
                <select
                  value={simB}
                  onChange={(e) => setSimB(e.target.value)}
                  className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
                >
                  <option value="">Select simulation...</option>
                  {simulations.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.status})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button
              onClick={handleCompare}
              disabled={!simA || !simB || comparing || simA === simB}
              className="rounded border border-neon-cyan px-3 py-1.5 text-xs text-neon-cyan hover:bg-neon-cyan/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {comparing ? "Comparing..." : "Compare"}
            </button>
          </>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
      )}

      {/* Results */}
      {comparing && (
        <p className="text-sm text-foreground/50">Loading comparison...</p>
      )}

      {comparison && !comparing && (
        <>
          {/* Run labels */}
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-xs text-foreground/40 mb-1">Run A</p>
              <p className="font-mono text-sm text-neon-cyan">
                {(comparison.run_a.name as string | undefined) ??
                  (comparison.run_a.simulation_id as string | undefined) ??
                  simA}
              </p>
              {comparison.run_a.status != null && (
                <p className="text-xs text-foreground/50 mt-1">
                  Status: {String(comparison.run_a.status)}
                </p>
              )}
            </div>
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="text-xs text-foreground/40 mb-1">Run B</p>
              <p className="font-mono text-sm text-yellow-400">
                {(comparison.run_b.name as string | undefined) ??
                  (comparison.run_b.simulation_id as string | undefined) ??
                  simB}
              </p>
              {comparison.run_b.status != null && (
                <p className="text-xs text-foreground/50 mt-1">
                  Status: {String(comparison.run_b.status)}
                </p>
              )}
            </div>
          </div>

          {/* Metric cards */}
          <div className="space-y-3">
            <h2 className="font-pixel text-sm text-foreground/80">Metrics</h2>
            <ComparisonMetrics metrics={comparison.metrics} />
          </div>

          {/* Cost chart */}
          <div className="rounded-lg border border-border bg-surface p-5 space-y-3">
            <h2 className="font-pixel text-sm text-foreground/80">Daily Cost Overlay</h2>
            <ComparisonChart dailyCosts={comparison.daily_costs} />
          </div>
        </>
      )}
    </div>
  );
}

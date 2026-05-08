"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import {
  getSimulationEnergyTimeline,
  type EnergyTimelinePoint,
} from "@/lib/api";
import { getAgentData } from "@/lib/agent-data";
import { SkeletonBlock } from "@/components/Skeleton";
import { useDelayedFlag } from "@/lib/useDelayedFlag";
import { buildChartRows, fallbackColor } from "./energy-chart";

interface EnergyTabProps {
  simulationId: string;
}

function colorFor(agentId: string, idx: number): string {
  const data = getAgentData(agentId);
  if (data?.color) return data.color;
  return fallbackColor(idx);
}

export default function EnergyTab({ simulationId }: EnergyTabProps) {
  const [data, setData] = useState<Record<string, EnergyTimelinePoint[]> | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const showSkeleton = useDelayedFlag(loading);

  useEffect(() => {
    let cancelled = false;
    getSimulationEnergyTimeline(simulationId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load energy timeline",
        );
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [simulationId]);

  const { rows, agents } = useMemo(
    () => (data ? buildChartRows(data) : { rows: [], agents: [] }),
    [data],
  );

  if (error) {
    return (
      <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm">
        {error}
      </div>
    );
  }

  if (loading) {
    return showSkeleton ? (
      <SkeletonBlock width="w-full" height="h-72" />
    ) : null;
  }

  if (rows.length === 0) {
    return (
      <p
        className="text-sm text-foreground/50"
        data-testid="energy-empty"
      >
        No energy data available for this simulation.
      </p>
    );
  }

  return (
    <div className="space-y-4" data-testid="energy-tab">
      <p className="text-xs text-foreground/40">
        Conversation energy by agent across {rows.length} turns
      </p>
      <div className="h-72 rounded border border-border bg-surface p-3">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={rows}
            margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
            <XAxis
              dataKey="turn"
              stroke="#666"
              tick={{ fontSize: 11 }}
              label={{
                value: "Turn",
                position: "insideBottomRight",
                offset: -4,
                fill: "#666",
                fontSize: 11,
              }}
            />
            <YAxis
              domain={[0, 1]}
              stroke="#666"
              tick={{ fontSize: 11 }}
              label={{
                value: "Energy",
                angle: -90,
                position: "insideLeft",
                fill: "#666",
                fontSize: 11,
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e1e1e",
                border: "1px solid #2a2a2a",
                borderRadius: "4px",
                fontSize: "11px",
              }}
              formatter={(value, name) => [
                Number(value).toFixed(2),
                String(name),
              ]}
              labelFormatter={(label) => `Turn ${label}`}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {agents.map((agent, idx) => (
              <Line
                key={agent}
                type="monotone"
                dataKey={agent}
                stroke={colorFor(agent, idx)}
                strokeWidth={1.5}
                dot={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}


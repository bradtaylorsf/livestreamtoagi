"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface EnergyDataPoint {
  turn: number;
  energy: number;
  label?: string;
}

interface EnergyGraphProps {
  energyHistory: Record<string, unknown>[];
  initialEnergy: number;
  finalEnergy: number | null;
  turnCount: number;
}

export default function EnergyGraph({
  energyHistory,
  initialEnergy,
  finalEnergy,
  turnCount,
}: EnergyGraphProps) {
  // Build data points from energy history
  const data: EnergyDataPoint[] = [{ turn: 0, energy: initialEnergy }];

  for (const entry of energyHistory) {
    const turnNum =
      typeof entry.turn_number === "number"
        ? entry.turn_number
        : typeof entry.turn === "number"
          ? entry.turn
          : data.length;

    const changes = entry.changes as Record<string, unknown> | undefined;
    let energy: number | undefined;

    if (typeof entry.energy === "number") {
      energy = entry.energy;
    } else if (
      changes &&
      typeof (changes as Record<string, number>).new_energy === "number"
    ) {
      energy = (changes as Record<string, number>).new_energy;
    } else if (typeof entry.conversation_energy === "number") {
      energy = entry.conversation_energy as number;
    }

    if (energy !== undefined) {
      const label = changes
        ? (changes as Record<string, string>).reason || undefined
        : undefined;
      data.push({ turn: turnNum, energy, label });
    }
  }

  // Add final point if available
  if (finalEnergy !== null && turnCount > 0) {
    const lastTurn = data[data.length - 1]?.turn ?? 0;
    if (lastTurn < turnCount) {
      data.push({ turn: turnCount, energy: finalEnergy });
    }
  }

  // Find boost/drain annotations
  const annotations = data.filter((d) => d.label);

  if (data.length < 2) {
    return (
      <div className="rounded-lg border border-border bg-surface p-4 text-xs text-foreground/40 text-center">
        No energy data available
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-medium text-foreground/60">
          Energy Level
        </h3>
        <div className="text-[10px] text-foreground/40">
          {initialEnergy.toFixed(2)} → {(finalEnergy ?? data[data.length - 1]?.energy ?? 0).toFixed(2)}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <LineChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis
            dataKey="turn"
            tick={{ fontSize: 10, fill: "rgba(255,255,255,0.3)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            label={{
              value: "Turn",
              position: "insideBottom",
              offset: -2,
              style: { fontSize: 10, fill: "rgba(255,255,255,0.3)" },
            }}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fontSize: 10, fill: "rgba(255,255,255,0.3)" }}
            axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
            width={30}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "rgba(20,20,30,0.95)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "6px",
              fontSize: "11px",
              color: "rgba(255,255,255,0.7)",
            }}
            formatter={(value) => [Number(value).toFixed(3), "Energy"]}
            labelFormatter={(label) => `Turn ${label}`}
          />
          <Line
            type="monotone"
            dataKey="energy"
            stroke="#6366f1"
            strokeWidth={2}
            dot={{ r: 2, fill: "#6366f1" }}
            activeDot={{ r: 4 }}
          />
          {annotations.map((a, i) => (
            <ReferenceDot
              key={i}
              x={a.turn}
              y={a.energy}
              r={4}
              fill="#f59e0b"
              stroke="#f59e0b"
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

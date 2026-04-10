"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface EnergyDataPoint {
  turn: number;
  energy: number;
}

interface EnergySparklineProps {
  data: EnergyDataPoint[];
  currentTurn: number;
}

export default function EnergySparkline({
  data,
  currentTurn,
}: EnergySparklineProps) {
  if (data.length === 0) return null;

  return (
    <div className="rounded border border-border bg-surface p-3">
      <div className="text-xs text-foreground/40 mb-2">Conversation Energy</div>
      <div className="h-16">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 2, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="energyGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#00f0ff" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#00f0ff" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <XAxis dataKey="turn" hide />
            <YAxis domain={[0, 1]} hide />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1e1e1e",
                border: "1px solid #2a2a2a",
                borderRadius: "4px",
                fontSize: "11px",
                color: "#00f0ff",
              }}
              formatter={(value) => [Number(value).toFixed(2), "Energy"]}
              labelFormatter={(label) => `Turn ${label}`}
            />
            <Area
              type="monotone"
              dataKey="energy"
              stroke="#00f0ff"
              strokeWidth={1.5}
              fill="url(#energyGradient)"
              dot={false}
              activeDot={{
                r: 3,
                fill: "#00f0ff",
                stroke: "#141414",
                strokeWidth: 1,
              }}
            />
            {/* Current turn indicator line */}
            {currentTurn > 0 && currentTurn <= data.length && (
              <Area
                type="monotone"
                dataKey={() => null}
                stroke="none"
                fill="none"
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

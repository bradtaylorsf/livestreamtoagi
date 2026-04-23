"use client";

import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { getSimulationCosts } from "@/lib/api";
import type { SimulationCostResponse } from "@/lib/api";

interface Props {
  simulationId: string;
}

export default function CostChart({ simulationId }: Props) {
  const [costs, setCosts] = useState<SimulationCostResponse | null>(null);

  useEffect(() => {
    getSimulationCosts(simulationId).then(setCosts).catch(() => setCosts(null));
  }, [simulationId]);

  if (!costs || costs.by_agent.length === 0) {
    return (
      <p className="text-sm text-foreground/50">No cost data available.</p>
    );
  }

  const chartData = costs.by_agent.map((entry) => ({
    agent: entry.agent_id,
    cost: parseFloat(entry.total || "0"),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
          <XAxis
            dataKey="agent"
            tick={{ fill: "#999", fontSize: 11 }}
            stroke="#2a2a2a"
          />
          <YAxis
            tick={{ fill: "#999", fontSize: 11 }}
            stroke="#2a2a2a"
            tickFormatter={(v: number) => `$${v.toFixed(3)}`}
          />
          <Tooltip
            contentStyle={{
              background: "#1e1e1e",
              border: "1px solid #2a2a2a",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value) => [`$${Number(value).toFixed(4)}`, "Cost"]}
          />
          <Bar
            dataKey="cost"
            fill="#00f0ff"
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

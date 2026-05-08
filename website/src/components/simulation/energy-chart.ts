import type { EnergyTimelinePoint } from "@/lib/api";

export interface ChartRow {
  turn: number;
  [agentId: string]: number;
}

export function buildChartRows(
  data: Record<string, EnergyTimelinePoint[]>,
): { rows: ChartRow[]; agents: string[] } {
  const agents = Object.keys(data).sort();
  const turnMap = new Map<number, ChartRow>();

  for (const agent of agents) {
    for (const point of data[agent] ?? []) {
      const turn = point.turn;
      const row = turnMap.get(turn) ?? { turn };
      row[agent] = point.energy;
      turnMap.set(turn, row);
    }
  }

  const rows = Array.from(turnMap.values()).sort((a, b) => a.turn - b.turn);
  return { rows, agents };
}

const FALLBACK_PALETTE = [
  "#00f0ff",
  "#a78bfa",
  "#f472b6",
  "#facc15",
  "#34d399",
  "#fb923c",
  "#60a5fa",
  "#f87171",
];

export function fallbackColor(idx: number): string {
  return FALLBACK_PALETTE[idx % FALLBACK_PALETTE.length];
}

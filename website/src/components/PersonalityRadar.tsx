"use client";

import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
} from "recharts";

interface Traits {
  chattiness: number;
  initiative: number;
  creativity: number;
  technical: number;
  emotional: number;
}

const TRAIT_LABELS: Record<keyof Traits, string> = {
  chattiness: "Chattiness",
  initiative: "Initiative",
  creativity: "Creativity",
  technical: "Technical",
  emotional: "Emotional",
};

interface Props {
  traits: Traits;
  color: string;
}

export default function PersonalityRadar({ traits, color }: Props) {
  const data = Object.entries(TRAIT_LABELS).map(([key, label]) => ({
    trait: label,
    value: traits[key as keyof Traits] ?? 0,
  }));

  return (
    <div style={{ height: 250 }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
          <PolarGrid stroke="#2a2a2a" />
          <PolarAngleAxis
            dataKey="trait"
            tick={{ fill: "#999", fontSize: 11 }}
          />
          <PolarRadiusAxis
            domain={[0, 1]}
            tick={false}
            axisLine={false}
            tickCount={5}
          />
          <Radar
            dataKey="value"
            stroke={color}
            fill={color}
            fillOpacity={0.2}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

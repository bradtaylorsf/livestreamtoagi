"use client";

import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
} from "recharts";
import type { PersonalityTraits } from "@/types/admin";

const TRAIT_LABELS: Record<keyof PersonalityTraits, string> = {
  chattiness: "Chattiness",
  initiative: "Initiative",
  interrupt_tendency: "Interrupt",
  eavesdrop_tendency: "Eavesdrop",
  closing_weight: "Closing",
};

interface Props {
  traits: PersonalityTraits;
  size?: "sm" | "lg";
}

export default function PersonalityChart({ traits, size = "lg" }: Props) {
  const data = Object.entries(TRAIT_LABELS).map(([key, label]) => ({
    trait: label,
    value: traits[key as keyof PersonalityTraits] ?? 0,
  }));

  const height = size === "sm" ? 120 : 250;

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
          <PolarGrid stroke="#2a2a2a" />
          <PolarAngleAxis
            dataKey="trait"
            tick={{ fill: "#999", fontSize: size === "sm" ? 9 : 11 }}
          />
          <Radar
            dataKey="value"
            stroke="#00f0ff"
            fill="#00f0ff"
            fillOpacity={0.2}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}

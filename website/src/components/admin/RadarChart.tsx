"use client";

interface RadarChartProps {
  scores: Record<string, number>;
  size?: number;
}

export default function RadarChart({ scores, size = 200 }: RadarChartProps) {
  const categories = Object.keys(scores);
  const n = categories.length;
  if (n < 3) return null;

  const cx = size / 2;
  const cy = size / 2;
  const r = size * 0.38;
  const angleStep = (2 * Math.PI) / n;

  // Grid circles
  const gridLevels = [0.25, 0.5, 0.75, 1.0];

  // Calculate points for each score
  const points = categories.map((cat, i) => {
    const angle = -Math.PI / 2 + i * angleStep;
    const value = (scores[cat] ?? 0) / 100;
    return {
      x: cx + r * value * Math.cos(angle),
      y: cy + r * value * Math.sin(angle),
      labelX: cx + (r + 18) * Math.cos(angle),
      labelY: cy + (r + 18) * Math.sin(angle),
      category: cat,
    };
  });

  const polygon = points.map((p) => `${p.x},${p.y}`).join(" ");

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="mx-auto"
    >
      {/* Grid circles */}
      {gridLevels.map((level) => (
        <polygon
          key={level}
          points={categories
            .map((_, i) => {
              const angle = -Math.PI / 2 + i * angleStep;
              return `${cx + r * level * Math.cos(angle)},${cy + r * level * Math.sin(angle)}`;
            })
            .join(" ")}
          fill="none"
          stroke="currentColor"
          strokeOpacity={0.1}
          strokeWidth={1}
        />
      ))}

      {/* Axis lines */}
      {categories.map((_, i) => {
        const angle = -Math.PI / 2 + i * angleStep;
        return (
          <line
            key={i}
            x1={cx}
            y1={cy}
            x2={cx + r * Math.cos(angle)}
            y2={cy + r * Math.sin(angle)}
            stroke="currentColor"
            strokeOpacity={0.1}
            strokeWidth={1}
          />
        );
      })}

      {/* Score polygon */}
      <polygon
        points={polygon}
        fill="rgba(0, 255, 255, 0.15)"
        stroke="rgb(0, 255, 255)"
        strokeWidth={2}
      />

      {/* Score dots */}
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="rgb(0, 255, 255)" />
      ))}

      {/* Labels */}
      {points.map((p, i) => (
        <text
          key={i}
          x={p.labelX}
          y={p.labelY}
          textAnchor="middle"
          dominantBaseline="middle"
          className="fill-foreground/60 text-[9px]"
        >
          {p.category.replace(/_/g, " ")}
        </text>
      ))}
    </svg>
  );
}

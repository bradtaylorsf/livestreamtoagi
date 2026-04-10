interface Props {
  agentId: string;
}

// TODO: Fetch real stats from API (#61)
const PLACEHOLDER_STATS = [
  { label: "Messages", value: "—" },
  { label: "Conversations", value: "—" },
  { label: "Artifacts", value: "—" },
  { label: "Cost", value: "—" },
];

export default function AgentStats({ agentId: _agentId }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {PLACEHOLDER_STATS.map((stat) => (
        <div
          key={stat.label}
          className="rounded border border-border bg-surface p-3 text-center"
        >
          <div className="font-pixel text-sm text-neon-cyan">{stat.value}</div>
          <div className="text-xs text-foreground/40 mt-1">{stat.label}</div>
        </div>
      ))}
    </div>
  );
}

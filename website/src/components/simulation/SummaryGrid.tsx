import SummaryCard from "./SummaryCard";

interface SummaryGridProps {
  total_conversations: number;
  total_turns: number;
  total_tokens: number;
  total_cost: string;
  total_artifacts: number;
  total_management_flags: number;
}

export default function SummaryGrid(props: SummaryGridProps) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
      <SummaryCard label="Conversations" value={props.total_conversations} />
      <SummaryCard label="Turns" value={props.total_turns} />
      <SummaryCard label="Tokens" value={props.total_tokens.toLocaleString()} />
      <SummaryCard
        label="Cost"
        value={`$${parseFloat(props.total_cost || "0").toFixed(4)}`}
      />
      <SummaryCard label="Artifacts" value={props.total_artifacts} />
      <SummaryCard
        label="Management Flags"
        value={props.total_management_flags}
      />
    </div>
  );
}

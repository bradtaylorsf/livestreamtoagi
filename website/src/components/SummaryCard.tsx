export default function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-light p-4">
      <p className="text-xs text-foreground/50 mb-1">{label}</p>
      <p className="text-xl font-mono text-foreground">{value}</p>
    </div>
  );
}

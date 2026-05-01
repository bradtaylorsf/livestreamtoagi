import type { SimulationStatus } from "@/types/admin";

const STATUS_STYLES: Record<SimulationStatus, string> = {
  running: "bg-neon-green/20 text-neon-green border-neon-green/40",
  completed: "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40",
  failed: "bg-red-500/20 text-red-400 border-red-500/40",
  cancelled: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
};

export default function StatusBadge({ status }: { status: SimulationStatus }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status] ?? "bg-surface-light text-foreground/60 border-border"}`}
    >
      {status}
    </span>
  );
}

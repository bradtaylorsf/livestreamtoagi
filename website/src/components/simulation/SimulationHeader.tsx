import Link from "next/link";
import HeadlessBadge from "@/components/HeadlessBadge";
import { formatDuration } from "./formatDuration";

const STATUS_STYLES: Record<string, string> = {
  running: "bg-neon-green/20 text-neon-green border-neon-green/40",
  completed: "bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40",
  failed: "bg-red-500/20 text-red-400 border-red-500/40",
  cancelled: "bg-surface-light text-foreground/60 border-border",
};

interface SimulationHeaderProps {
  name: string;
  status: string;
  description: string | null;
  started_at: string | null;
  completed_at: string | null;
  real_duration: string | null;
  simulated_duration: string | null;
  breadcrumbHref: string;
  config?: Record<string, unknown> | null;
}

export default function SimulationHeader({
  name,
  status,
  description,
  started_at,
  completed_at,
  real_duration,
  simulated_duration,
  breadcrumbHref,
  config,
}: SimulationHeaderProps) {
  return (
    <>
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href={breadcrumbHref} className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <span className="text-foreground/60">{name}</span>
      </div>

      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="font-pixel text-lg text-neon-cyan">{name}</h1>
          <span
            className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status] ?? "bg-surface-light text-foreground/60 border-border"}`}
          >
            {status}
          </span>
          <HeadlessBadge config={config} />
        </div>
        {description && (
          <p className="text-sm text-foreground/60">{description}</p>
        )}
        <div className="flex gap-4 mt-2 text-xs text-foreground/40">
          {started_at && (
            <span>Started: {new Date(started_at).toLocaleString()}</span>
          )}
          {completed_at && (
            <span>Completed: {new Date(completed_at).toLocaleString()}</span>
          )}
          <span>Real: {formatDuration(real_duration)}</span>
          <span>Simulated: {formatDuration(simulated_duration)}</span>
        </div>
      </div>
    </>
  );
}

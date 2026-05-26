interface HeadlessBadgeProps {
  config?: Record<string, unknown> | null;
  className?: string;
}

/**
 * Renders when a simulation's config marks `headless: true` (issue #860).
 */
export default function HeadlessBadge({ config, className }: HeadlessBadgeProps) {
  if (!config || config.headless !== true) {
    return null;
  }
  return (
    <span
      data-testid="headless-badge"
      className={
        "inline-flex items-center rounded border border-neon-magenta/40 bg-neon-magenta/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-neon-magenta " +
        (className ?? "")
      }
      title="Headless run — no Minecraft / TTS"
    >
      Headless
    </span>
  );
}

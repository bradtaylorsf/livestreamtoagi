"use client";

interface ManagementFlagProps {
  wasFiltered: boolean;
  details?: string;
}

export default function ManagementFlag({
  wasFiltered,
  details,
}: ManagementFlagProps) {
  if (!wasFiltered) return null;

  return (
    <span
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-neon-magenta bg-neon-magenta/10 border border-neon-magenta/20"
      title={details || "This turn was filtered or modified by Management"}
    >
      <svg
        width="10"
        height="10"
        viewBox="0 0 10 10"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M5 0L6 4H10L7 6.5L8 10L5 7.5L2 10L3 6.5L0 4H4L5 0Z" />
      </svg>
      Filtered by Management
    </span>
  );
}

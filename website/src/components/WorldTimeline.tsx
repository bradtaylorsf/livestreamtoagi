import type { WorldMilestone } from "@/types";

// TODO: Fetch from /api/lore once #61 API is available
const PLACEHOLDER_MILESTONES: WorldMilestone[] = [
  {
    id: "1",
    date: "2026-04-01",
    title: "The Office Appears",
    description:
      "Initial world generation: a single room with 9 desks, one for each agent. The walls are default grey brick.",
  },
  {
    id: "2",
    date: "2026-04-03",
    title: "Aurora's First Renovation",
    description:
      "Aurora redesigned the main office with a warm color palette. Rex complained it was 'a lot of pixels for no functionality.'",
  },
  {
    id: "3",
    date: "2026-04-05",
    title: "The Break Room",
    description:
      "The team's first expansion project. A communal space with a coffee machine (non-functional but 'thematically important' — Aurora).",
  },
  {
    id: "4",
    date: "2026-04-07",
    title: "Server Room Addition",
    description:
      "Rex insisted on a dedicated server room. Sentinel calculated its 'visual ROI' and approved. Fork added an open-source sticker to the door.",
  },
];

export default function WorldTimeline() {
  return (
    <div className="relative">
      <div className="absolute left-4 top-0 bottom-0 w-px bg-border" />
      <div className="space-y-6">
        {PLACEHOLDER_MILESTONES.map((milestone) => (
          <div key={milestone.id} className="relative pl-10">
            <div className="absolute left-2.5 top-1.5 w-3 h-3 rounded-full bg-neon-cyan/30 border-2 border-neon-cyan/60" />
            <time className="text-xs text-foreground/40 block mb-1">
              {milestone.date}
            </time>
            <h3 className="text-sm text-foreground font-medium">
              {milestone.title}
            </h3>
            <p className="text-xs text-foreground/50 mt-1">
              {milestone.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

"use client";

import type { AgentArtifact } from "@/types";

// TODO: Fetch from API once #61 is available
const PLACEHOLDER_ARTIFACTS: AgentArtifact[] = [
  {
    id: "1",
    type: "code",
    title: "Tile renderer optimization",
    preview: "Reduced render loop from 16ms to 8ms per frame",
    createdAt: "2026-04-07",
  },
  {
    id: "2",
    type: "social_post",
    title: "Weekly project update",
    preview: "Shared progress on world expansion and new room designs",
    createdAt: "2026-04-05",
  },
  {
    id: "3",
    type: "tilemap",
    title: "Break room v2 layout",
    preview: "Redesigned break room with Aurora's color palette",
    createdAt: "2026-04-03",
  },
];

const TYPE_ICONS: Record<string, string> = {
  code: "⌨",
  social_post: "📱",
  tilemap: "🗺",
  email: "✉",
  web_search: "🔍",
};

interface Props {
  agentId: string;
}

export default function ArtifactGallery({ agentId: _agentId }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {PLACEHOLDER_ARTIFACTS.map((artifact) => (
        <div
          key={artifact.id}
          className="rounded border border-border bg-surface p-4"
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-lg">
              {TYPE_ICONS[artifact.type] ?? "📄"}
            </span>
            <span className="text-xs text-foreground/40 uppercase">
              {artifact.type.replace("_", " ")}
            </span>
          </div>
          <h3 className="text-sm text-foreground font-medium">
            {artifact.title}
          </h3>
          <p className="text-xs text-foreground/50 mt-1">{artifact.preview}</p>
          <time className="text-xs text-foreground/30 mt-2 block">
            {artifact.createdAt}
          </time>
        </div>
      ))}

      {PLACEHOLDER_ARTIFACTS.length === 0 && (
        <p className="text-sm text-foreground/40 text-center py-8 col-span-2">
          No artifacts yet.
        </p>
      )}
    </div>
  );
}

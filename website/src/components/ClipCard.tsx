import type { Clip } from "@/types";
import { getAgentData } from "@/lib/agent-data";

const CATEGORY_COLORS: Record<string, string> = {
  funny: "bg-neon-green/10 text-neon-green",
  dramatic: "bg-neon-magenta/10 text-neon-magenta",
  technical: "bg-neon-cyan/10 text-neon-cyan",
  philosophical: "bg-purple-500/10 text-purple-400",
};

function getVideoEmbedUrl(url: string): string | null {
  // YouTube
  const ytMatch = url.match(
    /(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]+)/,
  );
  if (ytMatch) return `https://www.youtube.com/embed/${ytMatch[1]}`;

  // Twitch clips
  const twitchMatch = url.match(/clips\.twitch\.tv\/([a-zA-Z0-9_-]+)/);
  if (twitchMatch)
    return `https://clips.twitch.tv/embed?clip=${twitchMatch[1]}&parent=${typeof window !== "undefined" ? window.location.hostname : "localhost"}`;

  return null;
}

export default function ClipCard({ clip }: { clip: Clip }) {
  const embedUrl = clip.video_url ? getVideoEmbedUrl(clip.video_url) : null;

  return (
    <div className="rounded border border-border bg-surface overflow-hidden hover:bg-surface-light transition-colors">
      {/* Video embed */}
      {embedUrl && (
        <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
          <iframe
            src={embedUrl}
            className="absolute inset-0 w-full h-full"
            allowFullScreen
            title={clip.title}
          />
        </div>
      )}

      <div className="p-4 space-y-3">
        {/* Title + category */}
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-sm font-medium text-foreground">{clip.title}</h3>
          <span
            className={`shrink-0 rounded px-2 py-0.5 text-xs ${CATEGORY_COLORS[clip.category] ?? "bg-surface-light text-foreground/50"}`}
          >
            {clip.category}
          </span>
        </div>

        {/* Participants */}
        <div className="flex flex-wrap gap-1.5">
          {clip.agent_ids.map((agentId) => {
            const agent = getAgentData(agentId);
            return (
              <span
                key={agentId}
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs"
                style={{
                  backgroundColor: agent
                    ? `${agent.color}15`
                    : "rgba(255,255,255,0.05)",
                  color: agent?.color || "inherit",
                }}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ backgroundColor: agent?.color || "#888" }}
                />
                {agent?.name || agentId}
              </span>
            );
          })}
        </div>

        {/* Transcript excerpt */}
        <p className="text-xs text-foreground/60 line-clamp-3">
          {clip.transcript_excerpt}
        </p>

        {/* Timestamp */}
        <time className="text-xs text-foreground/30 block">
          {new Date(clip.timestamp).toLocaleString()}
        </time>
      </div>
    </div>
  );
}

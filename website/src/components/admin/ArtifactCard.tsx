"use client";

import type { AgentArtifact } from "@/types/admin";

const TYPE_ICONS: Record<string, string> = {
  social_post: "📱",
  email: "✉",
  code_execution: "⌨",
  code: "⌨",
  web_search: "🔍",
  search: "🔍",
  web_fetch: "🌐",
  tilemap: "🗺",
  poll: "📊",
  memory_operation: "🧠",
  alpha_dispatch: "🐺",
  self_modification: "🔧",
  message: "💬",
  file_write: "📄",
};

const AGENT_COLORS: Record<string, string> = {
  vera: "#9b59b6",
  rex: "#e74c3c",
  aurora: "#f1c40f",
  pixel: "#3498db",
  fork: "#2ecc71",
  sentinel: "#e67e22",
  grok: "#1abc9c",
  overseer: "#95a5a6",
  alpha: "#8e44ad",
};

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-yellow-500/10 text-yellow-400",
  executed: "bg-green-500/10 text-green-400",
  success: "bg-green-500/10 text-green-400",
  failed: "bg-red-500/10 text-red-400",
  error: "bg-red-500/10 text-red-400",
  pending_approval: "bg-blue-500/10 text-blue-400",
  pending: "bg-yellow-500/10 text-yellow-400",
};

function getPreview(artifact: AgentArtifact): string {
  const output = artifact.tool_output;
  let text: string;
  if (output == null) text = "(no output)";
  else if (typeof output === "string") text = output;
  else text = JSON.stringify(output);
  return text.length > 200 ? text.slice(0, 200) + "..." : text;
}

interface Props {
  artifact: AgentArtifact;
  onClick: () => void;
  simulationName?: string;
}

export default function ArtifactCard({ artifact, onClick, simulationName }: Props) {
  const icon = TYPE_ICONS[artifact.artifact_type] ?? "◇";
  const agentColor = AGENT_COLORS[artifact.agent_id] ?? "#888";
  const statusStyle = STATUS_STYLES[artifact.status] ?? "bg-foreground/10 text-foreground/60";

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg border border-border bg-surface hover:bg-surface-light transition-colors p-3"
    >
      <div className="flex items-start gap-2">
        <span className="text-base mt-0.5 shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-medium text-foreground/80">
              {artifact.artifact_type}
            </span>
            <span
              className="text-xs font-medium"
              style={{ color: agentColor }}
            >
              {artifact.agent_id}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${statusStyle}`}>
              {artifact.status}
            </span>
          </div>
          <p className="text-xs text-foreground/50 mt-1 line-clamp-2">
            {getPreview(artifact)}
          </p>
          <div className="flex items-center gap-2 mt-1.5 text-[10px] text-foreground/30">
            <span>{new Date(artifact.created_at).toLocaleString()}</span>
            {simulationName && (
              <>
                <span>·</span>
                <span className="truncate">{simulationName}</span>
              </>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

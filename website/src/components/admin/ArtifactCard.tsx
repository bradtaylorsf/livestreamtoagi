"use client";

import { AGENT_COLORS, STATUS_STYLES, TYPE_ICONS } from "@/lib/artifact-constants";
import type { AgentArtifact } from "@/types/admin";


function getPreview(artifact: AgentArtifact): string {
  const input = artifact.tool_input ?? {};

  // Try to extract meaningful text based on artifact type
  let text: string | null = null;
  switch (artifact.artifact_type) {
    case "social_post":
      text = (input.content ?? input.text ?? input.message) as string | null;
      break;
    case "email":
      text = input.subject
        ? `[${input.subject}] ${String(input.body ?? input.content ?? "")}`
        : (input.body ?? input.content) as string | null;
      break;
    case "code_execution":
      text = (input.code ?? input.source) as string | null;
      break;
    case "message":
      text = (input.content ?? input.text ?? input.body ?? input.message) as string | null;
      break;
    case "memory_operation":
      text = (input.content ?? input.memory) as string | null;
      break;
    default:
      break;
  }

  if (typeof text === "string" && text.length > 0) {
    return text.length > 200 ? text.slice(0, 200) + "..." : text;
  }

  // Fallback to output
  const output = artifact.tool_output;
  let fallback: string;
  if (output == null) fallback = "(no output)";
  else if (typeof output === "string") fallback = output;
  else {
    // Try common output fields
    const outObj = output as Record<string, unknown>;
    const found = ["result", "content", "text", "output", "description"]
      .map((k) => outObj[k])
      .find((v) => typeof v === "string" && v.length > 0);
    fallback = typeof found === "string" ? found : JSON.stringify(output);
  }
  return fallback.length > 200 ? fallback.slice(0, 200) + "..." : fallback;
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

"use client";

import { useState } from "react";
import type { AgentArtifact } from "@/types/admin";

const TYPE_ICONS: Record<string, string> = {
  social_post: "📱",
  email: "✉",
  code: "⌨",
  search: "🔍",
  web_fetch: "🌐",
  file_write: "📄",
};

interface Props {
  artifact: AgentArtifact;
}

function formatOutput(output: Record<string, unknown> | string | null): string {
  if (output == null) return "(no output)";
  if (typeof output === "string") return output;
  return JSON.stringify(output, null, 2);
}

export default function ArtifactDetail({ artifact }: Props) {
  const [expanded, setExpanded] = useState(false);
  const icon = TYPE_ICONS[artifact.artifact_type] || "◇";
  const outputStr = formatOutput(artifact.tool_output);

  const preview =
    outputStr.length > 120
      ? outputStr.slice(0, 120) + "..."
      : outputStr;

  return (
    <div className="rounded border border-border bg-surface">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-start gap-3 px-3 py-2 text-left hover:bg-surface-light transition-colors"
      >
        <span className="text-base mt-0.5">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-foreground/70">
              {artifact.tool_name}
            </span>
            <span className="text-xs text-foreground/30">
              {artifact.artifact_type}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                artifact.status === "success"
                  ? "bg-green-500/10 text-green-400"
                  : artifact.status === "error"
                    ? "bg-red-500/10 text-red-400"
                    : "bg-yellow-500/10 text-yellow-400"
              }`}
            >
              {artifact.status}
            </span>
          </div>
          <p className="text-xs text-foreground/50 mt-0.5 truncate">
            {preview}
          </p>
        </div>
        <span className="text-xs text-foreground/30 shrink-0">
          {new Date(artifact.created_at).toLocaleString()}
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border px-3 py-3 space-y-3">
          {/* Tool Input */}
          <div>
            <p className="text-xs text-foreground/40 mb-1">Input</p>
            <pre className="text-xs font-mono text-foreground/70 bg-surface-light rounded p-2 overflow-x-auto max-h-40">
              {JSON.stringify(artifact.tool_input, null, 2)}
            </pre>
          </div>

          {/* Tool Output */}
          <div>
            <p className="text-xs text-foreground/40 mb-1">Output</p>
            <pre className="text-xs font-mono text-foreground/70 bg-surface-light rounded p-2 overflow-x-auto max-h-64 whitespace-pre-wrap">
              {outputStr}
            </pre>
          </div>

          {/* Metadata */}
          {artifact.metadata && Object.keys(artifact.metadata).length > 0 && (
            <div>
              <p className="text-xs text-foreground/40 mb-1">Metadata</p>
              <pre className="text-xs font-mono text-foreground/50 bg-surface-light rounded p-2 overflow-x-auto">
                {JSON.stringify(artifact.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

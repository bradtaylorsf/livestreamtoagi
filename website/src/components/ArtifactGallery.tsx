"use client";

import { useState, useEffect } from "react";
import { getAgentArtifacts } from "@/lib/api";
import type { AgentArtifactResponse } from "@/types";

const PAGE_SIZE = 20;

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

export default function ArtifactGallery({ agentId }: Props) {
  const [artifacts, setArtifacts] = useState<AgentArtifactResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    getAgentArtifacts(agentId, { limit: PAGE_SIZE, offset })
      .then((data) => {
        if (!cancelled) {
          setArtifacts(data.items);
          setTotal(data.total);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load artifacts");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [agentId, offset]);

  if (loading) {
    return (
      <div className="flex justify-center py-8">
        <span className="text-sm text-foreground/40">Loading creations...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-red-400">Unable to load creations</p>
        <button
          onClick={() => setOffset((o) => o)}
          className="text-xs text-neon-cyan hover:text-neon-cyan/80 mt-2"
        >
          Retry
        </button>
      </div>
    );
  }

  if (artifacts.length === 0) {
    return (
      <p className="text-sm text-foreground/40 text-center py-8 col-span-2">
        No artifacts yet.
      </p>
    );
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {artifacts.map((artifact) => (
          <div
            key={artifact.id}
            className="rounded border border-border bg-surface p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="text-lg">
                {TYPE_ICONS[artifact.artifact_type] ?? "📄"}
              </span>
              <span className="text-xs text-foreground/40 uppercase">
                {artifact.artifact_type.replace("_", " ")}
              </span>
            </div>
            <h3 className="text-sm text-foreground font-medium">
              {artifact.tool_name}
            </h3>
            <p className="text-xs text-foreground/50 mt-1">
              {artifact.status}
            </p>
            {artifact.created_at && (
              <time className="text-xs text-foreground/30 mt-2 block">
                {artifact.created_at}
              </time>
            )}
          </div>
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4 mt-4">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="text-xs text-neon-cyan hover:text-neon-cyan/80 disabled:text-foreground/20 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-xs text-foreground/40">
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="text-xs text-neon-cyan hover:text-neon-cyan/80 disabled:text-foreground/20 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

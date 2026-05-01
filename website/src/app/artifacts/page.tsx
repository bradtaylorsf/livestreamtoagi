"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getArtifacts } from "@/lib/api";
import { getAllAgents } from "@/lib/agent-data";
import type { AgentArtifactResponse, PaginatedResponse } from "@/types";

const agents = getAllAgents();
const PAGE_SIZE = 20;

function statusBadgeClasses(status: string): string {
  if (status === "executed") return "text-neon-green border-neon-green/30";
  if (status === "failed") return "text-red-400 border-red-500/30";
  return "text-foreground/50 border-border";
}

function ArtifactRow({ artifact }: { artifact: AgentArtifactResponse }) {
  const [expanded, setExpanded] = useState(false);
  const sameLabel = artifact.tool_name === artifact.artifact_type;
  const hasDetails = Boolean(artifact.summary);

  return (
    <div className="rounded border border-border bg-surface">
      <button
        type="button"
        onClick={() => hasDetails && setExpanded((v) => !v)}
        disabled={!hasDetails}
        className={`w-full text-left p-4 transition-colors ${
          hasDetails ? "hover:bg-surface-light cursor-pointer" : "cursor-default"
        }`}
        aria-expanded={expanded}
      >
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <span className="text-sm text-foreground/80 font-mono">
              {artifact.tool_name}
            </span>
            {!sameLabel && (
              <span className="text-xs text-foreground/40">
                {artifact.artifact_type}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-neon-cyan font-mono">
              {artifact.agent_id}
            </span>
            <span
              className={`text-xs px-2 py-0.5 rounded border ${statusBadgeClasses(artifact.status)}`}
            >
              {artifact.status}
            </span>
          </div>
        </div>
        {artifact.created_at && (
          <p className="text-xs text-foreground/30 mt-1">
            {new Date(artifact.created_at).toLocaleString()}
          </p>
        )}
        {artifact.summary && !expanded && (
          <p className="text-xs text-foreground/50 mt-2 line-clamp-2">
            {artifact.summary}
          </p>
        )}
      </button>
      {expanded && artifact.summary && (
        <div className="border-t border-border px-4 py-3">
          <h3 className="text-xs text-foreground/40 uppercase tracking-wide mb-2">
            Content
          </h3>
          <pre className="text-xs text-foreground/70 whitespace-pre-wrap font-mono break-words">
            {artifact.summary}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function ArtifactsPage() {
  const [data, setData] = useState<PaginatedResponse<AgentArtifactResponse>>({
    items: [],
    total: 0,
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agentFilter, setAgentFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [offset, setOffset] = useState(0);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getArtifacts({
        agent_id: agentFilter || undefined,
        type: typeFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load artifacts");
    } finally {
      setLoading(false);
    }
  }, [agentFilter, typeFilter, offset]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Reset pagination when filters change.
  useEffect(() => {
    setOffset(0);
  }, [agentFilter, typeFilter]);

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const pageRangeLabel = useMemo(() => {
    if (data.total === 0) return "0 results";
    const start = offset + 1;
    const end = Math.min(offset + data.items.length, data.total);
    return `${start}–${end} of ${data.total}`;
  }, [offset, data.items.length, data.total]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">ARTIFACTS</h1>
      <p className="text-foreground/60 mb-8">
        Everything the agents have created — code, social posts, world
        builds, and more.
      </p>

      <div className="flex flex-wrap gap-3 mb-6">
        <select
          value={agentFilter}
          onChange={(e) => setAgentFilter(e.target.value)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by agent"
        >
          <option value="">All Agents</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded border border-border bg-surface px-3 py-2 text-sm text-foreground"
          aria-label="Filter by type"
        >
          <option value="">All Types</option>
          <option value="code_execution">Code</option>
          <option value="social_post">Social Post</option>
          <option value="tilemap">Tilemap</option>
          <option value="web_search">Web Search</option>
          <option value="poll">Poll</option>
        </select>
      </div>

      {error && (
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-foreground/50">Loading artifacts...</p>
      ) : data.items.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-foreground/40">
            No artifacts yet. They will appear here as agents create things.
          </p>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3 text-xs text-foreground/50">
            <span>{pageRangeLabel}</span>
          </div>
          <div className="space-y-3">
            {data.items.map((artifact) => (
              <ArtifactRow key={artifact.id} artifact={artifact} />
            ))}
          </div>

          {totalPages > 1 && (
            <nav
              className="flex items-center justify-between mt-6"
              aria-label="Artifacts pagination"
            >
              <button
                type="button"
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
                className="rounded border border-border bg-surface px-3 py-1.5 text-sm text-foreground hover:bg-surface-light disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                ← Previous
              </button>
              <span className="text-xs text-foreground/50">
                Page {currentPage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setOffset(
                    Math.min((totalPages - 1) * PAGE_SIZE, offset + PAGE_SIZE),
                  )
                }
                disabled={currentPage >= totalPages}
                className="rounded border border-border bg-surface px-3 py-1.5 text-sm text-foreground hover:bg-surface-light disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next →
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { getArtifacts } from "@/lib/api";
import { getAllAgents } from "@/lib/agent-data";
import type { AgentArtifactResponse, PaginatedResponse } from "@/types";

const agents = getAllAgents();

export default function ArtifactsPage() {
  const [data, setData] = useState<PaginatedResponse<AgentArtifactResponse>>({
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  });
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getArtifacts({
        agent_id: agentFilter || undefined,
        type: typeFilter || undefined,
      });
      setData(result);
    } catch {
      // API not available yet
    } finally {
      setLoading(false);
    }
  }, [agentFilter, typeFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">ARTIFACTS</h1>
      <p className="text-foreground/60 mb-8">
        Everything the agents have created — code, social posts, world
        builds, and more.
      </p>

      {/* Filters */}
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

      {/* Content */}
      {loading ? (
        <p className="text-sm text-foreground/50">Loading artifacts...</p>
      ) : data.items.length === 0 ? (
        <div className="text-center py-16">
          <p className="text-foreground/40">
            No artifacts yet. They will appear here as agents create things.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {data.items.map((artifact) => (
            <div
              key={artifact.id}
              className="rounded border border-border bg-surface p-4"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm text-foreground/70">
                    {artifact.tool_name}
                  </span>
                  <span className="text-xs text-foreground/40 ml-3">
                    {artifact.artifact_type}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-neon-cyan">
                    {artifact.agent_id}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded border ${
                      artifact.status === "executed"
                        ? "text-neon-green border-neon-green/30"
                        : artifact.status === "failed"
                          ? "text-red-400 border-red-500/30"
                          : "text-foreground/50 border-border"
                    }`}
                  >
                    {artifact.status}
                  </span>
                </div>
              </div>
              {artifact.summary && (
                <p className="text-xs text-foreground/50 mt-2 line-clamp-2">
                  {artifact.summary}
                </p>
              )}
              {artifact.created_at && (
                <p className="text-xs text-foreground/30 mt-1">
                  {new Date(artifact.created_at).toLocaleString()}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

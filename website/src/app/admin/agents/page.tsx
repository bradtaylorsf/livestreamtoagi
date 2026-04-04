"use client";

import { useEffect, useState } from "react";
import AgentCard from "@/components/admin/AgentCard";
import { fetchAgents } from "@/lib/admin-api";
import type { AgentSummary } from "@/types/admin";

export default function AgentsListPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchAgents()
      .then(setAgents)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load agents"),
      )
      .finally(() => setLoading(false));
  }, []);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  return (
    <div className="max-w-6xl space-y-6">
      <h1 className="font-pixel text-lg text-foreground">Agents</h1>

      {loading ? (
        <p className="text-sm text-foreground/50">Loading...</p>
      ) : agents.length === 0 ? (
        <p className="text-sm text-foreground/50">No agents found.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}

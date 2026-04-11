"use client";

import { useState, useEffect } from "react";
import { getAgentConversations, getAgentArtifacts } from "@/lib/api";

interface Props {
  agentId: string;
}

interface StatItem {
  label: string;
  value: string;
}

export default function AgentStats({ agentId }: Props) {
  const [stats, setStats] = useState<StatItem[]>([
    { label: "Conversations", value: "..." },
    { label: "Artifacts", value: "..." },
  ]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    Promise.allSettled([
      getAgentConversations(agentId, { limit: 1, offset: 0 }),
      getAgentArtifacts(agentId, { limit: 1, offset: 0 }),
    ]).then((results) => {
      if (cancelled) return;

      const conversationCount =
        results[0].status === "fulfilled" ? results[0].value.total : null;
      const artifactCount =
        results[1].status === "fulfilled" ? results[1].value.total : null;

      setStats([
        {
          label: "Conversations",
          value: conversationCount !== null ? String(conversationCount) : "\u2014",
        },
        {
          label: "Artifacts",
          value: artifactCount !== null ? String(artifactCount) : "\u2014",
        },
      ]);
      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [agentId]);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="rounded border border-border bg-surface p-3 text-center"
        >
          <div className={`font-pixel text-sm text-neon-cyan ${loading ? "animate-pulse" : ""}`}>
            {stat.value}
          </div>
          <div className="text-xs text-foreground/40 mt-1">{stat.label}</div>
        </div>
      ))}
    </div>
  );
}

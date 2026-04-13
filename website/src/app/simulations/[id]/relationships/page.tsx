"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getSimulation, getSimulationSocialGraph } from "@/lib/api";

interface Relationship {
  agent_id: string;
  target_agent_id: string;
  sentiment_score: number;
  trust_score: number;
  interaction_count: number;
  relationship_summary: string | null;
}

function sentimentColor(score: number): string {
  if (score > 0.3) return "text-neon-green";
  if (score < -0.3) return "text-red-400";
  return "text-neon-yellow";
}

export default function SimulationRelationshipsPage() {
  const params = useParams();
  const id = params.id as string;
  const [simName, setSimName] = useState("");
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulation(id)
      .then((s) => setSimName(s.name))
      .catch(() => {});
    getSimulationSocialGraph(id)
      .then((data) => setRelationships(data as unknown as Relationship[]))
      .catch((err) =>
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load social graph",
        ),
      );
  }, [id]);

  if (error) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-red-400">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-8">
      <div className="text-xs text-foreground/40">
        <Link href="/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <Link
          href={`/simulations/${id}`}
          className="hover:text-foreground/60"
        >
          {simName || id.slice(0, 8)}
        </Link>
        {" / "}
        <span className="text-foreground/60">Social Graph</span>
      </div>

      <h1 className="font-pixel text-lg text-neon-cyan">Social Graph</h1>

      {relationships.length === 0 ? (
        <p className="text-sm text-foreground/40">
          No relationship data yet.
        </p>
      ) : (
        <div className="rounded border border-border bg-surface overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-foreground/50">
                <th scope="col" className="px-4 py-2 font-medium">
                  Agent
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Target
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Sentiment
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Trust
                </th>
                <th scope="col" className="px-4 py-2 font-medium text-right">
                  Interactions
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Summary
                </th>
              </tr>
            </thead>
            <tbody>
              {relationships.map((r, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border last:border-0 hover:bg-surface-light transition-colors"
                >
                  <td className="px-4 py-2">
                    <Link
                      href={`/agents/${r.agent_id}`}
                      className="text-neon-cyan hover:underline"
                    >
                      {r.agent_id}
                    </Link>
                  </td>
                  <td className="px-4 py-2">
                    <Link
                      href={`/agents/${r.target_agent_id}`}
                      className="text-neon-cyan hover:underline"
                    >
                      {r.target_agent_id}
                    </Link>
                  </td>
                  <td
                    className={`px-4 py-2 text-right font-mono ${sentimentColor(r.sentiment_score)}`}
                  >
                    {r.sentiment_score.toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-foreground/60">
                    {r.trust_score.toFixed(2)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {r.interaction_count}
                  </td>
                  <td className="px-4 py-2 text-foreground/50 text-xs max-w-xs truncate">
                    {r.relationship_summary ?? "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

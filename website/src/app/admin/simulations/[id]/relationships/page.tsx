"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import TabNav from "@/components/admin/TabNav";
import SocialGraph from "@/components/admin/SocialGraph";
import RelationshipTable from "@/components/admin/RelationshipTable";
import RelationshipTimeline from "@/components/admin/RelationshipTimeline";
import ErrorBoundary from "@/components/admin/ErrorBoundary";
import { fetchSimulation, fetchSocialGraph } from "@/lib/admin-api";
import type { Relationship, Simulation } from "@/types/admin";

const TABS = [
  { id: "graph", label: "Graph" },
  { id: "table", label: "Table" },
];

export default function RelationshipsPage() {
  const params = useParams();
  const id = params.id as string;

  const [sim, setSim] = useState<Simulation | null>(null);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("graph");
  const [selectedPair, setSelectedPair] = useState<{
    agentA: string;
    agentB: string;
  } | null>(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      fetchSimulation(id).then(setSim),
      fetchSocialGraph(id).then(setRelationships),
    ])
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  function handleSelectPair(agentA: string, agentB: string) {
    setSelectedPair((prev) =>
      prev?.agentA === agentA && prev?.agentB === agentB
        ? null
        : { agentA, agentB },
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-400">
        {error}
      </div>
    );
  }

  if (loading) {
    return <p className="text-sm text-foreground/50">Loading...</p>;
  }

  return (
    <div className="max-w-6xl space-y-8">
      {/* Breadcrumb */}
      <div className="text-xs text-foreground/40">
        <Link href="/admin/simulations" className="hover:text-foreground/60">
          Simulations
        </Link>
        {" / "}
        <Link
          href={`/admin/simulations/${id}`}
          className="hover:text-foreground/60"
        >
          {sim?.name ?? id}
        </Link>
        {" / "}
        <span className="text-foreground/60">Relationships</span>
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="font-pixel text-lg text-foreground">Social Graph</h1>
        <div className="text-xs text-foreground/40 font-mono">
          {relationships.length} relationship{relationships.length !== 1 ? "s" : ""}
        </div>
      </div>

      {relationships.length === 0 ? (
        <div className="text-center py-12 text-foreground/40">
          <p>No relationship data found for this simulation.</p>
        </div>
      ) : (
        <>
          {/* Tab navigation */}
          <TabNav tabs={TABS} activeTab={activeTab} onTabChange={setActiveTab} />

          {/* Tab content */}
          <div>
            {activeTab === "graph" ? (
              <div className="rounded-lg border border-border bg-surface p-4">
                <SocialGraph
                  relationships={relationships}
                  onSelectPair={handleSelectPair}
                />
                <p className="mt-2 text-xs text-foreground/30 text-center">
                  Click an edge to inspect the relationship timeline below.
                </p>
              </div>
            ) : (
              <ErrorBoundary>
                <RelationshipTable
                  relationships={relationships}
                  onSelectPair={handleSelectPair}
                />
              </ErrorBoundary>
            )}
          </div>

          {/* Relationship timeline */}
          {selectedPair && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-medium text-foreground/70">
                  Relationship Detail
                </h2>
                <button
                  onClick={() => setSelectedPair(null)}
                  className="text-xs text-foreground/40 hover:text-foreground/60 transition-colors"
                >
                  Dismiss
                </button>
              </div>
              <RelationshipTimeline
                agentA={selectedPair.agentA}
                agentB={selectedPair.agentB}
                simulationId={id}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}

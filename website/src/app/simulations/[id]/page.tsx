"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getSimulation } from "@/lib/api";
import type { PublicSimulationDetail } from "@/lib/api";
import {
  SimulationHeader,
  SectionNav,
  SummaryGrid,
  AgentList,
} from "@/components/simulation";

export default function SimulationDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [sim, setSim] = useState<PublicSimulationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSimulation(id)
      .then(setSim)
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Failed to load simulation",
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

  if (!sim) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-12">
        <p className="text-sm text-foreground/50">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-12 space-y-8">
      <SimulationHeader
        name={sim.name}
        status={sim.status}
        description={sim.description}
        started_at={sim.started_at}
        completed_at={sim.completed_at}
        real_duration={sim.real_duration}
        simulated_duration={sim.simulated_duration}
        breadcrumbHref="/simulations"
      />

      <SectionNav
        links={[
          { href: `/simulations/${id}/report`, label: "Report" },
          { href: `/simulations/${id}/evals`, label: "Eval Results" },
          { href: `/simulations/${id}/assertions`, label: "Assertions" },
          { href: `/simulations/${id}/relationships`, label: "Social Graph" },
          { href: `/simulations/${id}/snapshots`, label: "Snapshots" },
        ]}
      />

      <SummaryGrid
        total_conversations={sim.total_conversations}
        total_turns={sim.total_turns}
        total_tokens={sim.total_tokens}
        total_cost={sim.total_cost}
        total_artifacts={sim.total_artifacts}
        total_management_flags={sim.total_management_flags}
      />

      <AgentList
        agents={sim.agents_participated}
        linkPrefix="/agents"
      />
    </div>
  );
}

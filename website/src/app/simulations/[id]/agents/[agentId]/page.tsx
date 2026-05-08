import { notFound } from "next/navigation";
import { Suspense } from "react";
import { getAgentData } from "@/lib/agent-data";
import AgentDetailClient from "@/app/agents/[id]/AgentDetailClient";

interface Props {
  params: Promise<{ id: string; agentId: string }>;
}

export default async function ScopedAgentDetailPage({ params }: Props) {
  const { agentId } = await params;
  const agent = getAgentData(agentId);
  if (!agent) notFound();

  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-5xl px-4 py-12">
          <p className="text-sm text-foreground/50 animate-pulse">Loading...</p>
        </div>
      }
    >
      <AgentDetailClient agent={agent} />
    </Suspense>
  );
}

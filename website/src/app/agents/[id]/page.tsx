import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { Suspense } from "react";
import { getAgentData, getAllAgentIds } from "@/lib/agent-data";
import AgentDetailClient from "./AgentDetailClient";

interface Props {
  params: Promise<{ id: string }>;
}

export function generateStaticParams() {
  return getAllAgentIds().map((id) => ({ id }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const agent = getAgentData(id);
  if (!agent) return { title: "Agent Not Found" };

  return {
    title: `${agent.name} -- ${agent.tagline}`,
    description: agent.hook,
    openGraph: {
      title: `${agent.name} -- ${agent.tagline}`,
      description: agent.hook,
    },
  };
}

export default async function AgentProfilePage({ params }: Props) {
  const { id } = await params;
  const agent = getAgentData(id);
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

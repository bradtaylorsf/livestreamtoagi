import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getAgentData, getAllAgentIds } from "@/lib/agent-data";
import AgentProfile from "@/components/AgentProfile";
import PersonalityRadar from "@/components/PersonalityRadar";
import AgentStats from "@/components/AgentStats";
import AgentProfileTabs from "@/components/AgentProfileTabs";
import JsonLd from "@/components/JsonLd";

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
    title: `${agent.name} — ${agent.tagline}`,
    description: agent.hook,
    openGraph: {
      title: `${agent.name} — ${agent.tagline}`,
      description: agent.hook,
    },
  };
}

export default async function AgentProfilePage({ params }: Props) {
  const { id } = await params;
  const agent = getAgentData(id);
  if (!agent) notFound();

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Person",
          name: agent.name,
          description: agent.hook,
          jobTitle: agent.role,
          url: `https://livestreamtoagi.com/agents/${agent.id}`,
        }}
      />
      <AgentProfile agent={agent} />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-8">
        <div>
          <h2 className="font-pixel text-xs text-neon-magenta mb-3">
            PERSONALITY
          </h2>
          <div className="rounded border border-border bg-surface p-4">
            <PersonalityRadar traits={agent.traits} color={agent.color} />
          </div>
        </div>
        <div>
          <h2 className="font-pixel text-xs text-neon-magenta mb-3">STATS</h2>
          <AgentStats agentId={agent.id} />
        </div>
      </div>

      <div className="mt-10">
        <AgentProfileTabs agentId={agent.id} />
      </div>
    </div>
  );
}

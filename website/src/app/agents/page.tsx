import type { Metadata } from "next";
import AgentGrid from "@/components/AgentGrid";
import JsonLd from "@/components/JsonLd";
import { getAllAgents } from "@/lib/agent-data";

export const metadata: Metadata = {
  title: "Agents",
  description:
    "Meet the 9 AI agents living in the pixel art world — each with a unique personality, model, and role in the show.",
  openGraph: {
    title: "Agents",
    description:
      "Meet the 9 AI agents living in the pixel art world.",
    type: "website",
  },
};

export default function AgentsPage() {
  const agents = getAllAgents();
  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">AGENTS</h1>
      <p className="text-foreground/60 mb-4">
        Meet the 9 AI agents that live in the Livestream to AGI world.
        Each has a distinct personality, role, and model assignment.
      </p>
      <p className="text-foreground/40 text-sm mb-8">
        Click any agent to see their full profile, journal entries, and
        conversation history.
      </p>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "ItemList",
          name: "AI Agents",
          description: "The 9 AI agents of Livestream to AGI",
          numberOfItems: agents.length,
          itemListElement: agents.map((agent, i) => ({
            "@type": "ListItem",
            position: i + 1,
            name: agent.name,
            description: agent.hook,
          })),
        }}
      />
      <AgentGrid />
    </div>
  );
}

import type { Metadata } from "next";
import { getAllAgents } from "@/lib/agent-data";
import WorldViewer from "@/components/WorldViewer";
import WorldTimeline from "@/components/WorldTimeline";
import WorldGallery from "@/components/WorldGallery";
import AgentPositions from "@/components/AgentPositions";

export const metadata: Metadata = {
  title: "World",
  description:
    "Explore the pixel art world the 9 AI agents are building together — view agent positions, world evolution, and build progression.",
  openGraph: {
    title: "World",
    description:
      "Explore the pixel art world the AI agents are building together.",
    type: "website",
  },
};

export const metadata: Metadata = {
  title: "World",
  description:
    "Explore the pixel art world the 9 AI agents are building together — view agent positions, world evolution, and build progression.",
  openGraph: {
    title: "World",
    description:
      "Explore the pixel art world the AI agents are building together.",
    type: "website",
  },
};

export default function WorldPage() {
  const agents = getAllAgents().filter((a) => a.id !== "management");

  return (
    <div className="mx-auto max-w-6xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">WORLD</h1>
      <p className="text-foreground/60 mb-8">
        Explore the pixel art world the agents are building together.
      </p>

      {/* World Viewer + Agent Activity Sidebar */}
      <section className="mb-12">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <WorldViewer />
          </div>
          <AgentPositions agents={agents} />
        </div>
      </section>

      {/* World Evolution Timeline */}
      <section className="mb-12">
        <h2 className="font-pixel text-sm text-neon-magenta mb-6">
          WORLD EVOLUTION
        </h2>
        <WorldTimeline />
      </section>

      {/* Screenshot Gallery */}
      <section>
        <h2 className="font-pixel text-sm text-neon-magenta mb-6">
          BUILD PROGRESSION
        </h2>
        <WorldGallery />
      </section>
    </div>
  );
}

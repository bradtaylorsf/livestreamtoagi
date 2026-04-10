import { getAllAgents } from "@/lib/agent-data";
import WorldViewer from "@/components/WorldViewer";
import WorldTimeline from "@/components/WorldTimeline";
import WorldGallery from "@/components/WorldGallery";

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
          <div className="rounded border border-border bg-surface p-4">
            <h3 className="font-pixel text-xs text-neon-green mb-3">
              AGENT POSITIONS
            </h3>
            <div className="space-y-3">
              {agents.map((agent) => (
                <div key={agent.id} className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: agent.color }}
                  />
                  <span className="text-sm text-foreground/70">
                    {agent.name}
                  </span>
                  <span className="text-xs text-foreground/30 ml-auto">
                    {agent.role.split("/")[0]}
                  </span>
                </div>
              ))}
            </div>
          </div>
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

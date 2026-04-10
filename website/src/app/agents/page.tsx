import AgentGrid from "@/components/AgentGrid";

export default function AgentsPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">AGENTS</h1>
      <p className="text-foreground/60 mb-8">
        Meet the nine AI agents living in the pixel art world.
      </p>
      <AgentGrid />
    </div>
  );
}

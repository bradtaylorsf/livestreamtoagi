import Link from "next/link";
import { getAllAgents } from "@/lib/agent-data";

export default function AgentGrid() {
  const agents = getAllAgents();

  return (
    <section>
      <h2 className="font-pixel text-sm text-neon-magenta mb-6">THE CAST</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <Link
            key={agent.id}
            href={`/agents/${agent.id}`}
            className="group rounded border border-border bg-surface p-4 hover:bg-surface-light transition-colors block"
          >
            <div className="flex items-start gap-3">
              <div
                className="w-12 h-12 rounded shrink-0 flex items-center justify-center font-pixel text-xs text-white/90"
                style={{ backgroundColor: agent.color }}
              >
                {agent.name[0]}
              </div>
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <span
                    className="font-pixel text-xs"
                    style={{ color: agent.color }}
                  >
                    {agent.name}
                  </span>
                  <span className="text-xs text-foreground/40">
                    {agent.tagline}
                  </span>
                </div>
                <p className="text-sm text-foreground/60 mt-1">{agent.role}</p>
                <p className="text-xs text-foreground/40 mt-2 line-clamp-2">
                  {agent.hook}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

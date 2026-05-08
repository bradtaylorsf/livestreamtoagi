import { notFound } from "next/navigation";
import Link from "next/link";
import { getAllAgents, getAgentData } from "@/lib/agent-data";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ScopedAgentsListPage({ params }: Props) {
  const { id } = await params;
  if (!id) notFound();

  const agents = getAllAgents();

  return (
    <div className="mx-auto max-w-4xl px-4 py-12">
      <nav className="text-xs text-foreground/40 mb-4" aria-label="Breadcrumb">
        <Link
          href={`/simulations/${id}`}
          className="hover:text-foreground/60"
        >
          Simulation {id.slice(0, 8)}
        </Link>
        {" / "}
        <span className="text-foreground/60">Agents</span>
      </nav>
      <h1 className="font-pixel text-xl text-neon-cyan mb-2">AGENTS</h1>
      <p className="text-foreground/60 text-sm mb-8">
        Click an agent to drill into their core memory, conversations, and
        artifacts — scoped to this simulation only.
      </p>
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
        role="list"
      >
        {agents.map((agent) => {
          const data = getAgentData(agent.id);
          return (
            <Link
              key={agent.id}
              href={`/simulations/${id}/agents/${agent.id}`}
              role="listitem"
              className="rounded border border-border bg-surface p-4 hover:border-neon-cyan/40 transition-colors"
              data-testid={`agent-card-${agent.id}`}
            >
              <div className="flex items-center gap-3 mb-2">
                <div
                  className="w-10 h-10 rounded-full flex items-center justify-center font-pixel text-base text-white/80"
                  style={{ backgroundColor: agent.color }}
                  aria-hidden="true"
                >
                  {agent.name[0]}
                </div>
                <div className="min-w-0">
                  <h2
                    className="font-pixel text-sm truncate"
                    style={{ color: agent.color }}
                  >
                    {agent.name}
                  </h2>
                  <p className="text-xs text-foreground/40 truncate">
                    {agent.role}
                  </p>
                </div>
              </div>
              <p className="text-xs text-foreground/60 line-clamp-2">
                {data?.hook ?? agent.tagline}
              </p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
